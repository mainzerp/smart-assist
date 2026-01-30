"""Entity control tools for Smart Assist."""

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


class GetEntitiesTool(BaseTool):
    """Tool to get entities matching filters."""

    name = "get_entities"
    description = "Search for entities by domain, area, or name. Use ONLY when entity is not found in the ENTITY INDEX or when caching is disabled. Always specify at least the domain filter."
    parameters = [
        ToolParameter(
            name="domain",
            type="string",
            description="Entity domain (light, switch, climate, cover, media_player, etc.) - REQUIRED",
            required=True,
        ),
        ToolParameter(
            name="area",
            type="string",
            description="Area/room name to filter by (optional)",
            required=False,
        ),
        ToolParameter(
            name="name_filter",
            type="string",
            description="Filter entities by name - partial match (optional)",
            required=False,
        ),
    ]

    async def execute(
        self,
        domain: str,
        area: str | None = None,
        name_filter: str | None = None,
    ) -> ToolResult:
        """Execute the get_entities tool."""
        from ..context.entity_manager import EntityManager

        manager = EntityManager(self._hass)
        entities = manager.get_all_entities()

        # Apply domain filter (required)
        entities = [e for e in entities if e.domain == domain]
        
        # Apply optional filters
        if area:
            area_lower = area.lower()
            entities = [e for e in entities if e.area_name and area_lower in e.area_name.lower()]
        if name_filter:
            filter_lower = name_filter.lower()
            entities = [e for e in entities if filter_lower in e.friendly_name.lower()]

        if not entities:
            return ToolResult(
                success=True,
                message="No entities found matching the filters.",
            )

        entity_list = "\n".join(
            f"- {e.entity_id}: {e.friendly_name}" + (f" ({e.area_name})" if e.area_name else "")
            for e in entities[:20]  # Limit to 20
        )

        return ToolResult(
            success=True,
            message=f"Found {len(entities)} entities:\n{entity_list}",
            data={"entities": [e.entity_id for e in entities]},
        )


class GetEntityStateTool(BaseTool):
    """Tool to get current state of an entity."""

    name = "get_entity_state"
    description = "Get the current state and attributes of a specific entity."
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="The entity ID (e.g., light.living_room)",
            required=True,
        ),
    ]

    async def execute(self, entity_id: str) -> ToolResult:
        """Execute the get_entity_state tool."""
        state = self._hass.states.get(entity_id)

        if not state:
            return ToolResult(
                success=False,
                message=f"Entity {entity_id} not found.",
            )

        from ..context.entity_manager import EntityState

        entity_state = EntityState(
            entity_id=entity_id,
            state=state.state,
            attributes=dict(state.attributes),
        )

        return ToolResult(
            success=True,
            message=entity_state.to_compact_string(),
            data={"state": state.state, "attributes": dict(state.attributes)},
        )


class ControlEntityTool(BaseTool):
    """Tool for basic entity control."""

    name = "control_entity"
    description = "Control an entity: turn on, turn off, or toggle."
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="The entity ID to control",
            required=True,
        ),
        ToolParameter(
            name="action",
            type="string",
            description="Action to perform",
            required=True,
            enum=["turn_on", "turn_off", "toggle"],
        ),
    ]

    async def execute(self, entity_id: str, action: str) -> ToolResult:
        """Execute the control_entity tool."""
        domain = entity_id.split(".")[0]

        service_map = {
            "turn_on": SERVICE_TURN_ON,
            "turn_off": SERVICE_TURN_OFF,
            "toggle": SERVICE_TOGGLE,
        }

        service = service_map.get(action)
        if not service:
            return ToolResult(
                success=False,
                message=f"Unknown action: {action}",
            )

        try:
            await self._hass.services.async_call(
                domain,
                service,
                {ATTR_ENTITY_ID: entity_id},
                blocking=True,
            )

            return ToolResult(
                success=True,
                message=f"Successfully executed {action} on {entity_id}.",
            )
        except Exception as err:
            return ToolResult(
                success=False,
                message=f"Failed to {action} {entity_id}: {err}",
            )


