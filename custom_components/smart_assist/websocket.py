"""WebSocket API for Smart Assist Dashboard.

Provides real-time data access for the Smart Assist custom panel.
Uses HA's native WebSocket API for secure, authenticated communication.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import voluptuous as vol

from .const import (
    ALARM_EXECUTION_MODE_DIRECT_ONLY,
    CONF_ASK_FOLLOWUP,
    CONF_ALARM_EXECUTION_MODE,
    CONF_CALENDAR_CONTEXT,
    CONF_CLEAN_RESPONSES,
    CONF_ENABLE_CACHE_WARMING,
    CONF_ENABLE_MEMORY,
    CONF_ENABLE_PRESENCE_HEURISTIC,
    CONF_ENABLE_WEB_SEARCH,
    CONF_LLM_PROVIDER,
    CONF_MAX_HISTORY,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_PROVIDER,
    CONF_TEMPERATURE,
    CONF_USER_SYSTEM_PROMPT,
    DEFAULT_ASK_FOLLOWUP,
    DEFAULT_ALARM_EXECUTION_MODE,
    DEFAULT_CALENDAR_CONTEXT,
    DEFAULT_CLEAN_RESPONSES,
    DEFAULT_ENABLE_CACHE_WARMING,
    DEFAULT_ENABLE_MEMORY,
    DEFAULT_ENABLE_PRESENCE_HEURISTIC,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_HISTORY,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TEMPERATURE,
    DEFAULT_USER_SYSTEM_PROMPT,
    DOMAIN,
    MANAGED_ALARM_DISPATCHER_RECONCILED,
    POST_FIRE_SNOOZE_CONTEXT_WINDOW_MINUTES,
    PERSISTENT_ALARM_EVENT_UPDATED,
)
from .context.calendar_reminder import CalendarReminderTracker
from .context.memory import MemoryManager
from .context.persistent_alarms import PersistentAlarmManager

_LOGGER = logging.getLogger(__name__)

_EMPTY_HISTORY_RESULT = {"entries": [], "total": 0}
_EMPTY_TOOL_ANALYTICS_RESULT = {"tools": [], "summary": {}}
_EMPTY_PROMPT_RESULT = {
    "system_prompt": "",
    "user_prompt": "",
    "agent_name": "",
}
_EMPTY_MEMORY_DETAILS_RESULT = {"memories": [], "stats": {}}
_EMPTY_CALENDAR_RESULT = {"enabled": False, "events": [], "calendars": 0}
_EMPTY_REMOVED_RESULT = {"removed": 0}
_DASHBOARD_METRIC_UPDATE_SIGNAL_SUFFIXES = ("metrics_updated", "cache_warming_updated")


def _build_empty_dashboard_result() -> dict[str, Any]:
    """Return empty dashboard payload shape."""
    return {
        "agents": {},
        "tasks": {},
        "memory": {},
        "calendar": {},
        "alarms_summary": {
            "total": 0,
            "active": 0,
            "snoozed": 0,
            "fired": 0,
            "dismissed": 0,
        },
    }


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register WebSocket commands for the Smart Assist dashboard."""
    websocket_api.async_register_command(hass, ws_dashboard_data)
    websocket_api.async_register_command(hass, ws_memory_details)
    websocket_api.async_register_command(hass, ws_memory_rename_user)
    websocket_api.async_register_command(hass, ws_memory_merge_users)
    websocket_api.async_register_command(hass, ws_memory_delete)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_request_history)
    websocket_api.async_register_command(hass, ws_tool_analytics)
    websocket_api.async_register_command(hass, ws_request_history_clear)
    websocket_api.async_register_command(hass, ws_system_prompt)
    websocket_api.async_register_command(hass, ws_calendar_data)
    websocket_api.async_register_command(hass, ws_alarms_data)
    websocket_api.async_register_command(hass, ws_alarm_action)
    _LOGGER.debug("Registered Smart Assist WebSocket commands")


def _get_subentry_config(data: dict[str, Any], key: str, default: Any = None) -> Any:
    """Get config value from subentry data with default."""
    return data.get(key, default)


def _get_primary_entry(hass: HomeAssistant) -> Any | None:
    """Return the single Smart Assist config entry if available."""
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _get_entry_data(hass: HomeAssistant, entry: Any) -> dict[str, Any]:
    """Return domain entry data container."""
    return hass.data.get(DOMAIN, {}).get(entry.entry_id, {})


def _get_request_history_store(hass: HomeAssistant, entry: Any) -> Any | None:
    """Return request history store from entry data."""
    return _get_entry_data(hass, entry).get("request_history")


def _find_default_conversation_subentry_id(entry: Any) -> str | None:
    """Return first conversation subentry id from config entry."""
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == "conversation":
            return subentry_id
    return None


def _build_dashboard_update_signal_names(entry: Any) -> list[str]:
    """Build dispatcher signal names used by dashboard subscriptions."""
    signal_names: list[str] = []
    for subentry_id in entry.subentries:
        for suffix in _DASHBOARD_METRIC_UPDATE_SIGNAL_SUFFIXES:
            signal_names.append(f"{DOMAIN}_{suffix}_{subentry_id}")
    signal_names.append(f"{MANAGED_ALARM_DISPATCHER_RECONCILED}_{entry.entry_id}")
    return signal_names


def _build_alarm_update_signal_name(entry: Any) -> str:
    """Build alarm update dispatcher signal name used by dashboard subscriptions."""
    return f"{DOMAIN}_alarms_updated_{entry.entry_id}"


