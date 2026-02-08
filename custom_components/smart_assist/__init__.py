"""Smart Assist - LLM-powered Home Assistant conversation integration.

This integration uses Home Assistant's Subentry system to allow
multiple Conversation Agents and AI Tasks with individual settings.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

# Set up logging FIRST
_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.config_entries import ConfigEntry, ConfigSubentry
    from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STARTED
    from homeassistant.core import HomeAssistant, Event
    from homeassistant.helpers import config_validation as cv
    from homeassistant.helpers.event import async_track_time_interval
except ImportError as e:
    _LOGGER.error("Smart Assist __init__.py: Failed to import HA core: %s", e)
    raise

try:
    from .const import (
        CONF_CACHE_REFRESH_INTERVAL,
        CONF_CANCEL_INTENT_AGENT,
        CONF_DEBUG_LOGGING,
        CONF_ENABLE_CACHE_WARMING,
        CONF_ENABLE_CANCEL_HANDLER,
        DEFAULT_CACHE_REFRESH_INTERVAL,
        DEFAULT_CANCEL_INTENT_AGENT,
        DEFAULT_DEBUG_LOGGING,
        DEFAULT_ENABLE_CACHE_WARMING,
        DEFAULT_ENABLE_CANCEL_HANDLER,
        DOMAIN,
    )
    from .utils import apply_debug_logging
except ImportError as e:
    _LOGGER.error("Smart Assist __init__.py: Failed to import const: %s", e)
    raise

_LOGGER.debug("Smart Assist: __init__.py module loaded successfully")

# Schema indicating this integration is only configurable via config entries
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Platforms are set up from subentries (conversation and ai_task)
PLATFORMS: list[Platform] = [Platform.AI_TASK, Platform.CONVERSATION, Platform.SENSOR]


class SmartAssistNevermindHandler:
    """Custom handler for HassNevermind that uses LLM for natural TTS response.

    Workaround for HA Core bug where the built-in NevermindIntentHandler
    returns empty speech, causing voice satellites to hang.

    Uses the first available Smart Assist LLM client to generate a brief,
    natural-sounding cancel confirmation in the correct language.
    Falls back to "OK" if no LLM client is available.
    """

    intent_type = "HassNevermind"
    description = "Cancels the current request with a spoken confirmation"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize with hass reference to access LLM clients."""
        self._hass = hass

    def _get_llm_client(self):
        """Get the LLM client for cancel intent handling.

        Prefers the agent explicitly marked as cancel intent handler.
        Falls back to the first available LLM client.
        """
        domain_data = self._hass.data.get(DOMAIN, {})
        fallback_client = None

        for entry_id, entry_data in domain_data.items():
            if not isinstance(entry_data, dict):
                continue

            # Get config entry to check subentry settings
            entry = self._hass.config_entries.async_get_entry(entry_id)
            agents = entry_data.get("agents", {})

            for subentry_id, agent_info in agents.items():
                llm_client = agent_info.get("llm_client")
                if llm_client is None:
                    continue

                # Check if this subentry is marked as the cancel intent agent
                if entry is not None:
                    subentry = entry.subentries.get(subentry_id)
                    if subentry is not None and subentry.data.get(
                        CONF_CANCEL_INTENT_AGENT, DEFAULT_CANCEL_INTENT_AGENT
                    ):
                        return llm_client

                # Keep first available as fallback
                if fallback_client is None:
                    fallback_client = llm_client

        return fallback_client

    async def async_handle(self, intent_obj) -> Any:
        """Generate a natural cancel confirmation via LLM."""
        response = intent_obj.create_response()

        llm_client = self._get_llm_client()
        if llm_client is not None:
            try:
                from .llm import ChatMessage
                from .llm.models import MessageRole

                lang = intent_obj.language or "en"

                messages = [
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=(
                            f"You are a voice assistant. The user just said "
                            f"'cancel' or 'never mind'. Respond with a very "
                            f"brief acknowledgment (max 5 words) in the "
                            f"language with code '{lang}'. Use plain text "
                            f"only, no emojis, no punctuation except period. "
                            f"Vary your responses naturally."
                        ),
                    ),
                    ChatMessage(
                        role=MessageRole.USER,
                        content="Cancel",
                    ),
                ]

                llm_response = await llm_client.chat(
                    messages=messages, tools=[]
                )

                if llm_response.content and llm_response.content.strip():
                    speech = llm_response.content.strip()
                    # Safety: cap at 50 chars to prevent runaway responses
                    if len(speech) > 50:
                        speech = speech[:50]
                    response.async_set_speech(speech)
                    _LOGGER.debug(
                        "HassNevermind: LLM response: %s", speech
                    )
                    return response
            except Exception as err:
                _LOGGER.debug(
                    "HassNevermind: LLM call failed, using fallback: %s", err
                )

        # Fallback: simple "OK" if no LLM available or call failed
        response.async_set_speech("OK")
        return response