class ControlLightTool(BaseTool):
    """Tool for light-specific control."""

    name = "control_light"
    description = "Control a light with brightness, color, or temperature."
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="The light entity ID",
            required=True,
        ),
        ToolParameter(
            name="action",
            type="string",
            description="Action: turn_on, turn_off, or set",
            required=True,
            enum=["turn_on", "turn_off", "set"],
        ),
        ToolParameter(
            name="brightness",
            type="number",
            description="Brightness percentage (0-100)",
            required=False,
        ),
        ToolParameter(
            name="color_temp",
            type="number",
            description="Color temperature in Kelvin (2000-6500)",
            required=False,
        ),
        ToolParameter(
            name="rgb_color",
            type="array",
            description="RGB color as [R, G, B] (0-255 each)",
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
    ) -> ToolResult:
        """Execute the control_light tool."""
        if action == "turn_off":
            try:
                await self._hass.services.async_call(
                    "light",
                    SERVICE_TURN_OFF,
                    {ATTR_ENTITY_ID: entity_id},
                    blocking=True,
                )
                return ToolResult(success=True, message=f"Turned off {entity_id}.")
            except Exception as err:
                return ToolResult(success=False, message=f"Failed: {err}")

        # Build service data for turn_on
        service_data: dict[str, Any] = {ATTR_ENTITY_ID: entity_id}

        if brightness is not None:
            service_data["brightness_pct"] = max(0, min(100, brightness))

        if color_temp is not None:
            service_data["color_temp_kelvin"] = max(2000, min(6500, color_temp))

        if rgb_color is not None and len(rgb_color) == 3:
            service_data["rgb_color"] = rgb_color

        try:
            await self._hass.services.async_call(
                "light",
                SERVICE_TURN_ON,
                service_data,
                blocking=True,
            )

            details = []
            if brightness is not None:
                details.append(f"brightness={brightness}%")
            if color_temp is not None:
                details.append(f"color_temp={color_temp}K")
            if rgb_color is not None:
                details.append(f"rgb={rgb_color}")

            detail_str = ", ".join(details) if details else "on"
            return ToolResult(
                success=True,
                message=f"Set {entity_id} to {detail_str}.",
            )
        except Exception as err:
            return ToolResult(success=False, message=f"Failed: {err}")


class ControlClimateTool(BaseTool):
    """Tool for climate/thermostat control."""

    name = "control_climate"
    description = "Control a thermostat: set temperature, HVAC mode, or preset."
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="The climate entity ID",
            required=True,
        ),
        ToolParameter(
            name="temperature",
            type="number",
            description="Target temperature in Celsius",
            required=False,
        ),
        ToolParameter(
            name="hvac_mode",
            type="string",
            description="HVAC mode",
            required=False,
            enum=["off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only"],
        ),
        ToolParameter(
            name="preset",
            type="string",
            description="Preset mode (e.g., away, home, comfort)",
            required=False,
        ),
    ]

    async def execute(
        self,
        entity_id: str,
        temperature: float | None = None,
        hvac_mode: str | None = None,
        preset: str | None = None,
    ) -> ToolResult:
        """Execute the control_climate tool."""
        results = []

        try:
            if hvac_mode is not None:
                await self._hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {ATTR_ENTITY_ID: entity_id, "hvac_mode": hvac_mode},
                    blocking=True,
                )
                results.append(f"mode={hvac_mode}")

            if temperature is not None:
                await self._hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {ATTR_ENTITY_ID: entity_id, "temperature": temperature},
                    blocking=True,
                )
                results.append(f"temp={temperature}C")

            if preset is not None:
                await self._hass.services.async_call(
                    "climate",
                    "set_preset_mode",
                    {ATTR_ENTITY_ID: entity_id, "preset_mode": preset},
                    blocking=True,
                )
                results.append(f"preset={preset}")

            if not results:
                return ToolResult(
                    success=False,
                    message="No climate settings provided.",
                )

            return ToolResult(
                success=True,
                message=f"Set {entity_id}: {', '.join(results)}.",
            )
        except Exception as err:
            return ToolResult(success=False, message=f"Failed: {err}")


