"""Smart Assist - LLM-powered Home Assistant conversation integration."""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Any

# Set up logging FIRST
_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STARTED
    from homeassistant.core import HomeAssistant, Event
    from homeassistant.helpers.event import async_track_time_interval
except ImportError as e:
    _LOGGER.error("Smart Assist __init__.py: Failed to import HA core: %s", e)
    raise

try:
    from .const import (
        CONF_CACHE_REFRESH_INTERVAL,
        CONF_CACHE_TTL_EXTENDED,
        CONF_ENABLE_CACHE_WARMING,
        CONF_ENABLE_PROMPT_CACHING,
        DEFAULT_CACHE_REFRESH_INTERVAL,
        DEFAULT_CACHE_TTL_EXTENDED,
        DEFAULT_ENABLE_CACHE_WARMING,
        DOMAIN,
    )
except ImportError as e:
    _LOGGER.error("Smart Assist __init__.py: Failed to import const: %s", e)
    raise

_LOGGER.warning("Smart Assist: __init__.py module loaded successfully")

PLATFORMS: list[Platform] = [Platform.CONVERSATION, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Smart Assist component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Smart Assist from a config entry."""
    _LOGGER.info("Setting up Smart Assist integration")

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}

    # Set up conversation platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Schedule cache warming and periodic refresh if enabled
    if (
        entry.data.get(CONF_ENABLE_PROMPT_CACHING, True)
        and entry.data.get(CONF_ENABLE_CACHE_WARMING, DEFAULT_ENABLE_CACHE_WARMING)
    ):
        async def _cache_warming_callback(event: Event) -> None:
            """Perform cache warming after Home Assistant starts."""
            await _perform_cache_warming(hass, entry)
            # Start periodic cache refresh
            _start_cache_refresh_timer(hass, entry)

        # If HA is already running, warm cache immediately
        if hass.is_running:
            hass.async_create_task(_perform_cache_warming(hass, entry))
            _start_cache_refresh_timer(hass, entry)
        else:
            # Otherwise wait for HA to start
            entry.async_on_unload(
                hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, _cache_warming_callback
                )
            )

    _LOGGER.info("Smart Assist integration setup complete")
    return True


def _start_cache_refresh_timer(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Start periodic cache refresh timer."""
    from datetime import timedelta
    
    # Get user-configured refresh interval (in minutes)
    interval_minutes = entry.data.get(
        CONF_CACHE_REFRESH_INTERVAL, DEFAULT_CACHE_REFRESH_INTERVAL
    )
    interval_seconds = interval_minutes * 60
    
    async def _refresh_cache(now: Any) -> None:
        """Periodically refresh the cache."""
        _LOGGER.debug("Refreshing prompt cache (periodic)")
        await _perform_cache_warming(hass, entry, initial=False)
    
    # Register the periodic task
    cancel_refresh = async_track_time_interval(
        hass,
        _refresh_cache,
        timedelta(seconds=interval_seconds),
    )
    
    # Store cancellation function and register for cleanup
    hass.data[DOMAIN][entry.entry_id]["cancel_cache_refresh"] = cancel_refresh
    entry.async_on_unload(cancel_refresh)
    
    _LOGGER.info(
        "Cache refresh timer started (interval: %d minutes)",
        interval_minutes,
    )


async def _perform_cache_warming(
    hass: HomeAssistant, entry: ConfigEntry, initial: bool = True
) -> None:
    """Perform cache warming by sending a minimal request to populate the cache.
    
    This pre-populates the prompt cache with the system prompt and entity index,
    reducing latency and cost for subsequent requests.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        initial: If True, wait for entities to load (first run only)
    """
    _LOGGER.debug("Starting cache warming for Smart Assist")
    
    # Wait a bit for entities to be fully loaded (only on initial warmup)
    if initial:
        await asyncio.sleep(5)
    
    try:
        # Get the conversation entity
        from .conversation import SmartAssistConversationEntity
        
        agent_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        entity: SmartAssistConversationEntity | None = agent_data.get("agent")
        
        if entity is None:
            _LOGGER.debug("No entity found for cache warming, skipping")
            return
        
        # Perform a minimal warming request
        # This builds the system prompt and entity index, populating the cache
        await entity.warm_cache()
        
        _LOGGER.info("Cache warming completed successfully")
        
    except Exception as err:
        _LOGGER.warning("Cache warming failed: %s", err)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Smart Assist integration")

    # Close LLM client session before unloading
    try:
        agent_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        if agent := agent_data.get("agent"):
            if hasattr(agent, "_llm_client") and agent._llm_client:
                await agent._llm_client.close()
                _LOGGER.debug("Closed LLM client session")
    except Exception as err:
        _LOGGER.warning("Error closing LLM client session: %s", err)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug("Smart Assist options updated, reloading")
    await hass.config_entries.async_reload(entry.entry_id)