def _get_alarm_manager(hass: HomeAssistant, entry: Any) -> PersistentAlarmManager | None:
    """Return persistent alarm manager from entry data."""
    manager = _get_entry_data(hass, entry).get("persistent_alarm_manager")
    if isinstance(manager, PersistentAlarmManager):
        return manager
    return None


def _resolve_satellites_for_alarm(hass: HomeAssistant, delivery: dict[str, Any]) -> list[str]:
    """Resolve deduplicated assist_satellite entities from delivery metadata."""
    resolved: list[str] = []
    seen: set[str] = set()

    def _add(entity_id: Any) -> None:
        value = str(entity_id or "").strip().lower()
        if not value or not value.startswith("assist_satellite."):
            return
        if value in seen:
            return
        seen.add(value)
        resolved.append(value)

    _add(delivery.get("source_satellite_id"))

    raw_targets = delivery.get("tts_targets")
    targets: list[str] = []
    if isinstance(raw_targets, list):
        targets = [str(item or "").strip().lower() for item in raw_targets]

    if not targets:
        return resolved

    try:
        registry = er.async_get(hass)
    except Exception:
        return resolved

    for media_player_entity_id in targets:
        if not media_player_entity_id.startswith("media_player."):
            continue
        try:
            player_entry = registry.async_get(media_player_entity_id)
            device_id = getattr(player_entry, "device_id", None)
            if not device_id:
                continue
            for entry in er.async_entries_for_device(registry, device_id):
                if getattr(entry, "domain", "") != "assist_satellite":
                    continue
                if getattr(entry, "disabled_by", None) is not None:
                    continue
                _add(getattr(entry, "entity_id", None))
        except Exception:
            continue

    return resolved


def _serialize_alarm(hass: HomeAssistant, alarm: dict[str, Any]) -> dict[str, Any]:
    """Return normalized alarm payload for websocket responses."""
    managed = alarm.get("managed_automation") if isinstance(alarm.get("managed_automation"), dict) else {}
    direct = alarm.get("direct_execution") if isinstance(alarm.get("direct_execution"), dict) else {}
    delivery = alarm.get("delivery") if isinstance(alarm.get("delivery"), dict) else {}
    wake_text = delivery.get("wake_text") if isinstance(delivery.get("wake_text"), dict) else {}
    resolved_satellites = _resolve_satellites_for_alarm(hass, delivery)
    status = str(alarm.get("status") or "")
    can_edit = bool(alarm.get("active")) or status in {"fired", "dismissed"}
    return {
        "id": alarm.get("id"),
        "display_id": alarm.get("display_id"),
        "label": alarm.get("label"),
        "message": alarm.get("message"),
        "source": alarm.get("source"),
        "status": alarm.get("status"),
        "active": alarm.get("active"),
        "dismissed": alarm.get("dismissed"),
        "fired": alarm.get("fired"),
        "scheduled_for": alarm.get("scheduled_for"),
        "next_scheduled_for": alarm.get("next_scheduled_for") or alarm.get("scheduled_for"),
        "recurrence": alarm.get("recurrence") if isinstance(alarm.get("recurrence"), dict) else None,
        "snoozed_until": alarm.get("snoozed_until"),
        "last_fired_at": alarm.get("last_fired_at"),
        "fire_count": alarm.get("fire_count"),
        "created_at": alarm.get("created_at"),
        "updated_at": alarm.get("updated_at"),
        "managed_enabled": managed.get("enabled", False),
        "managed_sync_state": managed.get("sync_state"),
        "managed_last_error": managed.get("last_sync_error"),
        "managed_automation_entity_id": managed.get("automation_entity_id"),
        "ownership_verified": managed.get("ownership_verified", False),
        "execution_mode": alarm.get("execution_mode") or DEFAULT_ALARM_EXECUTION_MODE,
        "direct_last_state": direct.get("last_state"),
        "direct_last_executed_at": direct.get("last_executed_at"),
        "direct_last_error": direct.get("last_error"),
        "direct_backend_results": direct.get("last_backend_results", {}),
        "tts_targets": delivery.get("tts_targets") if isinstance(delivery.get("tts_targets"), list) else [],
        "source_satellite_id": delivery.get("source_satellite_id"),
        "resolved_satellites": resolved_satellites,
        "wake_text_dynamic": bool(wake_text.get("dynamic", False)),
        "wake_text_include_weather": bool(wake_text.get("include_weather", False)),
        "wake_text_include_news": bool(wake_text.get("include_news", False)),
        "can_edit": can_edit,
    }


def _get_alarm_execution_mode_for_entry(hass: HomeAssistant, entry: Any) -> str:
    """Return normalized alarm execution mode for entry runtime data."""
    config = _get_entry_data(hass, entry).get("alarm_execution_config") or {}
    mode = str(config.get(CONF_ALARM_EXECUTION_MODE, DEFAULT_ALARM_EXECUTION_MODE) or "")
    if mode in {"managed_only", "direct_only", "hybrid"}:
        return mode
    return DEFAULT_ALARM_EXECUTION_MODE


