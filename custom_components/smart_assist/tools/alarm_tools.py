"""Persistent alarm tool for Smart Assist."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ALARM_EXECUTION_MODE,
    DEFAULT_ALARM_EXECUTION_MODE,
    DOMAIN,
    POST_FIRE_SNOOZE_CONTEXT_WINDOW_MINUTES,
    PERSISTENT_ALARM_EVENT_UPDATED,
)
from ..context.persistent_alarms import PersistentAlarmManager
from ..utils import normalize_media_player_targets, resolve_media_players_by_satellite
from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class AlarmTool(BaseTool):
    """Tool for restart-safe persistent alarms."""

    name = "alarm"
    description = (
        "Manage persistent alarms (set/list/cancel/snooze/status/edit) with absolute times. "
        "Use this for alarm-clock behavior that survives restart; use timer for relative durations."
    )

    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Alarm operation: set (create), list, cancel, snooze, status, or edit.",
            required=True,
            enum=["set", "list", "cancel", "snooze", "status", "edit"],
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
            description="Optional spoken message when alarm fires. Use this for the actual spoken text only (not for dynamic/weather/news directives).",
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
            minimum=1,
        ),
        ToolParameter(
            name="active_only",
            type="boolean",
            description="For action=list: when true, only active alarms are returned (default true).",
            required=False,
        ),
        ToolParameter(
            name="reactivate",
            type="boolean",
            description="For action=edit on fired/dismissed alarms: reactivate the alarm.",
            required=False,
        ),
        ToolParameter(
            name="recurrence_frequency",
            type="string",
            description="Optional recurrence frequency for set/edit: daily or weekly.",
            required=False,
            enum=["daily", "weekly"],
        ),
        ToolParameter(
            name="recurrence_interval",
            type="number",
            description="Optional recurrence interval (default 1).",
            required=False,
            minimum=1,
            maximum=365,
        ),
        ToolParameter(
            name="recurrence_byweekday",
            type="string",
            description="Optional weekly recurrence weekdays as comma-separated values (e.g. mon,wed,fri).",
            required=False,
        ),
        ToolParameter(
            name="tts_targets",
            type="string",
            description="Optional comma-separated media_player targets for this alarm (e.g. media_player.kitchen,media_player.bedroom).",
            required=False,
        ),
        ToolParameter(
            name="wake_text_dynamic",
            type="boolean",
            description="Optional: generate wake text dynamically via LLM when alarm fires. If weather/news context is requested, this should be true.",
            required=False,
        ),
        ToolParameter(
            name="wake_text_include_weather",
            type="boolean",
            description="Optional: include current weather in dynamic wake text (use only together with dynamic wake text).",
            required=False,
        ),
        ToolParameter(
            name="wake_text_include_news",
            type="boolean",
            description="Optional: include latest headlines in dynamic wake text (use only together with dynamic wake text).",
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
        reactivate: bool | None = None,
        recurrence_frequency: str | None = None,
        recurrence_interval: int | None = None,
        recurrence_byweekday: str | None = None,
        tts_targets: str | None = None,
        wake_text_dynamic: bool | None = None,
        wake_text_include_weather: bool | None = None,
        wake_text_include_news: bool | None = None,
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
                        "For action=set provide 'datetime' (full ISO string like 2026-02-16T07:30:00), or 'date' + 'time' together, or 'time' alone (today/tomorrow will be inferred).",
                    )

                recurrence_payload = self._build_recurrence_payload(
                    recurrence_frequency,
                    recurrence_interval,
                    recurrence_byweekday,
                )
                parsed_tts_targets = self._parse_tts_targets(tts_targets)
                if not parsed_tts_targets:
                    parsed_tts_targets = self._resolve_default_tts_targets()
                (
                    wake_text_dynamic,
                    wake_text_include_weather,
                    wake_text_include_news,
                ) = self._normalize_wake_text_args(
                    wake_text_dynamic,
                    wake_text_include_weather,
                    wake_text_include_news,
                )
                wake_text_options = self._build_wake_text_options(
                    wake_text_dynamic,
                    wake_text_include_weather,
                    wake_text_include_news,
                )
                alarm, status = manager.create_alarm(
                    alarm_datetime,
                    label,
                    message,
                    recurrence=recurrence_payload,
                    source_device_id=getattr(self, "_device_id", None),
                    source_satellite_id=getattr(self, "_satellite_id", None),
                    source_conversation_agent_id=getattr(self, "_conversation_agent_id", None),
                    source_tts_voice=getattr(self, "_source_tts_voice", None),
                    tts_targets=parsed_tts_targets,
                    wake_text=wake_text_options,
                )
                if alarm is None:
                    return ToolResult(False, status)

                await manager.async_force_save()
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
                    direct = alarm.get("direct_execution") if isinstance(alarm.get("direct_execution"), dict) else {}
                    execution_mode = self._get_execution_mode()
                    return ToolResult(
                        True,
                        (
                            f"Alarm {alarm.get('display_id', alarm.get('id'))}: {alarm.get('label')} at {next_trigger}, "
                            f"status={alarm.get('status')}, active={alarm.get('active')}, "
                            f"execution_mode={execution_mode}, direct_state={direct.get('last_state')}, "
                            f"direct_last_executed_at={direct.get('last_executed_at')}"
                        ),
                        data={"alarm": {**alarm, "execution_mode": execution_mode}},
                    )

                alarms = manager.list_alarms(active_only=True)
                return ToolResult(
                    True,
                    f"Active alarm count: {len(alarms)}",
                    data={"alarms": alarms},
                )

            if action == "edit":
                alarm_ref = alarm_id or display_id
                if not alarm_ref:
                    return ToolResult(False, "alarm_id or display_id is required for action=edit")

                updates: dict[str, Any] = {}
                if label is not None:
                    updates["label"] = label
                if message is not None:
                    updates["message"] = message

                alarm_datetime = self._resolve_datetime(datetime, date, time)
                if alarm_datetime:
                    updates["scheduled_for"] = alarm_datetime

                recurrence_payload = self._build_recurrence_payload(
                    recurrence_frequency,
                    recurrence_interval,
                    recurrence_byweekday,
                )
                if recurrence_payload is not None:
                    updates["recurrence"] = recurrence_payload

                delivery_updates: dict[str, Any] = {}
                if tts_targets is not None:
                    delivery_updates["tts_targets"] = self._parse_tts_targets(tts_targets)

                (
                    wake_text_dynamic,
                    wake_text_include_weather,
                    wake_text_include_news,
                ) = self._normalize_wake_text_args(
                    wake_text_dynamic,
                    wake_text_include_weather,
                    wake_text_include_news,
                )
                wake_text_options = self._build_wake_text_options(
                    wake_text_dynamic,
                    wake_text_include_weather,
                    wake_text_include_news,
                )
                if wake_text_options:
                    delivery_updates["wake_text"] = wake_text_options

                if delivery_updates:
                    updates["delivery"] = delivery_updates

                updated_alarm, status = manager.update_alarm(
                    alarm_ref,
                    updates,
                    reactivate=bool(reactivate),
                )
                if updated_alarm is None:
                    return ToolResult(False, status)

                await manager.async_force_save()
                self._emit_alarm_update(updated_alarm, "edit")
                return ToolResult(
                    True,
                    (
                        f"Alarm updated: {updated_alarm.get('display_id', updated_alarm.get('id'))} "
                        f"at {updated_alarm.get('scheduled_for')}"
                    ),
                    data={"alarm": updated_alarm},
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

        recent_fired = manager.get_recent_fired_alarms(
            window_minutes=POST_FIRE_SNOOZE_CONTEXT_WINDOW_MINUTES,
            limit=3,
        )
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

        if time_value and not date_value:
            try:
                now = dt_util.now()
                parsed = datetime.fromisoformat(
                    f"{now.date().isoformat()}T{time_value}"
                )
                parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                if parsed <= now:
                    from datetime import timedelta
                    parsed += timedelta(days=1)
                return dt_util.as_local(parsed).isoformat()
            except ValueError:
                return None

        return None

    def _parse_tts_targets(self, raw_targets: str | None) -> list[str]:
        """Parse comma-separated media_player entity ids into normalized unique list."""
        if raw_targets is None:
            return []

        seen: set[str] = set()
        targets: list[str] = []
        for part in str(raw_targets).split(","):
            entity_id = part.strip().lower()
            if not entity_id or not entity_id.startswith("media_player."):
                continue
            if entity_id in seen:
                continue
            seen.add(entity_id)
            targets.append(entity_id)
        return targets

    def _build_wake_text_options(
        self,
        dynamic: bool | None,
        include_weather: bool | None,
        include_news: bool | None,
    ) -> dict[str, bool]:
        """Build partial wake-text options payload from optional tool args."""
        updates: dict[str, bool] = {}
        if dynamic is not None:
            updates["dynamic"] = bool(dynamic)
        if include_weather is not None:
            updates["include_weather"] = bool(include_weather)
        if include_news is not None:
            updates["include_news"] = bool(include_news)
        return updates

    def _normalize_wake_text_args(
        self,
        dynamic: bool | None,
        include_weather: bool | None,
        include_news: bool | None,
    ) -> tuple[bool | None, bool | None, bool | None]:
        """Normalize wake-text arguments into a consistent payload.

        Language understanding remains model-side. This normalization only
        enforces a logical relationship: requesting weather/news implies
        dynamic wake text generation.
        """
        if (include_weather is True or include_news is True) and dynamic is not True:
            dynamic = True
        return dynamic, include_weather, include_news

    def _build_recurrence_payload(
        self,
        frequency: str | None,
        interval: int | None,
        byweekday: str | None,
    ) -> dict[str, Any] | None:
        """Build recurrence payload from flat tool args."""
        if not frequency:
            return None

        payload: dict[str, Any] = {
            "frequency": str(frequency).strip().lower(),
            "interval": int(interval or 1),
        }
        if byweekday:
            payload["byweekday"] = [part.strip().lower() for part in str(byweekday).split(",") if part.strip()]
        return payload

    def _resolve_default_tts_targets(self) -> list[str]:
        """Resolve default media_player targets from current device/satellite context."""
        by_device = self._resolve_media_players_by_device(getattr(self, "_device_id", None))
        if by_device:
            return by_device

        by_satellite = self._resolve_media_players_by_satellite(getattr(self, "_satellite_id", None))
        if by_satellite:
            return by_satellite

        return []

    def _resolve_media_players_by_device(self, device_id: str | None) -> list[str]:
        """Resolve media_player entity ids linked to the source device."""
        if not device_id:
            return []

        try:
            entity_registry = er.async_get(self._hass)
            entries = er.async_entries_for_device(entity_registry, str(device_id))
        except Exception:
            return []

        players = [
            entry.entity_id
            for entry in entries
            if isinstance(entry.entity_id, str)
            and entry.entity_id.startswith("media_player.")
            and self._hass.states.get(entry.entity_id) is not None
        ]
        return normalize_media_player_targets(players)

    def _resolve_media_players_by_satellite(self, satellite_id: str | None) -> list[str]:
        """Best-effort match from satellite id to media_player entities."""
        return resolve_media_players_by_satellite(self._hass, satellite_id)

    def _normalize_targets(self, targets: Any) -> list[str]:
        """Normalize targets from list or comma-separated string."""
        return normalize_media_player_targets(targets)

    def _get_execution_mode(self) -> str:
        """Return configured alarm execution mode from runtime entry data."""
        if not self._entry_id:
            return DEFAULT_ALARM_EXECUTION_MODE
        entry_data = self._hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        execution_config = entry_data.get("alarm_execution_config") or {}
        return str(execution_config.get(CONF_ALARM_EXECUTION_MODE, DEFAULT_ALARM_EXECUTION_MODE))

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