class ControlMediaTool(BaseTool):
    """Tool for media player control."""

    name = "control_media"
    description = "Control a media player: play, pause, volume, source."
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="The media player entity ID",
            required=True,
        ),
        ToolParameter(
            name="action",
            type="string",
            description="Media action",
            required=True,
            enum=[
                "play",
                "pause",
                "stop",
                "next",
                "previous",
                "volume_up",
                "volume_down",
                "mute",
                "unmute",
            ],
        ),
        ToolParameter(
            name="volume",
            type="number",
            description="Volume level (0-100)",
            required=False,
        ),
        ToolParameter(
            name="source",
            type="string",
            description="Input source to select",
            required=False,
        ),
    ]

    async def execute(
        self,
        entity_id: str,
        action: str,
        volume: int | None = None,
        source: str | None = None,
    ) -> ToolResult:
        """Execute the control_media tool."""
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

        try:
            service = service_map.get(action)
            if service:
                service_data: dict[str, Any] = {ATTR_ENTITY_ID: entity_id}
                if action == "mute":
                    service_data["is_volume_muted"] = True
                elif action == "unmute":
                    service_data["is_volume_muted"] = False

                await self._hass.services.async_call(
                    "media_player",
                    service,
                    service_data,
                    blocking=True,
                )

            if volume is not None:
                await self._hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {ATTR_ENTITY_ID: entity_id, "volume_level": volume / 100},
                    blocking=True,
                )

            if source is not None:
                await self._hass.services.async_call(
                    "media_player",
                    "select_source",
                    {ATTR_ENTITY_ID: entity_id, "source": source},
                    blocking=True,
                )

            return ToolResult(
                success=True,
                message=f"Executed {action} on {entity_id}.",
            )
        except Exception as err:
            return ToolResult(success=False, message=f"Failed: {err}")


class ControlCoverTool(BaseTool):
    """Tool for cover/blind control."""

    name = "control_cover"
    description = "Control blinds/shutters/covers: open, close, or set position."
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="The cover entity ID",
            required=True,
        ),
        ToolParameter(
            name="action",
            type="string",
            description="Cover action",
            required=True,
            enum=["open", "close", "stop", "set_position"],
        ),
        ToolParameter(
            name="position",
            type="number",
            description="Position percentage (0=closed, 100=open)",
            required=False,
        ),
    ]

    async def execute(
        self,
        entity_id: str,
        action: str,
        position: int | None = None,
    ) -> ToolResult:
        """Execute the control_cover tool."""
        service_map = {
            "open": "open_cover",
            "close": "close_cover",
            "stop": "stop_cover",
        }

        try:
            if action == "set_position" and position is not None:
                await self._hass.services.async_call(
                    "cover",
                    "set_cover_position",
                    {ATTR_ENTITY_ID: entity_id, "position": position},
                    blocking=True,
                )
                return ToolResult(
                    success=True,
                    message=f"Set {entity_id} position to {position}%.",
                )

            service = service_map.get(action)
            if service:
                await self._hass.services.async_call(
                    "cover",
                    service,
                    {ATTR_ENTITY_ID: entity_id},
                    blocking=True,
                )
                return ToolResult(
                    success=True,
                    message=f"Executed {action} on {entity_id}.",
                )

            return ToolResult(success=False, message=f"Unknown action: {action}")
        except Exception as err:
            return ToolResult(success=False, message=f"Failed: {err}")


