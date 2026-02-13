"""WebSocket API for Smart Assist Dashboard.

Provides real-time data access for the Smart Assist custom panel.
Uses HA's native WebSocket API for secure, authenticated communication.
"""

from __future__ import annotations

import asyncio
import logging
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
    _LOGGER.debug("Registered Smart Assist WebSocket commands")


def _get_subentry_config(data: dict[str, Any], key: str, default: Any = None) -> Any:
    """Get config value from subentry data with default."""
    return data.get(key, default)


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

    return {
        "name": subentry.title,
        "model": _get_subentry_config(data, CONF_MODEL, DEFAULT_MODEL),
        "llm_provider": _get_subentry_config(data, CONF_LLM_PROVIDER, DEFAULT_LLM_PROVIDER),
        "metrics": metrics_dict,
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
    result: dict[str, Any] = {
        "agents": {},
        "tasks": {},
        "memory": {},
        "calendar": {},
    }

    # Find the Smart Assist config entry
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_result(msg["id"], result)
        return

    entry = entries[0]  # Single instance integration

    # Build agent and task data from subentries
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == "conversation":
            result["agents"][subentry_id] = _build_agent_data(
                hass, entry.entry_id, subentry_id, subentry
            )
        elif subentry.subentry_type == "ai_task":
            result["tasks"][subentry_id] = _build_task_data(
                hass, entry.entry_id, subentry_id, subentry
            )

    # Build memory summary
    result["memory"] = _build_memory_summary(hass, entry.entry_id)

    # Build calendar data (async - fetches from HA calendar service)
    result["calendar"] = await _build_calendar_data(hass, entry.entry_id, entry)

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

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_result(msg["id"], {"memories": [], "stats": {}})
        return

    entry = entries[0]
    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(entry.entry_id, {})
    memory_manager = entry_data.get("memory_manager")

    if not isinstance(memory_manager, MemoryManager):
        connection.send_result(msg["id"], {"memories": [], "stats": {}})
        return

    connection.send_result(msg["id"], memory_manager.get_user_details(user_id))


def _get_memory_manager(hass: HomeAssistant) -> Any | None:
    """Get the memory manager from domain data."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None
    entry_data = hass.data.get(DOMAIN, {}).get(entries[0].entry_id, {})
    mm = entry_data.get("memory_manager")
    if isinstance(mm, MemoryManager):
        return mm
    return None


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
    mm = _get_memory_manager(hass)
    if not mm:
        connection.send_error(msg["id"], "not_found", "Memory manager not available")
        return

    result = mm.rename_user(msg["user_id"], msg["display_name"])
    await mm.async_force_save()
    connection.send_result(msg["id"], {"message": result})


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
    mm = _get_memory_manager(hass)
    if not mm:
        connection.send_error(msg["id"], "not_found", "Memory manager not available")
        return

    result = mm.merge_users(msg["source_user_id"], msg["target_user_id"])
    await mm.async_force_save()
    connection.send_result(msg["id"], {"message": result})


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
    mm = _get_memory_manager(hass)
    if not mm:
        connection.send_error(msg["id"], "not_found", "Memory manager not available")
        return

    result = mm.delete_memory(msg["user_id"], msg["memory_id"])
    await mm.async_force_save()
    connection.send_result(msg["id"], {"message": result})


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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_result(msg["id"])
        return

    entry = entries[0]

    @callback
    def forward_update(data: dict | None = None) -> None:
        """Forward metric updates to WebSocket client."""
        # Rebuild full dashboard data on each update
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

        # Schedule calendar data build (async) and send complete result
        async def _send_with_calendar() -> None:
            try:
                result["calendar"] = await _build_calendar_data(
                    hass, entry.entry_id, entry
                )
            except Exception:  # noqa: BLE001
                result["calendar"] = {"enabled": False, "events": [], "calendars": 0}
            try:
                connection.send_message(websocket_api.event_message(msg["id"], result))
            except Exception:  # noqa: BLE001
                _LOGGER.debug("WebSocket connection closed before message could be sent")

        hass.async_create_task(_send_with_calendar())

    # Subscribe to metric update signals for all subentries
    unsub_callbacks: list[Any] = []
    for subentry_id in entry.subentries:
        unsub = async_dispatcher_connect(
            hass,
            f"{DOMAIN}_metrics_updated_{subentry_id}",
            forward_update,
        )
        unsub_callbacks.append(unsub)

        # Also subscribe to cache warming updates
        unsub_warming = async_dispatcher_connect(
            hass,
            f"{DOMAIN}_cache_warming_updated_{subentry_id}",
            forward_update,
        )
        unsub_callbacks.append(unsub_warming)

    @callback
    def unsub_all() -> None:
        """Unsubscribe from all signals."""
        for unsub in unsub_callbacks:
            unsub()

    connection.subscriptions[msg["id"]] = unsub_all
    connection.send_result(msg["id"])


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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_result(msg["id"], {"entries": [], "total": 0})
        return

    entry = entries[0]
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("request_history")
    if not store:
        connection.send_result(msg["id"], {"entries": [], "total": 0})
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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_result(msg["id"], {"tools": [], "summary": {}})
        return

    entry = entries[0]
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("request_history")
    if not store:
        connection.send_result(msg["id"], {"tools": [], "summary": {}})
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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_result(msg["id"], {
            "system_prompt": "",
            "user_prompt": "",
            "agent_name": "",
        })
        return

    entry = entries[0]
    agent_id = msg.get("agent_id")

    # Find the target agent (default to first conversation subentry)
    target_subentry_id = agent_id
    if not target_subentry_id:
        for sid, sub in entry.subentries.items():
            if sub.subentry_type == "conversation":
                target_subentry_id = sid
                break

    if not target_subentry_id:
        connection.send_result(msg["id"], {
            "system_prompt": "",
            "user_prompt": "",
            "agent_name": "",
        })
        return

    subentry = entry.subentries.get(target_subentry_id)
    if not subentry or subentry.subentry_type != "conversation":
        connection.send_result(msg["id"], {
            "system_prompt": "",
            "user_prompt": "",
            "agent_name": "",
        })
        return

    # Get the entity to build/retrieve system prompt
    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(entry.entry_id, {})
    agents = entry_data.get("agents", {})
    agent_info = agents.get(target_subentry_id, {})
    entity = agent_info.get("entity")

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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_result(msg["id"], {"removed": 0})
        return

    entry = entries[0]
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("request_history")
    if not store:
        connection.send_result(msg["id"], {"removed": 0})
        return

    agent_id = msg.get("agent_id")
    removed = store.clear(agent_id=agent_id)
    await store.async_force_save()
    connection.send_result(msg["id"], {"removed": removed})
