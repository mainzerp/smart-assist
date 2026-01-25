"""Unified entity control tool for Smart Assist."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_TOGGLE,
)

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class UnifiedControlTool(BaseTool):
    """Unified tool for controlling any entity type.
    
    This consolidated tool handles:
    - Basic on/off/toggle for all entities
    - Light-specific: brightness, color, color_temp
    - Climate-specific: temperature, hvac_mode, preset
    - Media-specific: play, pause, volume, source
    - Cover-specific: open, close, position
    
    Domain is auto-detected from entity_id.
    """

    name = "control"
    description = """Control any entity. Actions depend on entity type:
- All: turn_on, turn_off, toggle
- light.*: set brightness (0-100), color_temp (2000-6500K), rgb_color [r,g,b]
- climate.*: set temperature, hvac_mode (off/heat/cool/auto), preset
- media_player.*: play, pause, stop, next, previous, volume (0-100), source
- cover.*: open, close, stop, position (0-100)
- script.*: turn_on/run to execute"""
    
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="The entity ID to control (e.g., light.living_room)",
            required=True,
        ),
        ToolParameter(
            name="action",
            type="string",
            description="Action: turn_on, turn_off, toggle, play, pause, stop, open, close, etc.",
            required=True,
        ),
        # Optional parameters for domain-specific control
        ToolParameter(
            name="brightness",
            type="number",
            description="Light brightness percentage (0-100)",
            required=False,
        ),
        ToolParameter(
            name="color_temp",
            type="number",
            description="Light color temperature in Kelvin (2000-6500)",
            required=False,
        ),
        ToolParameter(
            name="rgb_color",
            type="array",
            description="Light RGB color as [R, G, B] (0-255 each)",
            required=False,
        ),
        ToolParameter(
            name="temperature",
            type="number",
            description="Climate target temperature in Celsius",
            required=False,
        ),
        ToolParameter(
            name="hvac_mode",
            type="string",
            description="Climate HVAC mode: off, heat, cool, heat_cool, auto, dry, fan_only",
            required=False,
        ),
        ToolParameter(
            name="preset",
            type="string",
            description="Climate preset mode (e.g., away, home, comfort)",
            required=False,
        ),
        ToolParameter(
            name="volume",
            type="number",
            description="Media player volume (0-100)",
            required=False,
        ),
        ToolParameter(
            name="source",
            type="string",
            description="Media player input source",
            required=False,
        ),
        ToolParameter(
            name="position",
            type="number",
            description="Cover position percentage (0=closed, 100=open)",
            required=False,
        ),
    ]

    async def execute(
        self,
        entity_id: str,
        action: str,
        brightness: int | None = None,
        color_temp: int | None = None,
        rgb_color: list[int] | None = None,
        temperature: float | None = None,
        hvac_mode: str | None = None,
        preset: str | None = None,
        volume: int | None = None,
        source: str | None = None,
        position: int | None = None,
    ) -> ToolResult:
        """Execute unified control based on entity domain."""
        domain = entity_id.split(".")[0]
        
        try:
            # Route to domain-specific handler
            if domain == "light":
                return await self._control_light(
                    entity_id, action, brightness, color_temp, rgb_color
                )
            elif domain == "climate":
                return await self._control_climate(
                    entity_id, action, temperature, hvac_mode, preset
                )
            elif domain == "media_player":
                return await self._control_media(
                    entity_id, action, volume, source
                )
            elif domain == "cover":
                return await self._control_cover(
                    entity_id, action, position
                )
            elif domain == "script":
                return await self._control_script(entity_id, action)
            else:
                # Generic on/off/toggle for other domains
                return await self._control_generic(entity_id, action)
                
        except Exception as err:
            _LOGGER.error("Control error for %s: %s", entity_id, err)
            return ToolResult(success=False, message=f"Failed to control {entity_id}: {err}")

    async def _control_generic(self, entity_id: str, action: str) -> ToolResult:
        """Generic on/off/toggle control."""
        domain = entity_id.split(".")[0]
        
        service_map = {
            "turn_on": SERVICE_TURN_ON,
            "turn_off": SERVICE_TURN_OFF,
            "toggle": SERVICE_TOGGLE,
        }
        
        service = service_map.get(action)
        if not service:
            return ToolResult(success=False, message=f"Unknown action '{action}' for {domain}")
        
        await self._hass.services.async_call(
            domain, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )
        return ToolResult(success=True, message=f"Executed {action} on {entity_id}.")

    async def _control_light(
        self,
        entity_id: str,
        action: str,
        brightness: int | None,
        color_temp: int | None,
        rgb_color: list[int] | None,
    ) -> ToolResult:
        """Light-specific control."""
        if action == "turn_off":
            await self._hass.services.async_call(
                "light", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
            )
            return ToolResult(success=True, message=f"Turned off {entity_id}.")
        
        # Build service data for turn_on
        service_data: dict[str, Any] = {ATTR_ENTITY_ID: entity_id}
        details = []
        
        if brightness is not None:
            service_data["brightness_pct"] = max(0, min(100, brightness))
            details.append(f"brightness={brightness}%")
        
        if color_temp is not None:
            service_data["color_temp_kelvin"] = max(2000, min(6500, color_temp))
            details.append(f"color_temp={color_temp}K")
        
        if rgb_color is not None and len(rgb_color) == 3:
            service_data["rgb_color"] = rgb_color
            details.append(f"rgb={rgb_color}")
        
        await self._hass.services.async_call(
            "light", SERVICE_TURN_ON, service_data, blocking=True
        )
        
        detail_str = ", ".join(details) if details else "on"
        return ToolResult(success=True, message=f"Set {entity_id} to {detail_str}.")

    async def _control_climate(
        self,
        entity_id: str,
        action: str,
        temperature: float | None,
        hvac_mode: str | None,
        preset: str | None,
    ) -> ToolResult:
        """Climate-specific control."""
        results = []
        
        if action == "turn_off" or hvac_mode == "off":
            await self._hass.services.async_call(
                "climate", "set_hvac_mode",
                {ATTR_ENTITY_ID: entity_id, "hvac_mode": "off"}, blocking=True
            )
            results.append("mode=off")
        elif hvac_mode is not None:
            await self._hass.services.async_call(
                "climate", "set_hvac_mode",
                {ATTR_ENTITY_ID: entity_id, "hvac_mode": hvac_mode}, blocking=True
            )
            results.append(f"mode={hvac_mode}")
        
        if temperature is not None:
            await self._hass.services.async_call(
                "climate", "set_temperature",
                {ATTR_ENTITY_ID: entity_id, "temperature": temperature}, blocking=True
            )
            results.append(f"temp={temperature}C")
        
        if preset is not None:
            await self._hass.services.async_call(
                "climate", "set_preset_mode",
                {ATTR_ENTITY_ID: entity_id, "preset_mode": preset}, blocking=True
            )
            results.append(f"preset={preset}")
        
        if not results:
            return ToolResult(success=False, message="No climate settings provided.")
        
        return ToolResult(success=True, message=f"Set {entity_id}: {', '.join(results)}.")

    async def _control_media(
        self,
        entity_id: str,
        action: str,
        volume: int | None,
        source: str | None,
    ) -> ToolResult:
        """Media player control."""
        service_map = {
            "play": "media_play",
            "pause": "media_pause",
            "stop": "media_stop",
            "next": "media_next_track",
            "previous": "media_previous_track",
            "volume_up": "volume_up",
            "volume_down": "volume_down",
            "mute": "volume_mute",
            "unmute": "volume_mute",
        }
        
        results = []
        
        if action in service_map:
            service = service_map[action]
            service_data: dict[str, Any] = {ATTR_ENTITY_ID: entity_id}
            
            if action == "mute":
                service_data["is_volume_muted"] = True
            elif action == "unmute":
                service_data["is_volume_muted"] = False
            
            await self._hass.services.async_call(
                "media_player", service, service_data, blocking=True
            )
            results.append(action)
        
        if volume is not None:
            await self._hass.services.async_call(
                "media_player", "volume_set",
                {ATTR_ENTITY_ID: entity_id, "volume_level": volume / 100}, blocking=True
            )
            results.append(f"volume={volume}%")
        
        if source is not None:
            await self._hass.services.async_call(
                "media_player", "select_source",
                {ATTR_ENTITY_ID: entity_id, "source": source}, blocking=True
            )
            results.append(f"source={source}")
        
        if not results:
            return ToolResult(success=False, message="No media action specified.")
        
        return ToolResult(success=True, message=f"Executed on {entity_id}: {', '.join(results)}.")

    async def _control_cover(
        self,
        entity_id: str,
        action: str,
        position: int | None,
    ) -> ToolResult:
        """Cover/blind control."""
        if action == "set_position" or (position is not None and action in ("turn_on", "open")):
            if position is None:
                position = 100 if action == "open" else 0
            await self._hass.services.async_call(
                "cover", "set_cover_position",
                {ATTR_ENTITY_ID: entity_id, "position": position}, blocking=True
            )
            return ToolResult(success=True, message=f"Set {entity_id} position to {position}%.")
        
        service_map = {
            "open": "open_cover",
            "close": "close_cover",
            "stop": "stop_cover",
            "turn_on": "open_cover",
            "turn_off": "close_cover",
        }
        
        service = service_map.get(action)
        if not service:
            return ToolResult(success=False, message=f"Unknown cover action: {action}")
        
        await self._hass.services.async_call(
            "cover", service, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )
        return ToolResult(success=True, message=f"Executed {action} on {entity_id}.")

    async def _control_script(self, entity_id: str, action: str) -> ToolResult:
        """Script execution."""
        if action in ("turn_on", "run", "execute"):
            await self._hass.services.async_call(
                "script", SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
            )
            return ToolResult(success=True, message=f"Executed script {entity_id}.")
        elif action == "turn_off":
            await self._hass.services.async_call(
                "script", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
            )
            return ToolResult(success=True, message=f"Stopped script {entity_id}.")
        else:
            return ToolResult(success=False, message=f"Unknown script action: {action}. Use 'turn_on' or 'run'.")
