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
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import voluptuous as vol

from .const import (
    CONF_ASK_FOLLOWUP,
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
)
from .context.calendar_reminder import CalendarReminderTracker
from .context.memory import MemoryManager

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
_DASHBOARD_UPDATE_SIGNAL_SUFFIXES = ("metrics_updated", "cache_warming_updated")


def _build_empty_dashboard_result() -> dict[str, Any]:
    """Return empty dashboard payload shape."""
    return {
        "agents": {},
        "tasks": {},
        "memory": {},
        "calendar": {},
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
        for suffix in _DASHBOARD_UPDATE_SIGNAL_SUFFIXES:
            signal_names.append(f"{DOMAIN}_{suffix}_{subentry_id}")
    return signal_names


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
    send_pending = False

    async def _flush_updates() -> None:
        """Send coalesced lightweight dashboard updates."""
        nonlocal send_in_progress, send_pending
        send_in_progress = True
        try:
            while send_pending:
                send_pending = False
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
    def forward_update(data: dict | None = None) -> None:
        """Forward coalesced metric updates to WebSocket client."""
        nonlocal send_pending
        send_pending = True
        if not send_in_progress:
            hass.async_create_task(_flush_updates())

    unsub_callbacks: list[Any] = []
    for signal_name in _build_dashboard_update_signal_names(entry):
        unsub = async_dispatcher_connect(
            hass,
            signal_name,
            forward_update,
        )
        unsub_callbacks.append(unsub)

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
