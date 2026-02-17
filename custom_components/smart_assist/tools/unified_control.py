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
    description = (
        "Control one or more Home Assistant entities by action and optional value parameters. "
        "Use after entity IDs are known from index/discovery; pass exactly one of entity_id or entity_ids."
    )
    
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="Single entity ID. Required when entity_ids is not provided; do not pass with entity_ids.",
            required=False,
        ),
        ToolParameter(
            name="entity_ids",
            type="array",
            description="Multiple entity IDs for batch control. Required when entity_id is not provided; do not pass with entity_id.",
            required=False,
            items={"type": "string"},
            min_items=1,
        ),
        ToolParameter(
            name="action",
            type="string",
            description="Action to execute, such as turn_on, turn_off, toggle, play, pause, stop, open, close, set_temperature, set_position.",
            required=True,
        ),
        # Optional parameters for domain-specific control
        ToolParameter(
            name="brightness",
            type="number",
            description="Brightness % (0-100)",
            required=False,
            minimum=0,
            maximum=100,
        ),
        ToolParameter(
            name="color_temp",
            type="number",
            description="Color temp in Kelvin (2000-6500)",
            required=False,
            minimum=2000,
            maximum=6500,
        ),
        ToolParameter(
            name="rgb_color",
            type="array",
            description="RGB as [R,G,B] (0-255)",
            required=False,
            items={"type": "number", "minimum": 0, "maximum": 255},
            min_items=3,
            max_items=3,
        ),
        ToolParameter(
            name="temperature",
            type="number",
            description="Target temp (Celsius)",
            required=False,
        ),
        ToolParameter(
            name="hvac_mode",
            type="string",
            description="off, heat, cool, heat_cool, auto, dry, fan_only",
            required=False,
        ),
        ToolParameter(
            name="preset",
            type="string",
            description="Preset (away, home, comfort, etc.)",
            required=False,
        ),
        ToolParameter(
            name="volume",
            type="number",
            description="Volume % (0-100)",
            required=False,
            minimum=0,
            maximum=100,
        ),
        ToolParameter(
            name="source",
            type="string",
            description="Input source",
            required=False,
        ),
        ToolParameter(
            name="position",
            type="number",
            description="Position % (0=closed, 100=open)",
            required=False,
            minimum=0,
            maximum=100,
        ),
    ]

    def _validate_range(
        self, value: int | float | None, min_val: int | float, max_val: int | float, name: str
    ) -> tuple[int | None, str | None]:
        """Validate a numeric value is within range. Returns (clamped_value, error_message)."""
        if value is None:
            return None, None
        int_val = int(value)
        if int_val < min_val:
            return int(min_val), f"{name} clamped from {value} to {int(min_val)} (minimum)"
        if int_val > max_val:
            return int(max_val), f"{name} clamped from {value} to {int(max_val)} (maximum)"
        return int_val, None

    def _validate_rgb(self, rgb: list[int] | None) -> tuple[list[int] | None, str | None]:
        """Validate RGB color values. Returns (clamped_rgb, error_message)."""
        if rgb is None:
            return None, None
        if len(rgb) != 3:
            return None, f"RGB must have 3 values, got {len(rgb)}"
        clamped = [max(0, min(255, v)) for v in rgb]
        if clamped != rgb:
            return clamped, f"RGB values clamped to 0-255 range"
        return rgb, None

    async def execute(
        self,
        entity_id: str | None = None,
        entity_ids: list[str] | None = None,
        action: str | None = None,
        brightness: int | None = None,
        color_temp: int | None = None,
        rgb_color: list[int] | None = None,
        temperature: float | None = None,
        hvac_mode: str | None = None,
        preset: str | None = None,
        volume: int | None = None,
        source: str | None = None,
        position: int | None = None,
        state: str | None = None,  # Alias for 'action' (some models use this)
    ) -> ToolResult:
        """Execute unified control -- dispatches to batch or single."""
        # Handle 'state' as alias for 'action' (some models incorrectly use this)
        if action is None and state is not None:
            action = "turn_on" if state in ("on", "true", "1") else "turn_off" if state in ("off", "false", "0") else state
            _LOGGER.debug("Mapped 'state=%s' to 'action=%s'", state, action)

        if action is None:
            return ToolResult(success=False, message="Missing required parameter: 'action'")

        # Batch mode: entity_ids takes priority
        if entity_ids and len(entity_ids) > 0:
            results: list[str] = []
            errors: list[str] = []
            for eid in entity_ids:
                single_result = await self._execute_single(
                    entity_id=eid, action=action, brightness=brightness,
                    color_temp=color_temp, rgb_color=rgb_color,
                    temperature=temperature, hvac_mode=hvac_mode, preset=preset,
                    volume=volume, source=source, position=position,
                )
                if single_result.success:
                    results.append(eid)
                else:
                    errors.append(f"{eid}: {single_result.message}")

            if errors:
                return ToolResult(
                    success=len(results) > 0,
                    message=f"Controlled {len(results)}/{len(results)+len(errors)} entities. Errors: {'; '.join(errors)}",
                )
            return ToolResult(
                success=True,
                message=f"Successfully executed {action} on {len(results)} entities.",
            )

        if not entity_id:
            return ToolResult(success=False, message="Missing required parameter: 'entity_id' or 'entity_ids'")

        return await self._execute_single(
            entity_id=entity_id, action=action, brightness=brightness,
            color_temp=color_temp, rgb_color=rgb_color,
            temperature=temperature, hvac_mode=hvac_mode, preset=preset,
            volume=volume, source=source, position=position,
        )

    async def _execute_single(
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
        """Execute unified control for a single entity."""
        domain = entity_id.split(".")[0]
        
        # Validate and clamp numeric parameters
        warnings: list[str] = []
        
        brightness, warn = self._validate_range(brightness, 0, 100, "brightness")
        if warn:
            warnings.append(warn)
        
        color_temp, warn = self._validate_range(color_temp, 2000, 6500, "color_temp")
        if warn:
            warnings.append(warn)
        
        volume, warn = self._validate_range(volume, 0, 100, "volume")
        if warn:
            warnings.append(warn)
        
        position, warn = self._validate_range(position, 0, 100, "position")
        if warn:
            warnings.append(warn)
        
        rgb_color, warn = self._validate_rgb(rgb_color)
        if warn:
            warnings.append(warn)
        
        if warnings:
            _LOGGER.debug("Parameter validation warnings: %s", warnings)
        
        _LOGGER.debug(
            "UnifiedControl: entity=%s, action=%s, domain=%s, extras=%s",
            entity_id,
            action,
            domain,
            {
                k: v for k, v in {
                    "brightness": brightness,
                    "color_temp": color_temp,
                    "rgb_color": rgb_color,
                    "temperature": temperature,
                    "hvac_mode": hvac_mode,
                    "preset": preset,
                    "volume": volume,
                    "source": source,
                    "position": position,
                }.items() if v is not None
            },
        )
        
        # Check if entity exists
        state = self._hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("Entity not found: %s", entity_id)
            return ToolResult(success=False, message=f"Entity {entity_id} not found.")
        
        _LOGGER.debug("Entity %s current state: %s", entity_id, state.state)
        
        # Check if entity is already in the desired state (simple on/off actions without extras)
        # IMPORTANT: Skip this optimization for group entities (light groups, groups, etc.)
        # because a group state "on" means ANY member is on, not ALL members.
        # Calling turn_on on a partially-on group correctly turns on all members.
        is_group = isinstance(state.attributes.get("entity_id"), list)
        current = state.state
        if not is_group:
            if action == "turn_on" and current == "on" and not any([brightness, color_temp, rgb_color, temperature, hvac_mode, preset, volume, source, position]):
                return ToolResult(success=True, message=f"{entity_id} is already on.")
            if action == "turn_off" and current == "off":
                return ToolResult(success=True, message=f"{entity_id} is already off.")
        
        try:
            # Route to domain-specific handler
            if domain == "light":
                result = await self._control_light(
                    entity_id, action, brightness, color_temp, rgb_color
                )
            elif domain == "climate":
                result = await self._control_climate(
                    entity_id, action, temperature, hvac_mode, preset
                )
            elif domain == "media_player":
                result = await self._control_media(
                    entity_id, action, volume, source
                )
            elif domain == "cover":
                result = await self._control_cover(
                    entity_id, action, position
                )
            elif domain == "script":
                result = await self._control_script(entity_id, action)
            else:
                # Generic on/off/toggle for other domains
                result = await self._control_generic(entity_id, action)
            
            _LOGGER.debug("UnifiedControl result: %s", result.message)
            return result
                
        except Exception as err:
            _LOGGER.error("Control error for %s: %s", entity_id, err, exc_info=True)
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
            # Check if entity supports select_source before calling
            state = self._hass.states.get(entity_id)
            supported_features = state.attributes.get("supported_features", 0) if state else 0
            # SUPPORT_SELECT_SOURCE = 2048 (MediaPlayerEntityFeature.SELECT_SOURCE)
            if supported_features & 2048:
                await self._hass.services.async_call(
                    "media_player", "select_source",
                    {ATTR_ENTITY_ID: entity_id, "source": source}, blocking=True
                )
                results.append(f"source={source}")
            else:
                _LOGGER.debug("Entity %s does not support select_source, skipping", entity_id)
                results.append(f"source={source} (not supported)")
        
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
