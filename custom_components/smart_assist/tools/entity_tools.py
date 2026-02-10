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
            # Try exact match first, fall back to substring, then translation fallback
            exact = [e for e in entities if e.area_name and e.area_name.lower() == area_lower]
            if exact:
                entities = exact
            else:
                substring = [e for e in entities if e.area_name and area_lower in e.area_name.lower()]
                if substring:
                    entities = substring
                else:
                    # Translation fallback: LLM sometimes uses English area names
                    area_translations = {
                        "kitchen": "küche", "bedroom": "schlafzimmer",
                        "living room": "wohnzimmer", "bathroom": "badezimmer",
                        "hallway": "flur", "garage": "garage",
                        "office": "büro", "garden": "garten",
                        "balcony": "balkon", "basement": "keller",
                        "attic": "dachboden", "dining room": "esszimmer",
                        "laundry": "waschküche", "nursery": "kinderzimmer",
                        "guest room": "gästezimmer", "corridor": "flur",
                    }
                    translated = area_translations.get(area_lower)
                    if translated:
                        exact_t = [e for e in entities if e.area_name and e.area_name.lower() == translated]
                        if exact_t:
                            entities = exact_t
                        else:
                            entities = [e for e in entities if e.area_name and translated in e.area_name.lower()]
        if name_filter:
            filter_lower = name_filter.lower()
            entities = [e for e in entities if filter_lower in e.friendly_name.lower()]

        if not entities:
            return ToolResult(
                success=True,
                message="No entities found matching the filters.",
            )

        # Build entity list with state and group indicators
        entity_lines: list[str] = []
        for e in entities[:20]:
            hass_state = self._hass.states.get(e.entity_id)
            state_str = ""
            group_str = ""
            if hass_state:
                state_str = f" [{hass_state.state}]"
                member_ids = hass_state.attributes.get("entity_id")
                if isinstance(member_ids, list) and member_ids:
                    group_str = f" [GROUP, {len(member_ids)} members]"
            area_str = f" ({e.area_name})" if e.area_name else ""
            entity_lines.append(f"- {e.entity_id}: {e.friendly_name}{area_str}{state_str}{group_str}")
        entity_list = "\n".join(entity_lines)

        message = f"Found {len(entities)} entities:\n{entity_list}"

        # Add smart control hints when multiple entities found
        if len(entities) > 1:
            group_ids: list[str] = []
            individual_ids: list[str] = []
            for e in entities[:20]:
                st = self._hass.states.get(e.entity_id)
                if st and isinstance(st.attributes.get("entity_id"), list):
                    group_ids.append(e.entity_id)
                else:
                    individual_ids.append(e.entity_id)

            if group_ids:
                message += f"\n\nNote: {', '.join(group_ids)} are GROUP entities that control multiple members. Prefer controlling the group instead of individual members."

            all_ids = [e.entity_id for e in entities[:20]]
            ids_str = str(all_ids)
            message += f"\nTip: To control all at once: control(entity_ids={ids_str}, action=...)"

        return ToolResult(
            success=True,
            message=message,
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

        message = entity_state.to_compact_string(hass=self._hass)

        # For group entities, include member states so the LLM can see
        # which members are on/off (group state "on" = ANY member on)
        member_ids = state.attributes.get("entity_id")
        if isinstance(member_ids, list) and member_ids:
            member_lines = []
            for member_id in member_ids:
                member_state = self._hass.states.get(member_id)
                if member_state:
                    member_es = EntityState(
                        entity_id=member_id,
                        state=member_state.state,
                        attributes=dict(member_state.attributes),
                    )
                    member_lines.append(f"  {member_es.to_compact_string(hass=self._hass)}")
                else:
                    member_lines.append(f"  {member_id}: unavailable")
            message += f"\nGroup members ({len(member_ids)}):\n" + "\n".join(member_lines)

        return ToolResult(
            success=True,
            message=message,
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
            description="How to aggregate results: 'raw' (all changes), 'summary' (min/max/avg or counts), 'last_change' (most recent), 'periods' (on/off time ranges for switches/lights)",
            required=False,
            enum=["raw", "summary", "last_change", "periods"],
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

        elif aggregation == "periods":
            # Calculate on/off time periods for binary entities (switches, lights)
            # Returns periods like "on from 15:18 to 19:45 (4h 27min)"
            on_states = {"on", "playing", "home", "open", "unlocked", "active", "heating", "cooling"}
            periods = []
            current_on_start = None
            
            for s in states:
                state_lower = s.state.lower()
                is_on = state_lower in on_states
                
                if is_on and current_on_start is None:
                    # Start of an "on" period
                    current_on_start = s.last_changed
                elif not is_on and current_on_start is not None:
                    # End of an "on" period
                    duration = s.last_changed - current_on_start
                    duration_mins = int(duration.total_seconds() / 60)
                    if duration_mins >= 60:
                        duration_str = f"{duration_mins // 60}h {duration_mins % 60}min"
                    else:
                        duration_str = f"{duration_mins}min"
                    
                    periods.append({
                        "start": current_on_start.strftime("%H:%M"),
                        "end": s.last_changed.strftime("%H:%M"),
                        "duration": duration_str,
                    })
                    current_on_start = None
            
            # Handle still-on period
            if current_on_start is not None:
                duration = now - current_on_start
                duration_mins = int(duration.total_seconds() / 60)
                if duration_mins >= 60:
                    duration_str = f"{duration_mins // 60}h {duration_mins % 60}min"
                else:
                    duration_str = f"{duration_mins}min"
                
                periods.append({
                    "start": current_on_start.strftime("%H:%M"),
                    "end": "now",
                    "duration": duration_str,
                })
            
            if not periods:
                return ToolResult(
                    success=True,
                    message=f"{entity_id} was not on during the last {period}.",
                )
            
            # Format periods
            lines = [f"{entity_id} was on during {period}:"]
            for p in periods[-10:]:  # Limit to last 10 periods
                if p["end"] == "now":
                    lines.append(f"  from {p['start']} until now ({p['duration']})")
                else:
                    lines.append(f"  from {p['start']} to {p['end']} ({p['duration']})")
            
            # Calculate total on time
            total_on_mins = sum(
                int(p["duration"].replace("h ", "*60+").replace("min", "").replace("*60+", "*60+") or "0")
                if "h" not in p["duration"]
                else int(p["duration"].split("h")[0]) * 60 + int(p["duration"].split("h")[1].replace("min", "").strip())
                for p in periods
            )
            if total_on_mins >= 60:
                total_str = f"{total_on_mins // 60}h {total_on_mins % 60}min"
            else:
                total_str = f"{total_on_mins}min"
            lines.append(f"  Total on time: {total_str}")
            
            return ToolResult(
                success=True,
                message="\n".join(lines),
                data={"periods": periods, "total_on_minutes": total_on_mins},
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