def _build_alarms_summary(alarms: list[dict[str, Any]]) -> dict[str, int]:
    """Build lightweight alarm summary counts for dashboard snapshot."""
    summary = {
        "total": len(alarms),
        "active": 0,
        "snoozed": 0,
        "fired": 0,
        "dismissed": 0,
    }
    for alarm in alarms:
        status = str(alarm.get("status") or "")
        if alarm.get("active"):
            summary["active"] += 1
        if status == "snoozed":
            summary["snoozed"] += 1
        elif status == "fired":
            summary["fired"] += 1
        elif status == "dismissed":
            summary["dismissed"] += 1
    return summary


def _get_request_history_store_or_send_default(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    default_payload: dict[str, Any],
) -> Any | None:
    """Return request history store or send fallback payload and return None."""
    entry = _get_primary_entry(hass)
    if not entry:
        connection.send_result(msg["id"], default_payload)
        return None

    store = _get_request_history_store(hass, entry)
    if not store:
        connection.send_result(msg["id"], default_payload)
        return None

    return store


def _get_primary_entry_or_send_default(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    default_payload: dict[str, Any],
) -> Any | None:
    """Return primary entry or send fallback payload and return None."""
    entry = _get_primary_entry(hass)
    if not entry:
        connection.send_result(msg["id"], default_payload)
        return None
    return entry


def _resolve_prompt_subentry(entry: Any, agent_id: str | None) -> tuple[str, Any] | None:
    """Resolve conversation subentry for prompt preview."""
    target_subentry_id = agent_id or _find_default_conversation_subentry_id(entry)
    if not target_subentry_id:
        return None

    subentry = entry.subentries.get(target_subentry_id)
    if not subentry or subentry.subentry_type != "conversation":
        return None

    return target_subentry_id, subentry


def _get_prompt_entity(entry_data: dict[str, Any], subentry_id: str) -> Any | None:
    """Return conversation entity used for prompt preview."""
    agents = entry_data.get("agents", {})
    agent_info = agents.get(subentry_id, {})
    return agent_info.get("entity")


def _get_history_summary(entry_data: dict[str, Any], agent_id: str) -> dict[str, Any]:
    """Get request history summary for a specific agent."""
    request_history = entry_data.get("request_history")
    if not request_history:
        return {}
    return request_history.get_summary_stats(agent_id=agent_id)


