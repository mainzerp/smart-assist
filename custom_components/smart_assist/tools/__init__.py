"""Tools module for Smart Assist.

This module provides a tool registry with dynamic loading based on:
- Available entity domains in Home Assistant
- User configuration (e.g., web search enabled/disabled)

Tools are loaded dynamically to minimize token usage in API requests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .base import BaseTool, ToolRegistry, ToolResult
from ..const import CONF_ENABLE_WEB_SEARCH

if TYPE_CHECKING:
    from typing import Any


def _get_config(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Get config value from options first, then data, then default."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


def create_tool_registry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    available_domains: set[str] | None = None,
) -> ToolRegistry:
    """Create a tool registry with dynamically loaded tools.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry with user settings
        available_domains: Set of entity domains available in HA.
                          If None, will be auto-detected.
    
    Returns:
        ToolRegistry with appropriate tools registered
    """
    from .entity_tools import GetEntitiesTool, GetEntityStateTool
    from .unified_control import UnifiedControlTool
    from .scene_tools import RunSceneTool, TriggerAutomationTool
    from .search_tools import GetWeatherTool, WebSearchTool
    
    registry = ToolRegistry(hass)
    
    # Auto-detect available domains if not provided
    if available_domains is None:
        available_domains = {
            state.entity_id.split(".")[0]
            for state in hass.states.async_all()
        }
    
    # Core tools (always available)
    registry.register(GetEntitiesTool(hass))
    registry.register(GetEntityStateTool(hass))
    registry.register(UnifiedControlTool(hass))  # Handles all entity control including scripts
    
    # Scene tool (if domain exists) - scripts handled by unified control
    if "scene" in available_domains:
        registry.register(RunSceneTool(hass))
    
    # Automation trigger (if domain exists)
    if "automation" in available_domains:
        registry.register(TriggerAutomationTool(hass))
    
    # Weather tool (if weather entity exists)
    if "weather" in available_domains:
        registry.register(GetWeatherTool(hass))
    
    # Web search (if enabled in config - options override data)
    if _get_config(entry, CONF_ENABLE_WEB_SEARCH, True):
        registry.register(WebSearchTool(hass))
    
    return registry


# Exports - only actively used tools
from .entity_tools import GetEntitiesTool, GetEntityStateTool
from .unified_control import UnifiedControlTool
from .scene_tools import RunSceneTool, TriggerAutomationTool
from .search_tools import WebSearchTool, GetWeatherTool

__all__ = [
    # Base classes
    "BaseTool",
    "ToolRegistry",
    "ToolResult",
    "create_tool_registry",
    # Core tools
    "GetEntitiesTool",
    "GetEntityStateTool",
    "UnifiedControlTool",
    # Scene/Automation
    "RunSceneTool",
    "TriggerAutomationTool",
    # Utility
    "WebSearchTool",
    "GetWeatherTool",
]