class GetEntityHistoryTool(BaseTool):
    """Tool to get historical states of an entity."""

    name = "get_entity_history"
    description = "Get historical states of an entity. Use for questions about past states like 'How was the temperature yesterday?' or 'When was the light last on?'"
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="The entity ID to query history for",
            required=True,
        ),
        ToolParameter(
            name="period",
            type="string",
            description="Time period to query",
            required=False,
            enum=["1h", "6h", "12h", "24h", "48h", "7d"],
        ),
        ToolParameter(
            name="aggregation",
            type="string",
            description="How to aggregate results: 'raw' (all changes, max 20), 'summary' (min/max/avg), 'last_change' (most recent change)",
            required=False,
            enum=["raw", "summary", "last_change"],
        ),
    ]

    async def execute(
        self,
        entity_id: str,
        period: str = "24h",
        aggregation: str = "summary",
    ) -> ToolResult:
        """Execute the get_entity_history tool."""
        from collections import Counter
        from datetime import timedelta

        from homeassistant.components.recorder import get_instance, history
        from homeassistant.util import dt as dt_util

        # Parse period
        period_map = {
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "12h": timedelta(hours=12),
            "24h": timedelta(hours=24),
            "48h": timedelta(hours=48),
            "7d": timedelta(days=7),
        }
        delta = period_map.get(period, timedelta(hours=24))

        now = dt_util.utcnow()
        start_time = now - delta

        try:
            instance = get_instance(self._hass)
            states_dict = await instance.async_add_executor_job(
                history.state_changes_during_period,
                self._hass,
                start_time,
                now,
                entity_id,
                False,  # no_attributes - include attributes
                False,  # descending
                100 if aggregation == "raw" else None,  # limit for raw
                True,  # include_start_time_state
            )
        except Exception as err:
            _LOGGER.error("Failed to query history for %s: %s", entity_id, err)
            return ToolResult(
                success=False,
                message=f"Failed to query history: {err}",
            )

        if not states_dict or entity_id not in states_dict:
            return ToolResult(
                success=True,
                message=f"No history found for {entity_id} in the last {period}.",
            )

        states = states_dict[entity_id]

        if not states:
            return ToolResult(
                success=True,
                message=f"No state changes for {entity_id} in the last {period}.",
            )

        if aggregation == "last_change":
            # Format the most recent state change
            last = states[-1]
            time_str = last.last_changed.strftime("%Y-%m-%d %H:%M:%S")
            return ToolResult(
                success=True,
                message=f"{entity_id} was last '{last.state}' at {time_str}",
                data={"state": last.state, "time": time_str},
            )

        elif aggregation == "summary":
            # Try numeric aggregation
            numeric_values = []
            for s in states:
                try:
                    val = float(s.state)
                    numeric_values.append(val)
                except (ValueError, TypeError):
                    pass

            if numeric_values:
                # Numeric sensor - calculate statistics
                unit = states[0].attributes.get("unit_of_measurement", "")
                min_val = min(numeric_values)
                max_val = max(numeric_values)
                avg_val = sum(numeric_values) / len(numeric_values)

                msg = (
                    f"{entity_id} over {period}: "
                    f"min={min_val:.1f}{unit}, max={max_val:.1f}{unit}, "
                    f"avg={avg_val:.1f}{unit}, readings={len(states)}"
                )
            else:
                # Discrete states - count occurrences
                state_counts = Counter(s.state for s in states)
                counts_str = ", ".join(
                    f"{k}={v}" for k, v in state_counts.most_common(5)
                )
                msg = (
                    f"{entity_id} over {period}: {counts_str}, "
                    f"total changes={len(states)}"
                )

            return ToolResult(
                success=True,
                message=msg,
                data={"states_count": len(states)},
            )

        else:  # raw
            # Format raw state changes (limited to 20)
            lines = [f"{entity_id} history ({period}, {len(states)} changes):"]
            for s in states[-20:]:
                time_str = s.last_changed.strftime("%H:%M:%S")
                lines.append(f"  {time_str}: {s.state}")

            return ToolResult(
                success=True,
                message="\n".join(lines),
                data={"states_count": len(states)},
            )
