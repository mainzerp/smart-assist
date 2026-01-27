"""Calendar reminder tracking for Smart Assist.

This module provides staged reminder functionality for calendar events,
preventing repetitive reminders while ensuring important events are mentioned
at appropriate times before they occur.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Final

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class ReminderStage(Enum):
    """Reminder stages for an event."""

    DAY_BEFORE = "day_before"  # 24h before
    HOURS_BEFORE = "hours_before"  # 4h before
    HOUR_BEFORE = "hour_before"  # 1h before
    PASSED = "passed"  # Event started


# Reminder thresholds with time windows (min, max)
# Reminder only triggers if time_until is within window
REMINDER_WINDOWS: Final = {
    ReminderStage.DAY_BEFORE: (timedelta(hours=20), timedelta(hours=28)),  # 24h +-4h
    ReminderStage.HOURS_BEFORE: (timedelta(hours=3), timedelta(hours=5)),  # 4h +-1h
    ReminderStage.HOUR_BEFORE: (timedelta(minutes=10), timedelta(minutes=90)),  # 10min to 90min before
}

# Human-readable reminder templates per stage
REMINDER_TEMPLATES: Final = {
    ReminderStage.DAY_BEFORE: "Morgen um {time} hast du '{summary}'",
    ReminderStage.HOURS_BEFORE: "In etwa {hours} Stunden hast du '{summary}'",
    ReminderStage.HOUR_BEFORE: "In {minutes} Minuten hast du '{summary}'",
}


class CalendarReminderTracker:
    """Tracks calendar reminders with staged notification.

    This class prevents repetitive reminders by tracking which reminder stages
    have been completed for each event. Events are reminded about at most 3 times:
    - ~24 hours before
    - ~4 hours before
    - ~1 hour before

    Each stage has a time window. If no interaction occurs during a window,
    that reminder is skipped (not caught up later).
    """

    def __init__(self) -> None:
        """Initialize the reminder tracker."""
        # {event_hash: set of completed ReminderStages}
        self._completed_stages: dict[str, set[ReminderStage]] = {}

    def _event_hash(self, event: dict) -> str:
        """Create unique hash for event.

        Args:
            event: Event dict with 'summary' and 'start' keys.

        Returns:
            Short hash string identifying this specific event.
        """
        key = f"{event.get('summary', '')}_{event.get('start', '')}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def _parse_event_time(self, time_str: str | None) -> datetime | None:
        """Parse event time string to datetime.

        Args:
            time_str: ISO format datetime string or date string.

        Returns:
            Parsed datetime or None if parsing fails.
        """
        if not time_str:
            return None

        try:
            # Try datetime format first (2024-01-28T15:00:00)
            if "T" in time_str:
                # Handle timezone-aware strings
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                # Convert to local time
                return dt_util.as_local(dt)
            else:
                # All-day event (date only) - assume midnight
                from datetime import date as date_type

                d = date_type.fromisoformat(time_str)
                return datetime.combine(d, datetime.min.time())
        except (ValueError, TypeError) as err:
            _LOGGER.debug("Failed to parse event time '%s': %s", time_str, err)
            return None

    def _get_current_stage(self, event: dict, now: datetime) -> ReminderStage | None:
        """Determine which reminder stage applies based on time window.

        Args:
            event: Event dict with 'start' key.
            now: Current datetime.

        Returns:
            The active ReminderStage or None if not in any window.
        """
        event_start = self._parse_event_time(event.get("start"))
        if not event_start:
            return None

        # Make both timezone-aware or naive for comparison
        if event_start.tzinfo is None:
            now = now.replace(tzinfo=None)
        elif now.tzinfo is None:
            now = dt_util.as_local(now)

        time_until = event_start - now

        if time_until <= timedelta(0):
            return ReminderStage.PASSED

        # Check each window - order matters (smallest window first)
        for stage in [
            ReminderStage.HOUR_BEFORE,
            ReminderStage.HOURS_BEFORE,
            ReminderStage.DAY_BEFORE,
        ]:
            window_min, window_max = REMINDER_WINDOWS[stage]
            if window_min <= time_until <= window_max:
                return stage

        return None  # Not in any reminder window

    def should_remind(
        self, event: dict, now: datetime | None = None
    ) -> tuple[bool, str]:
        """Check if event should trigger a reminder.

        Args:
            event: Event dict with 'summary', 'start', and optionally 'owner' keys.
            now: Current datetime (defaults to now).

        Returns:
            Tuple of (should_remind: bool, reminder_text: str).
            If should_remind is False, reminder_text will be empty.
        """
        if now is None:
            now = dt_util.now()

        event_hash = self._event_hash(event)
        current_stage = self._get_current_stage(event, now)

        # Not in any reminder window
        if current_stage is None or current_stage == ReminderStage.PASSED:
            return False, ""

        # Check if this stage was already completed
        completed = self._completed_stages.get(event_hash, set())
        if current_stage in completed:
            return False, ""

        # Generate reminder text based on stage
        event_start = self._parse_event_time(event.get("start"))
        if not event_start:
            return False, ""

        summary = event.get("summary", "Termin")
        owner = event.get("owner", "")

        if current_stage == ReminderStage.DAY_BEFORE:
            time_str = event_start.strftime("%H:%M")
            if owner:
                reminder_text = f"{owner} hat morgen um {time_str} '{summary}'"
            else:
                reminder_text = f"Morgen um {time_str} hast du '{summary}'"
        elif current_stage == ReminderStage.HOURS_BEFORE:
            # Make both timezone-aware or naive for calculation
            if event_start.tzinfo is None:
                now_calc = now.replace(tzinfo=None)
            else:
                now_calc = dt_util.as_local(now)
            hours = int((event_start - now_calc).total_seconds() / 3600)
            if owner:
                reminder_text = f"{owner} hat in etwa {hours} Stunden '{summary}'"
            else:
                reminder_text = f"In etwa {hours} Stunden hast du '{summary}'"
        elif current_stage == ReminderStage.HOUR_BEFORE:
            # Make both timezone-aware or naive for calculation
            if event_start.tzinfo is None:
                now_calc = now.replace(tzinfo=None)
            else:
                now_calc = dt_util.as_local(now)
            minutes = int((event_start - now_calc).total_seconds() / 60)
            if owner:
                reminder_text = f"{owner} hat in {minutes} Minuten '{summary}'"
            else:
                reminder_text = f"In {minutes} Minuten hast du '{summary}'"
        else:
            return False, ""

        return True, reminder_text

    def mark_reminded(self, event: dict, now: datetime | None = None) -> None:
        """Mark current reminder stage as completed.

        Args:
            event: Event dict.
            now: Current datetime (defaults to now).
        """
        if now is None:
            now = dt_util.now()

        event_hash = self._event_hash(event)
        current_stage = self._get_current_stage(event, now)

        if current_stage and current_stage != ReminderStage.PASSED:
            if event_hash not in self._completed_stages:
                self._completed_stages[event_hash] = set()
            self._completed_stages[event_hash].add(current_stage)
            _LOGGER.debug(
                "Marked reminder stage %s as completed for event %s",
                current_stage.value,
                event.get("summary", "unknown"),
            )

    def cleanup_past_events(
        self, events: list[dict], now: datetime | None = None
    ) -> None:
        """Remove tracking data for past events to prevent memory leaks.

        Args:
            events: List of current/future events.
            now: Current datetime (defaults to now).
        """
        if now is None:
            now = dt_util.now()

        current_hashes = {self._event_hash(e) for e in events}
        old_hashes = set(self._completed_stages.keys()) - current_hashes

        for old_hash in old_hashes:
            del self._completed_stages[old_hash]
            _LOGGER.debug("Cleaned up reminder tracking for past event %s", old_hash)

    def get_reminders(
        self, events: list[dict], now: datetime | None = None
    ) -> list[str]:
        """Get all reminders that should be shown for a list of events.

        Args:
            events: List of event dicts.
            now: Current datetime (defaults to now).

        Returns:
            List of reminder text strings.
        """
        if now is None:
            now = dt_util.now()

        reminders = []
        for event in events:
            should_remind, reminder_text = self.should_remind(event, now)
            if should_remind:
                reminders.append(reminder_text)
                self.mark_reminded(event, now)

        # Cleanup old events
        self.cleanup_past_events(events, now)

        return reminders
