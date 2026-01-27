"""Calendar tools for Smart Assist."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class GetCalendarEventsTool(BaseTool):
    """Tool to query calendar events."""

    name = "get_calendar_events"
    description = "Get upcoming calendar events for a specific time range. Use this to answer questions about appointments, schedules, and upcoming events."
    parameters = [
        ToolParameter(
            name="time_range",
            type="string",
            description="Time range for events: 'today', 'tomorrow', 'this_week', or 'next_7_days'",
            required=True,
            enum=["today", "tomorrow", "this_week", "next_7_days"],
        ),
        ToolParameter(
            name="calendar_id",
            type="string",
            description="Calendar entity ID (e.g., calendar.family). If not specified, queries all calendars.",
            required=False,
        ),
        ToolParameter(
            name="max_events",
            type="number",
            description="Maximum number of events to return (default: 10)",
            required=False,
            default=10,
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
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
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
    description = "Create a new event on a calendar. Use this when the user wants to add an appointment, meeting, or reminder to their calendar. If you don't know the exact calendar entity ID, first use get_calendar_events to see available calendars and their owners."
    parameters = [
        ToolParameter(
            name="calendar_id",
            type="string",
            description="Calendar entity ID (e.g., calendar.laura, calendar.family). The entity name usually matches the owner's name. Required.",
            required=True,
        ),
        ToolParameter(
            name="summary",
            type="string",
            description="Title/summary of the event (e.g., 'Arzttermin', 'Meeting mit Team')",
            required=True,
        ),
        ToolParameter(
            name="start_date_time",
            type="string",
            description="Start date and time in ISO format (e.g., '2024-01-28T15:00:00'). For all-day events, use start_date instead.",
            required=False,
        ),
        ToolParameter(
            name="end_date_time",
            type="string",
            description="End date and time in ISO format (e.g., '2024-01-28T16:00:00'). If not specified, defaults to 1 hour after start.",
            required=False,
        ),
        ToolParameter(
            name="start_date",
            type="string",
            description="Start date for all-day events (e.g., '2024-01-28'). Use this instead of start_date_time for all-day events.",
            required=False,
        ),
        ToolParameter(
            name="end_date",
            type="string",
            description="End date (exclusive) for all-day events (e.g., '2024-01-29'). If not specified for all-day events, defaults to next day.",
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="Optional detailed description of the event.",
            required=False,
        ),
        ToolParameter(
            name="location",
            type="string",
            description="Optional location of the event.",
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
        # Ensure it's a calendar entity
        if not calendar_id.startswith("calendar."):
            calendar_id = f"calendar.{calendar_id}"

        # Validate that the calendar exists
        state = self._hass.states.get(calendar_id)
        if not state:
            return ToolResult(
                success=False,
                message=f"Calendar '{calendar_id}' not found. Please check the calendar name.",
            )

        # Build service data
        service_data: dict[str, Any] = {
            "entity_id": calendar_id,
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
            calendar_name = self._get_calendar_owner(calendar_id)
            
            if start_date_time:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(start_date_time.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M")
                    date_str = dt.strftime("%d.%m.%Y")
                    confirmation = f"'{summary}' am {date_str} um {time_str}"
                except (ValueError, TypeError):
                    confirmation = f"'{summary}' at {start_date_time}"
            else:
                confirmation = f"'{summary}' am {start_date} (ganztaegig)"

            return ToolResult(
                success=True,
                message=f"Termin erstellt: {confirmation} in {calendar_name}s Kalender.",
                data={
                    "calendar": calendar_id,
                    "summary": summary,
                    "start": start_date_time or start_date,
                },
            )

        except Exception as err:
            _LOGGER.error("Failed to create calendar event: %s", err)
            return ToolResult(
                success=False,
                message=f"Fehler beim Erstellen des Termins: {err}",
            )

    def _get_calendar_owner(self, entity_id: str) -> str:
        """Extract owner name from calendar entity."""
        state = self._hass.states.get(entity_id)
        if state and state.attributes.get("friendly_name"):
            return state.attributes["friendly_name"]
        
        name = entity_id.split(".", 1)[-1]
        name = name.replace("_", " ")
        return name.title()