def _build_agent_data(
    hass: HomeAssistant,
    entry_id: str,
    subentry_id: str,
    subentry: Any,
) -> dict[str, Any]:
    """Build dashboard data for a single conversation agent."""
    data = subentry.data
    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(entry_id, {})

    # Get LLM metrics
    agents = entry_data.get("agents", {})
    agent_info = agents.get(subentry_id, {})
    llm_client = agent_info.get("llm_client")

    metrics_dict = {}
    if llm_client and hasattr(llm_client, "metrics"):
        metrics_dict = llm_client.metrics.to_dict()

    # Get cache warming data
    cache_warming = entry_data.get("cache_warming", {}).get(subentry_id)

    # Get registered tools
    entity = agent_info.get("entity")
    tools_list: list[str] = []
    if entity and hasattr(entity, "get_registered_tool_names"):
        tools_list = entity.get_registered_tool_names()

    return {
        "name": subentry.title,
        "model": _get_subentry_config(data, CONF_MODEL, DEFAULT_MODEL),
        "provider": _get_subentry_config(data, CONF_PROVIDER, DEFAULT_PROVIDER),
        "llm_provider": _get_subentry_config(data, CONF_LLM_PROVIDER, DEFAULT_LLM_PROVIDER),
        "temperature": _get_subentry_config(data, CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
        "max_tokens": _get_subentry_config(data, CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
        "features": {
            "memory": _get_subentry_config(data, CONF_ENABLE_MEMORY, DEFAULT_ENABLE_MEMORY),
            "web_search": _get_subentry_config(data, CONF_ENABLE_WEB_SEARCH, True),
            "calendar_context": _get_subentry_config(data, CONF_CALENDAR_CONTEXT, DEFAULT_CALENDAR_CONTEXT),
            "prompt_caching": True,
            "cache_warming": _get_subentry_config(data, CONF_ENABLE_CACHE_WARMING, DEFAULT_ENABLE_CACHE_WARMING),
            "clean_responses": _get_subentry_config(data, CONF_CLEAN_RESPONSES, DEFAULT_CLEAN_RESPONSES),
            "ask_followup": _get_subentry_config(data, CONF_ASK_FOLLOWUP, DEFAULT_ASK_FOLLOWUP),
            "presence_heuristic": _get_subentry_config(data, CONF_ENABLE_PRESENCE_HEURISTIC, DEFAULT_ENABLE_PRESENCE_HEURISTIC),
        },
        "metrics": metrics_dict,
        "cache_warming": cache_warming,
        "tools": tools_list,
        "history_summary": _get_history_summary(entry_data, subentry_id),
    }


def _build_task_data(
    hass: HomeAssistant,
    entry_id: str,
    subentry_id: str,
    subentry: Any,
) -> dict[str, Any]:
    """Build dashboard data for a single AI task."""
    data = subentry.data
    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(entry_id, {})

    # Get LLM metrics
    tasks = entry_data.get("tasks", {})
    task_info = tasks.get(subentry_id, {})
    llm_client = task_info.get("llm_client")

    metrics_dict = {}
    if llm_client and hasattr(llm_client, "metrics"):
        metrics_dict = llm_client.metrics.to_dict()

    # Get registered tools
    entity = task_info.get("entity")
    tools_list: list[str] = []
    if entity and hasattr(entity, "get_registered_tool_names"):
        tools_list = entity.get_registered_tool_names()

    return {
        "name": subentry.title,
        "model": _get_subentry_config(data, CONF_MODEL, DEFAULT_MODEL),
        "llm_provider": _get_subentry_config(data, CONF_LLM_PROVIDER, DEFAULT_LLM_PROVIDER),
        "metrics": metrics_dict,
        "tools": tools_list,
    }


def _build_memory_summary(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """Build memory statistics summary."""
    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(entry_id, {})
    memory_manager = entry_data.get("memory_manager")

    if not isinstance(memory_manager, MemoryManager):
        return {
            "total_users": 0,
            "total_memories": 0,
            "global_memories": 0,
            "users": {},
        }
    return memory_manager.get_summary()


async def _build_calendar_data(
    hass: HomeAssistant,
    entry_id: str,
    entry: Any,
) -> dict[str, Any]:
    """Build calendar events data with reminder status for dashboard."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(entry_id, {})

    # Find a conversation agent with calendar context enabled
    calendar_enabled = False
    reminder_tracker: CalendarReminderTracker | None = None

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == "conversation":
            if subentry.data.get(CONF_CALENDAR_CONTEXT, DEFAULT_CALENDAR_CONTEXT):
                calendar_enabled = True
                agents = entry_data.get("agents", {})
                agent_info = agents.get(subentry_id, {})
                entity = agent_info.get("entity")
                if entity and hasattr(entity, "get_calendar_reminder_tracker"):
                    reminder_tracker = entity.get_calendar_reminder_tracker()
                break

    if not calendar_enabled:
        return {"enabled": False, "events": [], "calendars": 0}

    # Fetch events from all calendar entities
    now = dt_util.now()
    end = now + timedelta(hours=28)

    calendars = [
        state.entity_id
        for state in hass.states.async_all()
        if state.entity_id.startswith("calendar.")
    ]

    if not calendars:
        return {"enabled": True, "events": [], "calendars": 0}

    semaphore = asyncio.Semaphore(4)

    async def _fetch_calendar(cal_id: str) -> list[dict[str, Any]]:
        try:
            async with semaphore:
                async with asyncio.timeout(8):
                    result = await hass.services.async_call(
                        "calendar",
                        "get_events",
                        {
                            "entity_id": cal_id,
                            "start_date_time": now.isoformat(),
                            "end_date_time": end.isoformat(),
                        },
                        blocking=True,
                        return_response=True,
                    )

            if not result or cal_id not in result:
                return []

            state = hass.states.get(cal_id)
            if state and state.attributes.get("friendly_name"):
                owner = state.attributes["friendly_name"]
            else:
                name = cal_id.split(".", 1)[-1]
                owner = name.replace("_", " ").title()

            events: list[dict[str, Any]] = []
            for event in result[cal_id].get("events", []):
                event_data = {
                    "summary": event.get("summary", "Untitled"),
                    "start": event.get("start"),
                    "end": event.get("end"),
                    "owner": owner,
                    "calendar": cal_id,
                    "location": event.get("location"),
                }

                status = "upcoming"
                if reminder_tracker:
                    status = reminder_tracker.get_event_status(event_data, now)

                event_data["status"] = status
                events.append(event_data)

            return events
        except TimeoutError:
            _LOGGER.debug("Timeout while fetching calendar events from %s", cal_id)
        except Exception as err:
            _LOGGER.debug("Failed to fetch calendar events from %s: %s", cal_id, err)
        return []

    results = await asyncio.gather(
        *(_fetch_calendar(cal_id) for cal_id in calendars),
        return_exceptions=False,
    )

    all_events: list[dict[str, Any]] = []
    for events in results:
        all_events.extend(events)

    all_events.sort(key=lambda x: x.get("start", ""))

    return {
        "enabled": True,
        "calendars": len(calendars),
        "event_count": len(all_events),
        "events": all_events,
    }


async def _build_dashboard_snapshot(
    hass: HomeAssistant,
    entry: Any,
    include_calendar: bool,
) -> dict[str, Any]:
    """Build dashboard snapshot with optional heavy calendar section."""
    result: dict[str, Any] = {
        "agents": {},
        "tasks": {},
        "memory": {},
    }

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == "conversation":
            result["agents"][subentry_id] = _build_agent_data(
                hass, entry.entry_id, subentry_id, subentry
            )
        elif subentry.subentry_type == "ai_task":
            result["tasks"][subentry_id] = _build_task_data(
                hass, entry.entry_id, subentry_id, subentry
            )

    result["memory"] = _build_memory_summary(hass, entry.entry_id)

    manager = _get_alarm_manager(hass, entry)
    alarms = manager.list_alarms(active_only=False) if manager else []
    result["alarms_summary"] = _build_alarms_summary(alarms)

    if include_calendar:
        result["calendar"] = await _build_calendar_data(hass, entry.entry_id, entry)

    return result


async def _get_cached_calendar_data(
    hass: HomeAssistant,
    entry: Any,
    ttl_seconds: float = 30.0,
) -> dict[str, Any]:
    """Return calendar snapshot using short-lived in-memory cache."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    entry_data = domain_data.setdefault(entry.entry_id, {})
    dashboard_cache = entry_data.setdefault("dashboard_cache", {})

    now_monotonic = time.monotonic()
    cached = dashboard_cache.get("calendar")
    cached_at = dashboard_cache.get("calendar_cached_at", 0.0)

    if cached is not None and (now_monotonic - cached_at) < ttl_seconds:
        return cached

    calendar = await _build_calendar_data(hass, entry.entry_id, entry)
    dashboard_cache["calendar"] = calendar
    dashboard_cache["calendar_cached_at"] = now_monotonic
    return calendar


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/dashboard_data",
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_dashboard_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return all dashboard data for Smart Assist."""
    result = _build_empty_dashboard_result()

    entry = _get_primary_entry_or_send_default(hass, connection, msg, result)
    if not entry:
        return

    result = await _build_dashboard_snapshot(hass, entry, include_calendar=False)
    result["calendar"] = await _get_cached_calendar_data(hass, entry)

    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/memory_details",
        vol.Required("user_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_memory_details(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return detailed memory data for a specific user."""
    user_id = msg["user_id"]

    entry = _get_primary_entry_or_send_default(
        hass,
        connection,
        msg,
        _EMPTY_MEMORY_DETAILS_RESULT,
    )
    if not entry:
        return
    entry_data = _get_entry_data(hass, entry)
    memory_manager = entry_data.get("memory_manager")

    if not isinstance(memory_manager, MemoryManager):
        connection.send_result(msg["id"], _EMPTY_MEMORY_DETAILS_RESULT)
        return

    connection.send_result(msg["id"], memory_manager.get_user_details(user_id))


def _get_memory_manager(hass: HomeAssistant) -> Any | None:
    """Get the memory manager from domain data."""
    entry = _get_primary_entry(hass)
    if not entry:
        return None
    entry_data = _get_entry_data(hass, entry)
    mm = entry_data.get("memory_manager")
    if isinstance(mm, MemoryManager):
        return mm
    return None


def _get_memory_manager_or_send_error(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> MemoryManager | None:
    """Return memory manager or send standard not-found error."""
    memory_manager = _get_memory_manager(hass)
    if not memory_manager:
        connection.send_error(msg["id"], "not_found", "Memory manager not available")
        return None
    return memory_manager


async def _finalize_memory_mutation(
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    memory_manager: MemoryManager,
    result_message: str,
) -> None:
    """Persist memory mutation and send standard success payload."""
    await memory_manager.async_force_save()
    connection.send_result(msg["id"], {"message": result_message})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/memory_rename_user",
        vol.Required("user_id"): str,
        vol.Required("display_name"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_memory_rename_user(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Rename a memory user's display name."""
    memory_manager = _get_memory_manager_or_send_error(hass, connection, msg)
    if not memory_manager:
        return

    result = memory_manager.rename_user(msg["user_id"], msg["display_name"])
    await _finalize_memory_mutation(connection, msg, memory_manager, result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/memory_merge_users",
        vol.Required("source_user_id"): str,
        vol.Required("target_user_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_memory_merge_users(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Merge memories from one user into another."""
    memory_manager = _get_memory_manager_or_send_error(hass, connection, msg)
    if not memory_manager:
        return

    result = memory_manager.merge_users(msg["source_user_id"], msg["target_user_id"])
    await _finalize_memory_mutation(connection, msg, memory_manager, result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/memory_delete",
        vol.Required("user_id"): str,
        vol.Required("memory_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_memory_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a single memory entry."""
    memory_manager = _get_memory_manager_or_send_error(hass, connection, msg)
    if not memory_manager:
        return

    result = memory_manager.delete_memory(msg["user_id"], msg["memory_id"])
    await _finalize_memory_mutation(connection, msg, memory_manager, result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/subscribe",
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to Smart Assist metric updates.

    Forwards dispatcher signals to the WebSocket client for real-time updates.
    """
    entry = _get_primary_entry(hass)
    if not entry:
        connection.send_result(msg["id"])
        return

    send_in_progress = False
    send_pending_types: set[str] = set()

    async def _flush_updates() -> None:
        """Send coalesced lightweight dashboard updates."""
        nonlocal send_in_progress, send_pending_types
        send_in_progress = True
        try:
            while send_pending_types:
                if "metrics" in send_pending_types:
                    update_type = "metrics"
                    send_pending_types.remove("metrics")
                else:
                    update_type = send_pending_types.pop()

                if update_type == "alarms":
                    manager = _get_alarm_manager(hass, entry)
                    alarms = manager.list_alarms(active_only=False) if manager else []
                    result = {
                        "update_type": "alarms",
                        "alarms_summary": _build_alarms_summary(alarms),
                    }
                else:
                    result = await _build_dashboard_snapshot(
                        hass,
                        entry,
                        include_calendar=False,
                    )
                    result["update_type"] = "metrics"
                try:
                    connection.send_message(websocket_api.event_message(msg["id"], result))
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("WebSocket connection closed before message could be sent")
                    return
                await asyncio.sleep(0.5)
        finally:
            send_in_progress = False

    @callback
    def forward_update(update_type: str = "metrics", data: dict | None = None) -> None:
        """Forward coalesced metric updates to WebSocket client."""
        nonlocal send_pending_types
        send_pending_types.add(update_type)
        if not send_in_progress:
            hass.add_job(_flush_updates())

    unsub_callbacks: list[Any] = []
    for signal_name in _build_dashboard_update_signal_names(entry):
        unsub = async_dispatcher_connect(
            hass,
            signal_name,
            lambda data=None: forward_update("metrics", data),
        )
        unsub_callbacks.append(unsub)

    unsub_callbacks.append(
        async_dispatcher_connect(
            hass,
            _build_alarm_update_signal_name(entry),
            lambda data=None: forward_update("alarms", data),
        )
    )

    @callback
    def unsub_all() -> None:
        """Unsubscribe from all signals."""
        for unsub in unsub_callbacks:
            unsub()

    connection.subscriptions[msg["id"]] = unsub_all
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/calendar_data",
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_calendar_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return calendar data only for dashboard tab-scoped loading."""
    entry = _get_primary_entry_or_send_default(
        hass,
        connection,
        msg,
        _EMPTY_CALENDAR_RESULT,
    )
    if not entry:
        return

    calendar = await _get_cached_calendar_data(hass, entry)
    connection.send_result(msg["id"], calendar)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/alarms_data",
        vol.Optional("active_only", default=False): bool,
        vol.Optional("limit"): int,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_alarms_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return full alarm list and summary for alarms dashboard tab."""
    entry = _get_primary_entry_or_send_default(
        hass,
        connection,
        msg,
        {"alarms": [], "summary": _build_alarms_summary([])},
    )
    if not entry:
        return

    manager = _get_alarm_manager(hass, entry)
    if manager is None:
        connection.send_result(msg["id"], {"alarms": [], "summary": _build_alarms_summary([])})
        return

    alarms = manager.list_alarms(active_only=bool(msg.get("active_only", False)))
    execution_mode = _get_alarm_execution_mode_for_entry(hass, entry)
    managed_reconcile_available = execution_mode != ALARM_EXECUTION_MODE_DIRECT_ONLY
    for alarm in alarms:
        alarm["execution_mode"] = execution_mode
    summary = _build_alarms_summary(alarms)
    limit = msg.get("limit")
    if isinstance(limit, int) and limit > 0:
        alarms = alarms[:limit]

    connection.send_result(
        msg["id"],
        {
            "alarms": [_serialize_alarm(hass, alarm) for alarm in alarms],
            "summary": summary,
            "execution_mode": execution_mode,
            "managed_reconcile_available": managed_reconcile_available,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/alarm_action",
        vol.Required("action"): vol.In(["snooze", "cancel", "delete", "status", "managed_reconcile_now", "edit"]),
        vol.Optional("alarm_id"): str,
        vol.Optional("display_id"): str,
        vol.Optional("minutes"): int,
        vol.Optional("label"): str,
        vol.Optional("message"): str,
        vol.Optional("scheduled_for"): str,
        vol.Optional("recurrence"): vol.Any(dict, None),
        vol.Optional("tts_targets"): str,
        vol.Optional("wake_text_dynamic"): bool,
        vol.Optional("wake_text_include_weather"): bool,
        vol.Optional("wake_text_include_news"): bool,
        vol.Optional("reactivate", default=False): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_alarm_action(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Execute alarm management action for dashboard tab controls."""
    entry = _get_primary_entry(hass)
    if not entry:
        connection.send_error(msg["id"], "not_found", "Smart Assist entry not found")
        return

    manager = _get_alarm_manager(hass, entry)
    if manager is None:
        connection.send_error(msg["id"], "not_found", "Persistent alarm manager unavailable")
        return

    action = msg["action"]
    alarm_ref = msg.get("alarm_id") or msg.get("display_id")
    execution_mode = _get_alarm_execution_mode_for_entry(hass, entry)

    if action == "managed_reconcile_now":
        if execution_mode == ALARM_EXECUTION_MODE_DIRECT_ONLY:
            connection.send_result(msg["id"], {"success": False, "message": "Managed reconcile is disabled in direct-only mode"})
            return
        managed_service = _get_entry_data(hass, entry).get("managed_alarm_automation")
        if managed_service is None:
            connection.send_result(msg["id"], {"success": False, "message": "Managed alarm automation is disabled"})
            return
        try:
            alarm = manager.get_alarm(str(alarm_ref)) if alarm_ref else None
            if alarm is not None:
                await managed_service.async_reconcile_alarm(alarm, execution_mode=execution_mode)
            else:
                await managed_service.async_reconcile_all(execution_mode=execution_mode)
            await manager.async_save()
            from homeassistant.helpers.dispatcher import async_dispatcher_send
            async_dispatcher_send(hass, _build_alarm_update_signal_name(entry))
            connection.send_result(msg["id"], {"success": True, "message": "Managed alarms reconciled"})
            return
        except Exception as err:
            connection.send_error(msg["id"], "unknown_error", f"Managed reconcile failed: {err}")
            return

    if action == "status":
        if not alarm_ref:
            alarms = manager.list_alarms(active_only=False)
            connection.send_result(
                msg["id"],
                {
                    "success": True,
                    "message": f"Alarm count: {len(alarms)}",
                    "alarms": [_serialize_alarm(hass, {**alarm, "execution_mode": execution_mode}) for alarm in alarms],
                },
            )
            return

        alarm = manager.get_alarm(str(alarm_ref))
        if alarm is None:
            connection.send_error(msg["id"], "not_found", f"Alarm not found: {alarm_ref}")
            return
        connection.send_result(
            msg["id"],
            {
                "success": True,
                "message": "Alarm status resolved",
                "alarm": _serialize_alarm(hass, {**alarm, "execution_mode": execution_mode}),
            },
        )
        return

    if action == "cancel":
        if not alarm_ref:
            connection.send_error(msg["id"], "invalid_format", "alarm_id or display_id is required")
            return
        if not manager.cancel_alarm(str(alarm_ref)):
            connection.send_error(msg["id"], "not_found", f"Alarm not found or inactive: {alarm_ref}")
            return
        alarm = manager.get_alarm(str(alarm_ref))
        await manager.async_force_save()
        managed_service = _get_entry_data(hass, entry).get("managed_alarm_automation")
        if alarm is not None and managed_service is not None:
            try:
                await managed_service.async_reconcile_alarm(alarm, execution_mode=execution_mode)
                await manager.async_save()
            except Exception as err:
                _LOGGER.warning("Managed alarm reconcile failed on websocket cancel: %s", err)
        if alarm is not None:
            hass.bus.async_fire(
                PERSISTENT_ALARM_EVENT_UPDATED,
                {
                    "entry_id": entry.entry_id,
                    "alarm_id": alarm.get("id"),
                    "display_id": alarm.get("display_id"),
                    "status": alarm.get("status"),
                    "active": alarm.get("active"),
                    "scheduled_for": alarm.get("scheduled_for"),
                    "snoozed_until": alarm.get("snoozed_until"),
                    "updated_at": alarm.get("updated_at"),
                    "reason": "cancel",
                },
            )
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        async_dispatcher_send(hass, _build_alarm_update_signal_name(entry))
        connection.send_result(
            msg["id"],
            {
                "success": True,
                "message": "Alarm cancelled",
                "alarm": _serialize_alarm(hass, {**alarm, "execution_mode": execution_mode}) if alarm else None,
            },
        )
        return

    if action == "delete":
        if not alarm_ref:
            connection.send_error(msg["id"], "invalid_format", "alarm_id or display_id is required")
            return

        alarm_before_delete = manager.get_alarm(str(alarm_ref))
        if not manager.delete_alarm(str(alarm_ref)):
            connection.send_error(msg["id"], "not_found", f"Alarm not found: {alarm_ref}")
            return

        await manager.async_force_save()
        hass.bus.async_fire(
            PERSISTENT_ALARM_EVENT_UPDATED,
            {
                "entry_id": entry.entry_id,
                "alarm_id": alarm_before_delete.get("id") if alarm_before_delete else str(alarm_ref),
                "display_id": alarm_before_delete.get("display_id") if alarm_before_delete else None,
                "status": "deleted",
                "active": False,
                "scheduled_for": None,
                "snoozed_until": None,
                "updated_at": alarm_before_delete.get("updated_at") if alarm_before_delete else None,
                "reason": "delete",
            },
        )

        from homeassistant.helpers.dispatcher import async_dispatcher_send

        async_dispatcher_send(hass, _build_alarm_update_signal_name(entry))
        connection.send_result(
            msg["id"],
            {
                "success": True,
                "message": "Alarm deleted",
                "deleted_alarm_id": alarm_before_delete.get("id") if alarm_before_delete else str(alarm_ref),
            },
        )
        return

    if action == "edit":
        if not alarm_ref:
            connection.send_error(msg["id"], "invalid_format", "alarm_id or display_id is required")
            return

        updates: dict[str, Any] = {}
        if "label" in msg:
            updates["label"] = msg.get("label")
        if "message" in msg:
            updates["message"] = msg.get("message")
        if "scheduled_for" in msg:
            updates["scheduled_for"] = msg.get("scheduled_for")
        if "recurrence" in msg:
            updates["recurrence"] = msg.get("recurrence")
        delivery_updates: dict[str, Any] = {}
        if "tts_targets" in msg:
            raw_targets = str(msg.get("tts_targets") or "")
            parsed_targets = [
                token.strip().lower()
                for token in raw_targets.split(",")
                if token.strip().lower().startswith("media_player.")
            ]
            delivery_updates["tts_targets"] = parsed_targets
        wake_text_updates: dict[str, Any] = {}
        if "wake_text_dynamic" in msg:
            wake_text_updates["dynamic"] = bool(msg.get("wake_text_dynamic"))
        if "wake_text_include_weather" in msg:
            wake_text_updates["include_weather"] = bool(msg.get("wake_text_include_weather"))
        if "wake_text_include_news" in msg:
            wake_text_updates["include_news"] = bool(msg.get("wake_text_include_news"))
        if wake_text_updates:
            delivery_updates["wake_text"] = wake_text_updates
        if delivery_updates:
            updates["delivery"] = delivery_updates

        alarm, status = manager.update_alarm(
            str(alarm_ref),
            updates,
            reactivate=bool(msg.get("reactivate", False)),
        )
        if alarm is None:
            connection.send_error(msg["id"], "invalid_format", status)
            return

        await manager.async_force_save()
        managed_service = _get_entry_data(hass, entry).get("managed_alarm_automation")
        if managed_service is not None:
            try:
                await managed_service.async_reconcile_alarm(alarm, execution_mode=execution_mode)
                await manager.async_save()
            except Exception as err:
                _LOGGER.warning("Managed alarm reconcile failed on websocket edit: %s", err)

        hass.bus.async_fire(
            PERSISTENT_ALARM_EVENT_UPDATED,
            {
                "entry_id": entry.entry_id,
                "alarm_id": alarm.get("id"),
                "display_id": alarm.get("display_id"),
                "status": alarm.get("status"),
                "active": alarm.get("active"),
                "scheduled_for": alarm.get("scheduled_for"),
                "snoozed_until": alarm.get("snoozed_until"),
                "updated_at": alarm.get("updated_at"),
                "reason": "edit",
            },
        )
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        async_dispatcher_send(hass, _build_alarm_update_signal_name(entry))
        connection.send_result(
            msg["id"],
            {
                "success": True,
                "message": "Alarm updated",
                "alarm": _serialize_alarm(hass, {**alarm, "execution_mode": execution_mode}),
            },
        )
        return

    minutes = int(msg.get("minutes") or 0)
    if minutes <= 0:
        connection.send_error(msg["id"], "invalid_format", "minutes must be > 0 for snooze")
        return

    if not alarm_ref:
        recent = manager.get_recent_fired_alarms(
            window_minutes=POST_FIRE_SNOOZE_CONTEXT_WINDOW_MINUTES,
            limit=3,
        )
        if len(recent) == 1:
            alarm_ref = str(recent[0].get("id"))
        elif len(recent) > 1:
            connection.send_error(msg["id"], "invalid_format", "Multiple recently fired alarms found; specify alarm_id or display_id")
            return
        else:
            connection.send_error(msg["id"], "invalid_format", "No recent fired alarm found; specify alarm_id or display_id")
            return

    alarm, status = manager.snooze_alarm(str(alarm_ref), minutes)
    if alarm is None:
        connection.send_error(msg["id"], "not_found", status)
        return

    await manager.async_force_save()
    managed_service = _get_entry_data(hass, entry).get("managed_alarm_automation")
    if managed_service is not None:
        try:
            await managed_service.async_reconcile_alarm(alarm, execution_mode=execution_mode)
            await manager.async_save()
        except Exception as err:
            _LOGGER.warning("Managed alarm reconcile failed on websocket snooze: %s", err)
    hass.bus.async_fire(
        PERSISTENT_ALARM_EVENT_UPDATED,
        {
            "entry_id": entry.entry_id,
            "alarm_id": alarm.get("id"),
            "display_id": alarm.get("display_id"),
            "status": alarm.get("status"),
            "active": alarm.get("active"),
            "scheduled_for": alarm.get("scheduled_for"),
            "snoozed_until": alarm.get("snoozed_until"),
            "updated_at": alarm.get("updated_at"),
            "reason": "snooze",
        },
    )
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    async_dispatcher_send(hass, _build_alarm_update_signal_name(entry))
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "message": "Alarm snoozed",
            "alarm": _serialize_alarm(hass, {**alarm, "execution_mode": execution_mode}),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/request_history",
        vol.Optional("agent_id"): str,
        vol.Optional("limit", default=50): int,
        vol.Optional("offset", default=0): int,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_request_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return request history entries."""
    store = _get_request_history_store_or_send_default(
        hass,
        connection,
        msg,
        _EMPTY_HISTORY_RESULT,
    )
    if not store:
        return

    agent_id = msg.get("agent_id")
    limit = msg.get("limit", 50)
    offset = msg.get("offset", 0)

    history_entries, total = store.get_entries(
        limit=limit, offset=offset, agent_id=agent_id
    )
    connection.send_result(msg["id"], {
        "entries": history_entries,
        "total": total,
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/tool_analytics",
        vol.Optional("agent_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_tool_analytics(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return tool usage analytics."""
    store = _get_request_history_store_or_send_default(
        hass,
        connection,
        msg,
        _EMPTY_TOOL_ANALYTICS_RESULT,
    )
    if not store:
        return

    agent_id = msg.get("agent_id")
    tools = store.get_tool_analytics(agent_id=agent_id)
    summary = store.get_summary_stats(agent_id=agent_id)

    connection.send_result(msg["id"], {
        "tools": tools,
        "summary": summary,
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/system_prompt",
        vol.Optional("agent_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_system_prompt(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the system prompt for a specific agent."""
    entry = _get_primary_entry(hass)
    if not entry:
        connection.send_result(msg["id"], _EMPTY_PROMPT_RESULT)
        return

    agent_id = msg.get("agent_id")
    resolved = _resolve_prompt_subentry(entry, agent_id)
    if not resolved:
        connection.send_result(msg["id"], _EMPTY_PROMPT_RESULT)
        return
    target_subentry_id, subentry = resolved

    # Get the entity to build/retrieve system prompt
    entry_data = _get_entry_data(hass, entry)
    entity = _get_prompt_entity(entry_data, target_subentry_id)

    system_prompt = ""
    user_prompt = ""

    if entity:
        # Import and call build_system_prompt (will use cache if available)
        from .prompt_builder import build_system_prompt
        try:
            system_prompt = await build_system_prompt(entity)
        except Exception as err:
            _LOGGER.warning("Failed to build system prompt for preview: %s", err)
            system_prompt = f"[Error building prompt: {err}]"

        # Get user system prompt from config
        user_prompt = entity._get_config(
            CONF_USER_SYSTEM_PROMPT, DEFAULT_USER_SYSTEM_PROMPT
        )

    connection.send_result(msg["id"], {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt or "",
        "agent_name": subentry.title,
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_assist/request_history_clear",
        vol.Optional("agent_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_request_history_clear(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Clear request history."""
    store = _get_request_history_store_or_send_default(
        hass,
        connection,
        msg,
        _EMPTY_REMOVED_RESULT,
    )
    if not store:
        return

    agent_id = msg.get("agent_id")
    removed = store.clear(agent_id=agent_id)
    await store.async_force_save()
    connection.send_result(msg["id"], {"removed": removed})
