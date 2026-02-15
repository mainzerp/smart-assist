"""Persistent alarm tool for Smart Assist."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from ..const import DOMAIN, PERSISTENT_ALARM_EVENT_UPDATED
from ..context.persistent_alarms import PersistentAlarmManager
from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class AlarmTool(BaseTool):
    """Tool for restart-safe persistent alarms."""

    name = "alarm"
    description = (
        "Manage persistent alarms (set/list/cancel/snooze/status) with absolute times. "
        "Use this for alarm-clock behavior that survives restart; use timer for relative durations."
    )

    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Alarm action",
            required=True,
            enum=["set", "list", "cancel", "snooze", "status"],
        ),
        ToolParameter(
            name="datetime",
            type="string",
            description="ISO datetime (e.g. 2026-02-16T07:30:00+01:00). Required for action=set.",
            required=False,
        ),
        ToolParameter(
            name="date",
            type="string",
            description="Optional date (YYYY-MM-DD). Use with time for action=set if datetime is omitted.",
            required=False,
        ),
        ToolParameter(
            name="time",
            type="string",
            description="Optional time (HH:MM or HH:MM:SS). Use with date for action=set if datetime is omitted.",
            required=False,
        ),
        ToolParameter(
            name="label",
            type="string",
            description="Alarm label (e.g. Morning alarm)",
            required=False,
        ),
        ToolParameter(
            name="message",
            type="string",
            description="Optional alarm message announced when fired",
            required=False,
        ),
        ToolParameter(
            name="alarm_id",
            type="string",
            description="Alarm id or display_id for cancel/snooze/status. Optional for snooze when exactly one recent fired alarm exists.",
            required=False,
        ),
        ToolParameter(
            name="display_id",
            type="string",
            description="Human-readable alarm display_id. Alternative to alarm_id.",
            required=False,
        ),
        ToolParameter(
            name="minutes",
            type="number",
            description="Snooze duration in minutes. Required for action=snooze.",
            required=False,
        ),
        ToolParameter(
            name="active_only",
            type="boolean",
            description="For action=list: when true, only active alarms are returned (default true).",
            required=False,
        ),
    ]

    def __init__(self, hass: HomeAssistant, entry_id: str | None = None) -> None:
        """Initialize alarm tool."""
        super().__init__(hass)
        self._entry_id = entry_id

    async def execute(
        self,
        action: str,
        datetime: str | None = None,
        date: str | None = None,
        time: str | None = None,
        label: str | None = None,
        message: str | None = None,
        alarm_id: str | None = None,
        display_id: str | None = None,
        minutes: int | None = None,
        active_only: bool | None = None,
    ) -> ToolResult:
        """Execute persistent alarm actions."""
        manager = self._get_manager()
        if manager is None:
            return ToolResult(False, "Persistent alarm manager is not available")

        try:
            if action == "set":
                alarm_datetime = self._resolve_datetime(datetime, date, time)
                if not alarm_datetime:
                    return ToolResult(
                        False,
                        "For action=set provide datetime (ISO) or date+time.",
                    )

                alarm, status = manager.create_alarm(alarm_datetime, label, message)
                if alarm is None:
                    return ToolResult(False, status)

                await manager.async_force_save()
                await self._reconcile_managed_alarm(alarm)
                self._emit_alarm_update(alarm, "set")
                return ToolResult(
                    True,
                    (
                        f"Alarm '{alarm['label']}' set for {alarm['scheduled_for']} "
                        f"(id: {alarm['id']}, display_id: {alarm.get('display_id')})."
                    ),
                    data={"alarm": alarm},
                )

            if action == "list":
                only_active = True if active_only is None else bool(active_only)
                alarms = manager.list_alarms(active_only=only_active)
                if not alarms:
                    return ToolResult(True, "No alarms found.", data={"alarms": []})

                lines = []
                for alarm in alarms[:10]:
                    next_trigger = alarm.get("snoozed_until") or alarm.get("scheduled_for")
                    lines.append(
                        f"- {alarm.get('display_id', alarm.get('id'))}: {alarm.get('label')} at {next_trigger} ({alarm.get('status')})"
                    )
                summary = "Active alarms:" if only_active else "Alarms:"
                return ToolResult(
                    True,
                    summary + "\n" + "\n".join(lines),
                    data={"alarms": alarms},
                )

            if action == "cancel":
                alarm_ref = alarm_id or display_id
                if not alarm_ref:
                    return ToolResult(False, "alarm_id or display_id is required for action=cancel")
                if not manager.cancel_alarm(alarm_ref):
                    return ToolResult(False, f"Alarm not found or inactive: {alarm_ref}")
                await manager.async_force_save()
                alarm = manager.get_alarm(alarm_ref)
                if alarm:
                    await self._reconcile_managed_alarm(alarm)
                    self._emit_alarm_update(alarm, "cancel")
                    return ToolResult(
                        True,
                        f"Alarm cancelled: {alarm.get('display_id', alarm.get('id'))}",
                        data={"alarm": alarm},
                    )
                return ToolResult(True, f"Alarm cancelled: {alarm_ref}")

            if action == "snooze":
                explicit_ref = alarm_id or display_id
                resolved_ref, resolve_err = self._resolve_snooze_alarm_ref(manager, explicit_ref)
                if not resolved_ref:
                    return ToolResult(False, resolve_err)
                snooze_minutes = int(minutes or 0)
                alarm, status = manager.snooze_alarm(resolved_ref, snooze_minutes)
                if alarm is None:
                    return ToolResult(False, status)
                await manager.async_force_save()
                await self._reconcile_managed_alarm(alarm)
                self._emit_alarm_update(alarm, "snooze")
                return ToolResult(
                    True,
                    (
                        f"Alarm snoozed until {alarm.get('snoozed_until')} "
                        f"(id: {alarm.get('id')}, display_id: {alarm.get('display_id')})"
                    ),
                    data={"alarm": alarm},
                )

            if action == "status":
                alarm_ref = alarm_id or display_id
                if alarm_ref:
                    alarm = manager.get_alarm(alarm_ref)
                    if alarm is None:
                        return ToolResult(False, f"Alarm not found: {alarm_ref}")
                    next_trigger = alarm.get("snoozed_until") or alarm.get("scheduled_for")
                    return ToolResult(
                        True,
                        (
                            f"Alarm {alarm.get('display_id', alarm.get('id'))}: {alarm.get('label')} at {next_trigger}, "
                            f"status={alarm.get('status')}, active={alarm.get('active')}"
                        ),
                        data={"alarm": alarm},
                    )

                alarms = manager.list_alarms(active_only=True)
                return ToolResult(
                    True,
                    f"Active alarm count: {len(alarms)}",
                    data={"alarms": alarms},
                )

            return ToolResult(False, f"Unknown action: {action}")
        except Exception as err:
            _LOGGER.warning("Alarm tool execution failed: %s", err)
            return ToolResult(False, f"Failed to execute alarm action: {err}")

    def _resolve_snooze_alarm_ref(
        self,
        manager: PersistentAlarmManager,
        explicit_ref: str | None,
    ) -> tuple[str | None, str]:
        """Resolve snooze target with explicit-first and recent-fired fallback."""
        if explicit_ref:
            alarm = manager.get_alarm(explicit_ref)
            if alarm is None:
                return None, f"Alarm not found: {explicit_ref}"
            return str(alarm.get("id")), ""

        recent_hint_ids = [
            str(item)
            for item in (getattr(self, "_recent_fired_alarm_ids", []) or [])
            if isinstance(item, str)
        ]
        hinted_alarms = [
            manager.get_alarm(alarm_ref)
            for alarm_ref in recent_hint_ids
        ]
        hinted_alarms = [
            alarm for alarm in hinted_alarms if alarm and alarm.get("status") == "fired"
        ]
        if len(hinted_alarms) == 1:
            return str(hinted_alarms[0].get("id")), ""
        if len(hinted_alarms) > 1:
            choices = ", ".join(
                str(item.get("display_id") or item.get("id"))
                for item in hinted_alarms[:3]
            )
            return None, f"Multiple recently fired alarms found. Which one should I snooze? ({choices})"

        recent_fired = manager.get_recent_fired_alarms(window_minutes=30, limit=3)
        if len(recent_fired) == 1:
            return str(recent_fired[0].get("id")), ""
        if len(recent_fired) > 1:
            choices = ", ".join(
                str(item.get("display_id") or item.get("id"))
                for item in recent_fired
            )
            return None, f"Multiple recently fired alarms found. Which one should I snooze? ({choices})"

        return None, "No recently fired alarm found. Please provide alarm_id or display_id."

    def _emit_alarm_update(self, alarm: dict[str, Any], reason: str) -> None:
        """Emit lifecycle update event + dashboard signal for alarm changes."""
        self._hass.bus.async_fire(
            PERSISTENT_ALARM_EVENT_UPDATED,
            {
                "entry_id": self._entry_id,
                "alarm_id": alarm.get("id"),
                "display_id": alarm.get("display_id"),
                "status": alarm.get("status"),
                "active": alarm.get("active"),
                "scheduled_for": alarm.get("scheduled_for"),
                "snoozed_until": alarm.get("snoozed_until"),
                "updated_at": alarm.get("updated_at"),
                "reason": reason,
            },
        )
        if self._entry_id:
            async_dispatcher_send(self._hass, f"{DOMAIN}_alarms_updated_{self._entry_id}")

    def _resolve_datetime(
        self,
        dt_value: str | None,
        date_value: str | None,
        time_value: str | None,
    ) -> str | None:
        """Resolve datetime input into timezone-aware ISO string."""
        if dt_value:
            parsed = dt_util.parse_datetime(dt_value)
            if parsed is None:
                try:
                    parsed = datetime.fromisoformat(dt_value)
                except ValueError:
                    return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            return dt_util.as_local(parsed).isoformat()

        if date_value and time_value:
            try:
                parsed = datetime.fromisoformat(f"{date_value}T{time_value}")
            except ValueError:
                return None
            parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            return dt_util.as_local(parsed).isoformat()

        return None

    async def _reconcile_managed_alarm(self, alarm: dict[str, Any]) -> None:
        """Best-effort managed automation sync; never block alarm command success."""
        if not self._entry_id:
            return

        entry_data = self._hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        managed_service = entry_data.get("managed_alarm_automation")
        manager = entry_data.get("persistent_alarm_manager")
        if managed_service is None or manager is None:
            return

        try:
            await managed_service.async_reconcile_alarm(alarm)
            await manager.async_save()
        except Exception as err:
            _LOGGER.warning("Managed alarm reconcile failed after tool action: %s", err)

    def _get_manager(self) -> PersistentAlarmManager | None:
        """Resolve persistent alarm manager from integration runtime data."""
        domain_data = self._hass.data.get(DOMAIN, {})

        if self._entry_id and self._entry_id in domain_data:
            manager = domain_data[self._entry_id].get("persistent_alarm_manager")
            if manager is not None:
                return manager

        for entry_data in domain_data.values():
            if not isinstance(entry_data, dict):
                continue
            manager = entry_data.get("persistent_alarm_manager")
            if manager is not None:
                return manager

        return None
