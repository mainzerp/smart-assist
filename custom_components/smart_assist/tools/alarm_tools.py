"""Persistent alarm tool for Smart Assist."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
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
            description="Alarm id required for cancel/snooze/status by specific alarm",
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
                return ToolResult(
                    True,
                    (
                        f"Alarm '{alarm['label']}' set for {alarm['scheduled_for']} "
                        f"(id: {alarm['id']})."
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
                        f"- {alarm.get('id')}: {alarm.get('label')} at {next_trigger} ({alarm.get('status')})"
                    )
                summary = "Active alarms:" if only_active else "Alarms:"
                return ToolResult(
                    True,
                    summary + "\n" + "\n".join(lines),
                    data={"alarms": alarms},
                )

            if action == "cancel":
                if not alarm_id:
                    return ToolResult(False, "alarm_id is required for action=cancel")
                if not manager.cancel_alarm(alarm_id):
                    return ToolResult(False, f"Alarm not found or inactive: {alarm_id}")
                await manager.async_force_save()
                return ToolResult(True, f"Alarm cancelled: {alarm_id}")

            if action == "snooze":
                if not alarm_id:
                    return ToolResult(False, "alarm_id is required for action=snooze")
                snooze_minutes = int(minutes or 0)
                alarm, status = manager.snooze_alarm(alarm_id, snooze_minutes)
                if alarm is None:
                    return ToolResult(False, status)
                await manager.async_force_save()
                return ToolResult(
                    True,
                    f"Alarm snoozed until {alarm.get('snoozed_until')} (id: {alarm_id})",
                    data={"alarm": alarm},
                )

            if action == "status":
                if alarm_id:
                    alarm = manager.get_alarm(alarm_id)
                    if alarm is None:
                        return ToolResult(False, f"Alarm not found: {alarm_id}")
                    next_trigger = alarm.get("snoozed_until") or alarm.get("scheduled_for")
                    return ToolResult(
                        True,
                        (
                            f"Alarm {alarm_id}: {alarm.get('label')} at {next_trigger}, "
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
