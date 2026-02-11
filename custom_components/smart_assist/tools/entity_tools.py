"""Entity control tools for Smart Assist."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.const import ATTR_ENTITY_ID

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class GetEntitiesTool(BaseTool):
    """Tool to get entities matching filters."""

    name = "get_entities"
    description = "Search entities by domain/area/name. Use only if not in ENTITY INDEX."
    parameters = [
        ToolParameter(
            name="domain",
            type="string",
            description="Entity domain (light, switch, climate, cover, media_player, etc.)",
            required=True,
        ),
        ToolParameter(
            name="area",
            type="string",
            description="Area/room name filter",
            required=False,
        ),
        ToolParameter(
            name="name_filter",
            type="string",
            description="Name substring filter",
            required=False,
        ),
    ]

    def __init__(self, hass: HomeAssistant, entity_manager: Any | None = None) -> None:
        """Initialize the tool with optional shared EntityManager."""
        super().__init__(hass)
        self._entity_manager = entity_manager

    async def execute(
        self,
        domain: str,
        area: str | None = None,
        name_filter: str | None = None,
    ) -> ToolResult:
        """Execute the get_entities tool."""
        if self._entity_manager:
            entities = self._entity_manager.get_all_entities()
        else:
            from ..context.entity_manager import EntityManager
            manager = EntityManager(self._hass)
            entities = manager.get_all_entities()

        # Apply domain filter (required)
        entities = [e for e in entities if e.domain == domain]
        
        # Apply optional filters
        if area:
            area_lower = area.lower()
            # Try exact match first, fall back to substring
            exact = [e for e in entities if e.area_name and e.area_name.lower() == area_lower]
            if exact:
                entities = exact
            else:
                entities = [e for e in entities if e.area_name and area_lower in e.area_name.lower()]
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

        # Suggest batch control for multiple entities
        if len(entities) > 1:
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
    description = "Get current state and attributes of an entity."
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="Entity ID (e.g., light.living_room)",
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


class GetEntityHistoryTool(BaseTool):
    """Tool to get historical states of an entity."""

    name = "get_entity_history"
    description = "Get historical states of an entity for past-state questions."
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="Entity ID",
            required=True,
        ),
        ToolParameter(
            name="period",
            type="string",
            description="Time period",
            required=False,
            enum=["1h", "6h", "12h", "24h", "48h", "7d"],
        ),
        ToolParameter(
            name="aggregation",
            type="string",
            description="raw=all changes, summary=stats, last_change=most recent, periods=on/off durations",
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
                        "duration_mins": duration_mins,
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
                    "duration_mins": duration_mins,
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
            
            # Calculate total on time from stored duration_mins
            total_on_mins = sum(p.get("duration_mins", 0) for p in periods)
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
