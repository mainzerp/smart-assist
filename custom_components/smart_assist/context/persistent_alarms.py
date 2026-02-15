"""Persistent alarm manager for Smart Assist.

Provides absolute-time alarm scheduling with Home Assistant Storage persistence
so alarms survive restarts.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import (
    PERSISTENT_ALARM_STORAGE_KEY,
    PERSISTENT_ALARM_STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _empty_store_data() -> dict[str, Any]:
    """Return empty persistent alarm storage structure."""
    return {
        "version": PERSISTENT_ALARM_STORAGE_VERSION,
        "alarms": [],
    }


class PersistentAlarmManager:
    """Manage restart-safe, absolute-time alarms."""

    def __init__(self, hass: HomeAssistant | None) -> None:
        """Initialize manager with optional Home Assistant storage backend."""
        self._hass = hass
        self._store: Store | None = None
        if hass is not None:
            self._store = Store(
                hass,
                PERSISTENT_ALARM_STORAGE_VERSION,
                PERSISTENT_ALARM_STORAGE_KEY,
            )

        self._data: dict[str, Any] = _empty_store_data()
        self._dirty = False
        self._last_save: float = 0.0
        self._save_debounce_seconds = 5.0

    async def async_load(self) -> None:
        """Load alarms from HA storage."""
        if self._store is None:
            return

        stored = await self._store.async_load()
        if stored is None:
            self._data = _empty_store_data()
            _LOGGER.info("No persistent alarm storage found, starting fresh")
            return

        self.import_state(stored)
        _LOGGER.info("Loaded %d persistent alarms", len(self._data.get("alarms", [])))

    async def async_save(self) -> None:
        """Persist alarms with debounce."""
        if self._store is None or not self._dirty:
            return

        now = time.monotonic()
        if now - self._last_save < self._save_debounce_seconds:
            return

        await self.async_force_save()

    async def async_force_save(self) -> None:
        """Persist alarms immediately."""
        if self._store is None:
            return

        try:
            await self._store.async_save(self._data)
            self._dirty = False
            self._last_save = time.monotonic()
        except Exception as err:
            _LOGGER.error("Failed to save persistent alarms: %s", err)

    async def async_shutdown(self) -> None:
        """Flush pending changes during unload/shutdown."""
        if self._dirty:
            await self.async_force_save()

    def create_alarm(
        self,
        when_iso: str,
        label: str | None = None,
        message: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """Create a new alarm at an absolute datetime."""
        trigger_dt = self._parse_datetime(when_iso)
        if trigger_dt is None:
            return None, "Invalid datetime format"

        now = dt_util.now()
        if trigger_dt <= now:
            return None, "Alarm time must be in the future"

        created_at = now.isoformat()
        alarm_id = self._generate_id()
        alarm = {
            "id": alarm_id,
            "label": (label or "Alarm").strip() or "Alarm",
            "message": (message or "").strip(),
            "created_at": created_at,
            "updated_at": created_at,
            "scheduled_for": trigger_dt.isoformat(),
            "active": True,
            "status": "active",
            "dismissed": False,
            "fired": False,
            "snoozed_until": None,
            "last_fired_at": None,
            "fire_count": 0,
        }

        self._data.setdefault("alarms", []).append(alarm)
        self._dirty = True
        return dict(alarm), "Alarm created"

    def list_alarms(self, active_only: bool = True) -> list[dict[str, Any]]:
        """Return sorted alarm list."""
        alarms = list(self._data.get("alarms", []))
        if active_only:
            alarms = [alarm for alarm in alarms if alarm.get("active") is True]

        def _sort_key(alarm: dict[str, Any]) -> tuple[int, str]:
            next_trigger = alarm.get("snoozed_until") or alarm.get("scheduled_for") or ""
            return (0 if alarm.get("active") else 1, str(next_trigger))

        alarms.sort(key=_sort_key)
        return [dict(alarm) for alarm in alarms]

    def get_alarm(self, alarm_id: str) -> dict[str, Any] | None:
        """Return a copy of alarm by id."""
        alarm = self._find_alarm(alarm_id)
        return dict(alarm) if alarm else None

    def cancel_alarm(self, alarm_id: str) -> bool:
        """Cancel (dismiss) alarm by id."""
        alarm = self._find_alarm(alarm_id)
        if alarm is None or not alarm.get("active", False):
            return False

        alarm["active"] = False
        alarm["dismissed"] = True
        alarm["status"] = "dismissed"
        alarm["updated_at"] = dt_util.now().isoformat()
        self._dirty = True
        return True

    def snooze_alarm(
        self,
        alarm_id: str,
        minutes: int,
    ) -> tuple[dict[str, Any] | None, str]:
        """Snooze an active alarm by N minutes from now."""
        if minutes <= 0:
            return None, "Snooze minutes must be greater than zero"

        alarm = self._find_alarm(alarm_id)
        if alarm is None:
            return None, "Alarm not found"
        if not alarm.get("active", False):
            return None, "Alarm is not active"

        snooze_until = dt_util.now() + timedelta(minutes=minutes)
        alarm["snoozed_until"] = snooze_until.isoformat()
        alarm["status"] = "snoozed"
        alarm["updated_at"] = dt_util.now().isoformat()
        self._dirty = True
        return dict(alarm), "Alarm snoozed"

    def pop_due_alarms(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Mark and return alarms due at or before now."""
        reference = now or dt_util.now()
        due: list[dict[str, Any]] = []

        for alarm in self._data.get("alarms", []):
            if not alarm.get("active", False):
                continue

            trigger = self._next_trigger_datetime(alarm)
            if trigger is None:
                continue

            if trigger <= reference:
                alarm["active"] = False
                alarm["fired"] = True
                alarm["status"] = "fired"
                alarm["last_fired_at"] = reference.isoformat()
                alarm["fire_count"] = int(alarm.get("fire_count", 0)) + 1
                alarm["updated_at"] = reference.isoformat()
                due.append(dict(alarm))

        if due:
            self._dirty = True

        return due

    def import_state(self, stored: dict[str, Any]) -> None:
        """Import persisted state data, applying required defaults."""
        data = stored if isinstance(stored, dict) else {}
        alarms = data.get("alarms", [])

        if not isinstance(alarms, list):
            alarms = []

        normalized: list[dict[str, Any]] = []
        for raw in alarms:
            if not isinstance(raw, dict):
                continue

            alarm = dict(raw)
            alarm.setdefault("id", self._generate_id())
            alarm.setdefault("label", "Alarm")
            alarm.setdefault("message", "")
            now_iso = dt_util.now().isoformat()
            alarm.setdefault("created_at", now_iso)
            alarm.setdefault("updated_at", now_iso)
            alarm.setdefault("scheduled_for", now_iso)
            alarm.setdefault("active", True)
            alarm.setdefault("status", "active")
            alarm.setdefault("dismissed", False)
            alarm.setdefault("fired", False)
            alarm.setdefault("snoozed_until", None)
            alarm.setdefault("last_fired_at", None)
            alarm.setdefault("fire_count", 0)
            normalized.append(alarm)

        self._data = {
            "version": PERSISTENT_ALARM_STORAGE_VERSION,
            "alarms": normalized,
        }
        self._dirty = False

    def export_state(self) -> dict[str, Any]:
        """Return a copy of persisted state (for diagnostics/tests)."""
        return {
            "version": self._data.get("version", PERSISTENT_ALARM_STORAGE_VERSION),
            "alarms": [dict(alarm) for alarm in self._data.get("alarms", [])],
        }

    def _find_alarm(self, alarm_id: str) -> dict[str, Any] | None:
        """Find mutable alarm by id."""
        for alarm in self._data.get("alarms", []):
            if alarm.get("id") == alarm_id:
                return alarm
        return None

    def _next_trigger_datetime(self, alarm: dict[str, Any]) -> datetime | None:
        """Resolve next trigger datetime for alarm."""
        trigger_value = alarm.get("snoozed_until") or alarm.get("scheduled_for")
        if not isinstance(trigger_value, str):
            return None
        return self._parse_datetime(trigger_value)

    def _parse_datetime(self, value: str) -> datetime | None:
        """Parse datetime string to timezone-aware local datetime."""
        parsed = dt_util.parse_datetime(value)
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

        return dt_util.as_local(parsed)

    def _generate_id(self) -> str:
        """Create unique alarm id."""
        return f"alarm_{int(time.time())}_{uuid.uuid4().hex[:8]}"