def _register_cancel_handler(hass: HomeAssistant) -> None:
    """Register the custom HassNevermind intent handler."""
    from homeassistant.helpers import intent as ha_intent
    ha_intent.async_register(hass, SmartAssistNevermindHandler(hass))
    _LOGGER.debug("Registered custom HassNevermind intent handler")


def _unregister_cancel_handler(hass: HomeAssistant) -> None:
    """Restore the original HassNevermind intent handler."""
    try:
        from homeassistant.components.intent import NevermindIntentHandler
        from homeassistant.helpers import intent as ha_intent
        ha_intent.async_register(hass, NevermindIntentHandler())
        _LOGGER.debug("Restored original HassNevermind intent handler")
    except ImportError:
        pass


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Smart Assist component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Smart Assist from a config entry.
    
    The main config entry contains the API key.
    Subentries (conversation, ai_task) contain the individual settings.
    """
    _LOGGER.info("Setting up Smart Assist integration")

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "agents": {},  # Store conversation agents by subentry_id
        "tasks": {},   # Store AI tasks by subentry_id
    }

    # Initialize persistent memory manager
    from .context.memory import MemoryManager
    memory_manager = MemoryManager(hass)
    await memory_manager.async_load()
    hass.data[DOMAIN][entry.entry_id]["memory_manager"] = memory_manager

    # Initialize request history store
    from .context.request_history import RequestHistoryStore
    request_history = RequestHistoryStore(hass)
    await request_history.async_load()
    hass.data[DOMAIN][entry.entry_id]["request_history"] = request_history

    # Helper to get config values (options override data)
    def get_config(key: str, default: Any = None) -> Any:
        """Get config value from options first, then data, then default."""
        if key in entry.options:
            return entry.options[key]
        return entry.data.get(key, default)

    # Apply debug logging setting
    debug_enabled = get_config(CONF_DEBUG_LOGGING, DEFAULT_DEBUG_LOGGING)
    apply_debug_logging(debug_enabled)

    # Register WebSocket API commands for dashboard
    from .websocket import async_register_websocket_commands
    async_register_websocket_commands(hass)

    # Register frontend panel in sidebar
    from .frontend import async_register_frontend
    await async_register_frontend(hass)

    # Register custom HassNevermind handler if enabled (fixes satellite hang)
    cancel_enabled = get_config(CONF_ENABLE_CANCEL_HANDLER, DEFAULT_ENABLE_CANCEL_HANDLER)
    if cancel_enabled:
        _register_cancel_handler(hass)

    # Set up platforms (they will read from subentries)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Cache warming for conversation agents (if any subentries have it enabled)
    # This is handled per-subentry now, so we iterate through conversation subentries
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != "conversation":
            continue
        
        warming_enabled = subentry.data.get(CONF_ENABLE_CACHE_WARMING, DEFAULT_ENABLE_CACHE_WARMING)
        
        if warming_enabled:
            if hass.is_running:
                _LOGGER.info("HA running, starting cache warming for %s...", subentry.title)
                hass.async_create_task(_initial_cache_warming(hass, entry, subentry_id, subentry))
            else:
                # Create callback using closure to properly capture subentry context
                # Avoids mutable default argument anti-pattern
                def _create_cache_warming_callback(
                    se_id: str,
                    se: ConfigSubentry,
                ) -> tuple[Any, Any]:
                    """Create cache warming callback with proper closure."""
                    listener_called = False
                    
                    async def callback(event: Event) -> None:
                        nonlocal listener_called
                        listener_called = True
                        _LOGGER.info("Starting initial cache warming for %s...", se.title)
                        await _initial_cache_warming(hass, entry, se_id, se)
                    
                    def safe_unsub(unsub_func: callable) -> callable:
                        def _unsub() -> None:
                            nonlocal listener_called
                            if not listener_called:
                                unsub_func()
                        return _unsub
                    
                    return callback, safe_unsub
                
                callback, safe_unsub_factory = _create_cache_warming_callback(
                    subentry_id, subentry
                )
                unsub = hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, callback
                )
                entry.async_on_unload(safe_unsub_factory(unsub))

    _LOGGER.info("Smart Assist integration setup complete")
    return True


async def _initial_cache_warming(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry_id: str,
    subentry: ConfigSubentry,
) -> None:
    """Perform initial cache warming and start the refresh timer.
    
    This handles the first warmup and initializes tracking data.
    Performs TWO warmups at startup to ensure cache is fully populated.
    """
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    
    # Initialize tracking data early
    hass.data[DOMAIN][entry.entry_id].setdefault("cache_warming", {})
    hass.data[DOMAIN][entry.entry_id]["cache_warming"][subentry_id] = {
        "status": "warming",
        "last_warmup": None,
        "next_warmup": None,
        "warmup_count": 0,
        "warmup_failures": 0,
        "interval_minutes": subentry.data.get(
            CONF_CACHE_REFRESH_INTERVAL, DEFAULT_CACHE_REFRESH_INTERVAL
        ),
    }
    
    warming_data = hass.data[DOMAIN][entry.entry_id]["cache_warming"][subentry_id]
    
    # Perform TWO warmups at startup to ensure cache is fully populated
    # First warmup creates the cache, second warmup uses it (verifies it works)
    for i in range(2):
        _LOGGER.debug("Cache warming pass %d/2 for %s", i + 1, subentry.title)
        success = await _perform_cache_warming(hass, entry, subentry_id, initial=True)
        
        # Update tracking
        warming_data["last_warmup"] = datetime.now().isoformat()
        if success:
            warming_data["warmup_count"] += 1
        else:
            warming_data["warmup_failures"] += 1
    
    warming_data["status"] = "active"
    
    # Signal sensor update
    async_dispatcher_send(hass, f"{DOMAIN}_cache_warming_updated_{subentry_id}")
    
    # Start the periodic refresh timer
    _start_cache_refresh_timer(hass, entry, subentry)


def _start_cache_refresh_timer(
    hass: HomeAssistant, entry: ConfigEntry, subentry: ConfigSubentry
) -> None:
    """Start periodic cache refresh timer for a specific conversation agent."""
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    
    # Get user-configured refresh interval (in minutes) from subentry
    interval_minutes = subentry.data.get(
        CONF_CACHE_REFRESH_INTERVAL, DEFAULT_CACHE_REFRESH_INTERVAL
    )
    interval_seconds = interval_minutes * 60
    subentry_id = subentry.subentry_id
    
    # Initialize cache warming tracking data
    hass.data[DOMAIN][entry.entry_id].setdefault("cache_warming", {})
    hass.data[DOMAIN][entry.entry_id]["cache_warming"][subentry_id] = {
        "status": "active",
        "last_warmup": None,
        "next_warmup": None,
        "warmup_count": 0,
        "warmup_failures": 0,
        "interval_minutes": interval_minutes,
    }
    
    def _update_next_warmup() -> None:
        """Update the next warmup timestamp."""
        next_time = datetime.now() + timedelta(minutes=interval_minutes)
        hass.data[DOMAIN][entry.entry_id]["cache_warming"][subentry_id]["next_warmup"] = next_time.isoformat()
    
    async def _refresh_cache(now: Any) -> None:
        """Periodically refresh the cache."""
        _LOGGER.info(
            "Refreshing prompt cache for %s (every %d min)",
            subentry.title, interval_minutes
        )
        
        # Update status to warming
        hass.data[DOMAIN][entry.entry_id]["cache_warming"][subentry_id]["status"] = "warming"
        async_dispatcher_send(hass, f"{DOMAIN}_cache_warming_updated_{subentry_id}")
        
        success = await _perform_cache_warming(hass, entry, subentry_id, initial=False)
        
        # Update tracking data
        warming_data = hass.data[DOMAIN][entry.entry_id]["cache_warming"][subentry_id]
        warming_data["last_warmup"] = datetime.now().isoformat()
        warming_data["status"] = "active"
        if success:
            warming_data["warmup_count"] += 1
        else:
            warming_data["warmup_failures"] += 1
        _update_next_warmup()
        
        # Signal sensor update
        async_dispatcher_send(hass, f"{DOMAIN}_cache_warming_updated_{subentry_id}")
    
    # Register the periodic task
    cancel_refresh = async_track_time_interval(
        hass,
        _refresh_cache,
        timedelta(seconds=interval_seconds),
    )
    
    # Store cancellation function for this subentry
    hass.data[DOMAIN][entry.entry_id].setdefault("cache_timers", {})
    hass.data[DOMAIN][entry.entry_id]["cache_timers"][subentry_id] = cancel_refresh
    entry.async_on_unload(cancel_refresh)
    
    # Set initial next warmup time
    _update_next_warmup()
    
    _LOGGER.info(
        "Cache refresh timer started for %s (interval: %d minutes)",
        subentry.title, interval_minutes,
    )


async def _perform_cache_warming(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry_id: str,
    initial: bool = True,
) -> bool:
    """Perform cache warming for a specific conversation agent.
    
    This pre-populates the prompt cache with the system prompt and entity index,
    reducing latency and cost for subsequent requests.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        subentry_id: ID of the subentry (conversation agent) to warm
        initial: If True, wait for entities to load (first run only)
        
    Returns:
        True if warming was successful, False otherwise
    """
    _LOGGER.debug("Starting cache warming for subentry %s", subentry_id)
    
    # Wait a bit for entities to be fully loaded (only on initial warmup)
    if initial:
        await asyncio.sleep(5)
    
    try:
        # Get the conversation entity for this subentry
        from .conversation import SmartAssistConversationEntity
        
        agent_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        agents = agent_data.get("agents", {})
        agent_info = agents.get(subentry_id, {})
        entity: SmartAssistConversationEntity | None = agent_info.get("entity")
        
        if entity is None:
            _LOGGER.debug("No entity found for cache warming (subentry %s), skipping", subentry_id)
            return False
        
        # Perform a minimal warming request
        # This builds the system prompt and entity index, populating the cache
        await entity.warm_cache()
        
        _LOGGER.info("Cache warming completed successfully for subentry %s", subentry_id)
        return True
        
    except Exception as err:
        _LOGGER.warning("Cache warming failed for subentry %s: %s", subentry_id, err)
        return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Smart Assist integration")

    # Restore original HassNevermind handler
    _unregister_cancel_handler(hass)

    # Close LLM client sessions for all agents
    try:
        agent_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        agents = agent_data.get("agents", {})
        for subentry_id, agent_info in agents.items():
            entity = agent_info.get("entity")
            if entity and hasattr(entity, "_llm_client") and entity._llm_client:
                await entity._llm_client.close()
                _LOGGER.debug("Closed LLM client session for %s", subentry_id)
    except Exception as err:
        _LOGGER.warning("Error closing LLM client sessions: %s", err)

    # Save pending memory changes before unloading
    try:
        memory_manager = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("memory_manager")
        if memory_manager:
            await memory_manager.async_shutdown()
            _LOGGER.debug("Memory manager shutdown complete")
    except Exception as err:
        _LOGGER.warning("Error shutting down memory manager: %s", err)

    # Save pending request history before unloading
    try:
        request_history = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("request_history")
        if request_history:
            await request_history.async_shutdown()
            _LOGGER.debug("Request history store shutdown complete")
    except Exception as err:
        _LOGGER.warning("Error shutting down request history store: %s", err)

    # Remove sidebar panel
    try:
        from homeassistant.components.frontend import async_remove_panel
        if hass.data.get("frontend_panels", {}).get(DOMAIN):
            async_remove_panel(hass, DOMAIN)
            _LOGGER.debug("Removed Smart Assist sidebar panel")
    except (ImportError, AttributeError):
        pass

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug("Smart Assist options updated, reloading")
    await hass.config_entries.async_reload(entry.entry_id)
