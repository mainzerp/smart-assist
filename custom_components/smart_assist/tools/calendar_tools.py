"""Calendar tools for Smart Assist."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class GetCalendarEventsTool(BaseTool):
    """Tool to query calendar events."""

    name = "get_calendar_events"
    description = "Get upcoming calendar events for a time range."
    parameters = [
        ToolParameter(
            name="time_range",
            type="string",
            description="Calendar window to query: today, tomorrow, this_week, or next_7_days.",
            required=True,
            enum=["today", "tomorrow", "this_week", "next_7_days"],
        ),
        ToolParameter(
            name="calendar_id",
            type="string",
            description="Calendar entity ID (default: all)",
            required=False,
        ),
        ToolParameter(
            name="max_events",
            type="number",
            description="Maximum number of returned events (default: 10).",
            required=False,
            default=10,
            minimum=1,
            maximum=50,
        ),
    ]

    async def execute(
        self,
        time_range: str = "today",
        calendar_id: str | None = None,
        max_events: int = 10,
    ) -> ToolResult:
        """Execute the get_calendar_events tool."""
        # Calculate time window based on time_range
        now = dt_util.now()
        
        if time_range == "today":
            # Start from NOW to only show upcoming events, not past ones
            start = now
            end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif time_range == "tomorrow":
            tomorrow = now + timedelta(days=1)
            start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif time_range in ("this_week", "next_7_days"):
            start = now
            end = now + timedelta(days=7)
        else:
            return ToolResult(
                success=False,
                message=f"Invalid time_range: {time_range}. Use 'today', 'tomorrow', 'this_week', or 'next_7_days'.",
            )

        # Get calendar entities
        calendars: list[str] = []
        if calendar_id:
            # Ensure it's a calendar entity
            if not calendar_id.startswith("calendar."):
                calendar_id = f"calendar.{calendar_id}"
            calendars = [calendar_id]
        else:
            # Get all calendar entities
            calendars = [
                state.entity_id
                for state in self._hass.states.async_all()
                if state.entity_id.startswith("calendar.")
            ]

        if not calendars:
            return ToolResult(
                success=True,
                message="No calendar entities found.",
                data={"events": [], "count": 0},
            )

        # Fetch events from each calendar
        events: list[dict[str, Any]] = []
        for cal_id in calendars:
            try:
                result = await self._hass.services.async_call(
                    "calendar",
                    "get_events",
                    {
                        "entity_id": cal_id,
                        "start_date_time": start.isoformat(),
                        "end_date_time": end.isoformat(),
                    },
                    blocking=True,
                    return_response=True,
                )
                
                if result and cal_id in result:
                    # Extract owner name from calendar entity
                    calendar_name = self._get_calendar_owner(cal_id)
                    
                    for event in result[cal_id].get("events", []):
                        events.append({
                            "calendar": cal_id,
                            "owner": calendar_name,
                            "summary": event.get("summary", "Untitled"),
                            "start": event.get("start"),
                            "end": event.get("end"),
                            "location": event.get("location"),
                            "description": event.get("description"),
                        })
            except Exception as err:
                _LOGGER.warning("Failed to get events from %s: %s", cal_id, err)

        # Sort by start time and limit
        events.sort(key=lambda x: x.get("start", ""))
        events = events[:max_events]

        if not events:
            time_desc = {
                "today": "today",
                "tomorrow": "tomorrow",
                "this_week": "this week",
                "next_7_days": "in the next 7 days",
            }.get(time_range, time_range)
            
            return ToolResult(
                success=True,
                message=f"No events found {time_desc}.",
                data={"events": [], "count": 0},
            )

        # Format events for display
        event_lines = []
        for event in events:
            start_str = event.get("start", "")
            # Parse start time for display
            if "T" in start_str:
                # DateTime format
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M")
                    date_str = dt.strftime("%d.%m.")
                except (ValueError, TypeError):
                    time_str = start_str
                    date_str = ""
            else:
                # All-day event (date only)
                time_str = "All day"
                date_str = start_str
            
            owner = event.get("owner", "Calendar")
            summary = event.get("summary", "Untitled")
            
            if time_range in ("today", "tomorrow"):
                event_lines.append(f"- {time_str}: {summary} [{owner}]")
            else:
                event_lines.append(f"- {date_str} {time_str}: {summary} [{owner}]")
            
            if location := event.get("location"):
                event_lines.append(f"  Location: {location}")

        time_desc = {
            "today": "Today",
            "tomorrow": "Tomorrow",
            "this_week": "This week",
            "next_7_days": "Next 7 days",
        }.get(time_range, time_range)

        return ToolResult(
            success=True,
            message=f"{time_desc} ({len(events)} events):\n" + "\n".join(event_lines),
            data={"events": events, "count": len(events)},
        )

    def _get_calendar_owner(self, entity_id: str) -> str:
        """Extract owner name from calendar entity.
        
        Examples:
            calendar.laura -> "Laura"
            calendar.patric_arbeit -> "Patric Arbeit"
            calendar.familie -> "Familie"
        """
        # Try friendly_name first (if user set custom name)
        state = self._hass.states.get(entity_id)
        if state and state.attributes.get("friendly_name"):
            return state.attributes["friendly_name"]
        
        # Fallback: Extract from entity_id
        # calendar.laura -> "laura" -> "Laura"
        name = entity_id.split(".", 1)[-1]  # Remove domain
        name = name.replace("_", " ")  # calendar.patric_arbeit -> "patric arbeit"
        return name.title()  # "Laura", "Patric Arbeit"


class CreateCalendarEventTool(BaseTool):
    """Tool to create calendar events."""

    name = "create_calendar_event"
    description = "Create a calendar event. Calendar can be a name or entity ID (fuzzy matched)."
    parameters = [
        ToolParameter(
            name="calendar_id",
            type="string",
            description="Calendar name or entity ID (fuzzy matched)",
            required=True,
        ),
        ToolParameter(
            name="summary",
            type="string",
            description="Event title/summary",
            required=True,
        ),
        ToolParameter(
            name="start_date_time",
            type="string",
            description="Start ISO datetime (e.g., '2024-01-28T15:00:00')",
            required=False,
        ),
        ToolParameter(
            name="end_date_time",
            type="string",
            description="End ISO datetime (default: start + 1h)",
            required=False,
        ),
        ToolParameter(
            name="start_date",
            type="string",
            description="Start date for all-day events (YYYY-MM-DD)",
            required=False,
        ),
        ToolParameter(
            name="end_date",
            type="string",
            description="End date exclusive for all-day (default: next day)",
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="Event description",
            required=False,
        ),
        ToolParameter(
            name="location",
            type="string",
            description="Event location",
            required=False,
        ),
    ]

    async def execute(
        self,
        calendar_id: str,
        summary: str,
        start_date_time: str | None = None,
        end_date_time: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> ToolResult:
        """Execute the create_calendar_event tool."""
        # Fuzzy match calendar_id to actual calendar entity
        matched_calendar = await self._match_calendar(calendar_id)
        
        if not matched_calendar:
            # List available calendars in error message
            available = self._get_available_calendars()
            cal_list = ", ".join([c["name"] for c in available]) if available else "none"
            return ToolResult(
                success=False,
                message=f"Calendar '{calendar_id}' not found. Available calendars: {cal_list}",
            )
        
        calendar_entity_id = matched_calendar["entity_id"]
        calendar_name = matched_calendar["name"]

        # Build service data
        service_data: dict[str, Any] = {
            "entity_id": calendar_entity_id,
            "summary": summary,
        }

        # Handle date/time parameters
        if start_date_time:
            # Timed event
            service_data["start_date_time"] = start_date_time
            
            if end_date_time:
                service_data["end_date_time"] = end_date_time
            else:
                # Default to 1 hour duration
                try:
                    from datetime import datetime
                    start_dt = datetime.fromisoformat(start_date_time.replace("Z", "+00:00"))
                    end_dt = start_dt + timedelta(hours=1)
                    service_data["end_date_time"] = end_dt.isoformat()
                except (ValueError, TypeError):
                    service_data["end_date_time"] = start_date_time  # Fallback
        elif start_date:
            # All-day event
            service_data["start_date"] = start_date
            
            if end_date:
                service_data["end_date"] = end_date
            else:
                # Default to next day (end is exclusive)
                try:
                    from datetime import date, datetime
                    start_d = date.fromisoformat(start_date)
                    end_d = start_d + timedelta(days=1)
                    service_data["end_date"] = end_d.isoformat()
                except (ValueError, TypeError):
                    return ToolResult(
                        success=False,
                        message=f"Invalid start_date format: {start_date}. Use YYYY-MM-DD.",
                    )
        else:
            return ToolResult(
                success=False,
                message="Either start_date_time or start_date is required.",
            )

        # Add optional fields
        if description:
            service_data["description"] = description
        if location:
            service_data["location"] = location

        try:
            await self._hass.services.async_call(
                "calendar",
                "create_event",
                service_data,
                blocking=True,
            )

            # Build confirmation message
            if start_date_time:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(start_date_time.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M")
                    date_str = dt.strftime("%Y-%m-%d")
                    confirmation = f"'{summary}' on {date_str} at {time_str}"
                except (ValueError, TypeError):
                    confirmation = f"'{summary}' at {start_date_time}"
            else:
                confirmation = f"'{summary}' on {start_date} (all day)"

            return ToolResult(
                success=True,
                message=f"Created event: {confirmation} in {calendar_name}'s calendar.",
                data={
                    "calendar": calendar_entity_id,
                    "summary": summary,
                    "start": start_date_time or start_date,
                },
            )

        except Exception as err:
            _LOGGER.error("Failed to create calendar event: %s", err)
            return ToolResult(
                success=False,
                message=f"Failed to create calendar event: {err}",
            )

    def _get_available_calendars(self) -> list[dict[str, str]]:
        """Get all available calendar entities with their names.
        
        Returns:
            List of dicts with 'entity_id' and 'name' keys.
        """
        calendars = []
        for state in self._hass.states.async_all():
            if state.entity_id.startswith("calendar."):
                name = self._get_calendar_owner(state.entity_id)
                calendars.append({
                    "entity_id": state.entity_id,
                    "name": name,
                })
        return calendars

    async def _match_calendar(self, calendar_input: str) -> dict[str, str] | None:
        """Fuzzy match calendar input to actual calendar entity.
        
        Args:
            calendar_input: User-provided calendar name or entity ID
            
        Returns:
            Dict with 'entity_id' and 'name', or None if no match found.
        """
        available = self._get_available_calendars()
        
        if not available:
            return None
        
        # Normalize input for matching
        input_lower = calendar_input.lower().strip()
        
        # Remove "calendar." prefix if provided
        if input_lower.startswith("calendar."):
            input_lower = input_lower[9:]
        
        # Try exact match first
        for cal in available:
            entity_suffix = cal["entity_id"].split(".", 1)[-1].lower()
            name_lower = cal["name"].lower()
            
            if input_lower == entity_suffix or input_lower == name_lower:
                _LOGGER.debug("Exact calendar match: %s -> %s", calendar_input, cal["entity_id"])
                return cal
        
        # Try fuzzy matching (substring, similarity)
        best_match = None
        best_score = 0.0
        
        for cal in available:
            entity_suffix = cal["entity_id"].split(".", 1)[-1].lower()
            name_lower = cal["name"].lower()
            
            # Check substring match
            if input_lower in entity_suffix or input_lower in name_lower:
                score = len(input_lower) / max(len(entity_suffix), len(name_lower))
                if score > best_score:
                    best_score = score
                    best_match = cal
                continue
            
            if entity_suffix in input_lower or name_lower in input_lower:
                score = len(entity_suffix) / len(input_lower)
                if score > best_score:
                    best_score = score
                    best_match = cal
                continue
            
            # Calculate similarity score (simple character matching)
            score = self._calculate_similarity(input_lower, entity_suffix)
            name_score = self._calculate_similarity(input_lower, name_lower)
            max_score = max(score, name_score)
            
            if max_score > best_score:
                best_score = max_score
                best_match = cal
        
        # Only accept if score is reasonably strong
        if best_match and best_score >= 0.72:
            _LOGGER.debug(
                "Fuzzy calendar match: %s -> %s (score: %.2f)",
                calendar_input, best_match["entity_id"], best_score
            )
            return best_match
        
        _LOGGER.debug("No calendar match found for: %s (best score: %.2f)", calendar_input, best_score)
        return None

    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """Calculate normalized similarity with sequence + token overlap.

        Returns a score between 0.0 (no match) and 1.0 (exact match).
        """
        left = re.sub(r"[^a-z0-9]+", " ", (s1 or "").lower()).strip()
        right = re.sub(r"[^a-z0-9]+", " ", (s2 or "").lower()).strip()
        if not left or not right:
            return 0.0
        if left == right:
            return 1.0

        seq_score = SequenceMatcher(None, left, right).ratio()

        left_tokens = {token for token in left.split(" ") if token}
        right_tokens = {token for token in right.split(" ") if token}
        token_union = left_tokens | right_tokens
        token_score = (len(left_tokens & right_tokens) / len(token_union)) if token_union else 0.0

        prefix_bonus = 0.05 if left and right and left[0] == right[0] else 0.0
        return min(1.0, (seq_score * 0.75) + (token_score * 0.25) + prefix_bonus)

    def _get_calendar_owner(self, entity_id: str) -> str:
        """Extract owner name from calendar entity."""
        state = self._hass.states.get(entity_id)
        if state and state.attributes.get("friendly_name"):
            return state.attributes["friendly_name"]
        
        name = entity_id.split(".", 1)[-1]
        name = name.replace("_", " ")
        return name.title()
