"""Persistent alarm manager for Smart Assist.

Provides absolute-time alarm scheduling with Home Assistant Storage persistence
so alarms survive restarts.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
import uuid
import calendar
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import (
    DIRECT_ALARM_STATE_SKIPPED,
    MANAGED_ALARM_SYNC_PENDING,
    PERSISTENT_ALARM_STORAGE_KEY,
    PERSISTENT_ALARM_STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _managed_defaults() -> dict[str, Any]:
    """Return default managed automation metadata block."""
    return {
        "enabled": False,
        "automation_entity_id": None,
        "ownership_verified": False,
        "sync_state": MANAGED_ALARM_SYNC_PENDING,
        "last_sync_at": None,
        "last_sync_error": None,
    }


def _empty_store_data() -> dict[str, Any]:
    """Return empty persistent alarm storage structure."""
    return {
        "version": PERSISTENT_ALARM_STORAGE_VERSION,
        "alarms": [],
    }


def _direct_defaults() -> dict[str, Any]:
    """Return default direct execution metadata block."""
    return {
        "last_executed_at": None,
        "last_state": DIRECT_ALARM_STATE_SKIPPED,
        "last_error": None,
        "last_backend_results": {},
        "last_fire_marker": None,
    }


def _delivery_defaults() -> dict[str, Any]:
    """Return default delivery metadata block."""
    return {
        "source_device_id": None,
        "source_satellite_id": None,
        "tts_targets": [],
        "wake_text": {
            "dynamic": False,
            "include_weather": False,
            "include_news": False,
        },
    }


class PersistentAlarmManager:
    """Manage restart-safe, absolute-time alarms."""

    def __init__(self, hass: HomeAssistant | None) -> None:
        """Initialize manager with optional Home Assistant storage backend."""
        self._hass = hass
        self._store: Store | None = None
        if hass is not None:
            try:
                self._store = Store(
                    hass,
                    PERSISTENT_ALARM_STORAGE_VERSION,
                    PERSISTENT_ALARM_STORAGE_KEY,
                    async_migrate_func=self._async_migrate_storage,
                )
            except TypeError:
                self._store = Store(
                    hass,
                    PERSISTENT_ALARM_STORAGE_VERSION,
                    PERSISTENT_ALARM_STORAGE_KEY,
                )
                if hasattr(self._store, "_async_migrate_func"):
                    self._store._async_migrate_func = self._async_migrate_storage

        self._data: dict[str, Any] = _empty_store_data()
        self._dirty = False
        self._last_save: float = 0.0
        self._save_debounce_seconds = 5.0

    async def _async_migrate_storage(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Migrate stored alarm payload to current schema version."""
        data = old_data if isinstance(old_data, dict) else {}
        alarms = data.get("alarms", [])
        if not isinstance(alarms, list):
            alarms = []

        _LOGGER.info(
            "Migrating persistent alarm storage from %s.%s to %s",
            old_major_version,
            old_minor_version,
            PERSISTENT_ALARM_STORAGE_VERSION,
        )

        return {
            "version": PERSISTENT_ALARM_STORAGE_VERSION,
            "alarms": alarms,
        }

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
        source: str | None = None,
        recurrence: dict[str, Any] | None = None,
        source_device_id: str | None = None,
        source_satellite_id: str | None = None,
        tts_targets: list[str] | None = None,
        wake_text: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """Create a new alarm at an absolute datetime."""
        trigger_dt = self._parse_datetime(when_iso)
        if trigger_dt is None:
            return None, "Invalid datetime format"

        normalized_recurrence = self._normalize_recurrence(recurrence, trigger_dt)
        if recurrence is not None and normalized_recurrence is None:
            return None, "Invalid recurrence configuration"

        now = dt_util.now()
        if trigger_dt <= now:
            return None, "Alarm time must be in the future"

        created_at = now.isoformat()
        alarm_id = self._generate_id()
        normalized_label = (label or "Alarm").strip() or "Alarm"
        display_id = self._generate_display_id(
            label=normalized_label,
            when_iso=trigger_dt.isoformat(),
        )
        alarm = {
            "id": alarm_id,
            "display_id": display_id,
            "label": normalized_label,
            "message": (message or "").strip(),
            "source": (source or "smart_assist").strip() or "smart_assist",
            "created_at": created_at,
            "updated_at": created_at,
            "scheduled_for": trigger_dt.isoformat(),
            "next_scheduled_for": trigger_dt.isoformat(),
            "recurrence": normalized_recurrence,
            "active": True,
            "status": "active",
            "dismissed": False,
            "fired": False,
            "snoozed_until": None,
            "last_fired_at": None,
            "fire_count": 0,
            "managed_automation": _managed_defaults(),
            "direct_execution": _direct_defaults(),
            "delivery": {
                "source_device_id": str(source_device_id or "").strip() or None,
                "source_satellite_id": str(source_satellite_id or "").strip() or None,
                "tts_targets": self._normalize_tts_targets(tts_targets),
                "wake_text": self._normalize_wake_text_options(wake_text),
            },
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

    def delete_alarm(self, alarm_id: str) -> bool:
        """Delete alarm permanently by machine id or display id."""
        target = self._normalize_lookup_value(alarm_id)
        if not target:
            return False

        alarms = self._data.get("alarms", [])
        if not isinstance(alarms, list):
            return False

        for index, alarm in enumerate(alarms):
            alarm_id_value = self._normalize_lookup_value(str(alarm.get("id") or ""))
            display_id_value = self._normalize_lookup_value(str(alarm.get("display_id") or ""))
            if target in {alarm_id_value, display_id_value}:
                del alarms[index]
                self._dirty = True
                return True

        return False

    def snooze_alarm(
        self,
        alarm_id: str,
        minutes: int,
    ) -> tuple[dict[str, Any] | None, str]:
        """Snooze an alarm by N minutes from now (supports fired reactivation)."""
        if minutes <= 0:
            return None, "Snooze minutes must be greater than zero"

        alarm = self._find_alarm(alarm_id)
        if alarm is None:
            return None, "Alarm not found"
        if alarm.get("dismissed", False):
            return None, "Alarm is dismissed"
        if not alarm.get("active", False) and alarm.get("status") != "fired":
            return None, "Alarm is not active"

        snooze_until = dt_util.now() + timedelta(minutes=minutes)
        alarm["snoozed_until"] = snooze_until.isoformat()
        alarm["active"] = True
        alarm["dismissed"] = False
        alarm["fired"] = False
        alarm["status"] = "snoozed"
        alarm["updated_at"] = dt_util.now().isoformat()
        self._dirty = True
        return dict(alarm), "Alarm snoozed"

    def get_recent_fired_alarms(
        self,
        window_minutes: int = 30,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return recently fired alarms within a time window, newest first."""
        now = dt_util.now()
        window = timedelta(minutes=max(1, int(window_minutes)))
        recent: list[dict[str, Any]] = []

        for alarm in self._data.get("alarms", []):
            if alarm.get("status") != "fired":
                continue

            last_fired_at = alarm.get("last_fired_at")
            if not isinstance(last_fired_at, str):
                continue

            fired_dt = self._parse_datetime(last_fired_at)
            if fired_dt is None:
                continue

            if (now - fired_dt) <= window:
                recent.append(dict(alarm))

        recent.sort(key=lambda item: item.get("last_fired_at") or "", reverse=True)
        return recent[: max(1, int(limit))]

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
                scheduled_before_fire = alarm.get("scheduled_for")
                recurrence = alarm.get("recurrence") if isinstance(alarm.get("recurrence"), dict) else None

                alarm["active"] = False
                alarm["fired"] = True
                alarm["status"] = "fired"
                alarm["last_fired_at"] = reference.isoformat()
                alarm["fire_count"] = int(alarm.get("fire_count", 0)) + 1
                alarm["updated_at"] = reference.isoformat()

                fired_occurrence = dict(alarm)

                if recurrence is not None and isinstance(scheduled_before_fire, str):
                    base_dt = self._parse_datetime(scheduled_before_fire)
                    next_dt = self._compute_next_occurrence(
                        base_dt,
                        recurrence,
                        reference,
                    )
                    if next_dt is not None:
                        alarm["scheduled_for"] = next_dt.isoformat()
                        alarm["next_scheduled_for"] = next_dt.isoformat()
                        alarm["snoozed_until"] = None
                        alarm["active"] = True
                        alarm["fired"] = False
                        alarm["dismissed"] = False
                        alarm["status"] = "active"
                        alarm["updated_at"] = reference.isoformat()
                        fired_occurrence["next_scheduled_for"] = next_dt.isoformat()

                due.append(fired_occurrence)

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
        used_display_ids: set[str] = set()
        for raw in alarms:
            if not isinstance(raw, dict):
                continue

            alarm = dict(raw)
            alarm.setdefault("id", self._generate_id())
            alarm.setdefault("label", "Alarm")
            alarm.setdefault("message", "")
            alarm.setdefault("source", "smart_assist")
            now_iso = dt_util.now().isoformat()
            alarm.setdefault("created_at", now_iso)
            alarm.setdefault("updated_at", now_iso)
            alarm.setdefault("scheduled_for", now_iso)
            alarm.setdefault("next_scheduled_for", alarm.get("scheduled_for", now_iso))
            recurrence_raw = alarm.get("recurrence") if isinstance(alarm.get("recurrence"), dict) else None
            normalized_recurrence = self._normalize_recurrence(
                recurrence_raw,
                self._parse_datetime(str(alarm.get("scheduled_for") or now_iso)),
            )
            alarm["recurrence"] = normalized_recurrence
            alarm.setdefault("active", True)
            alarm.setdefault("status", "active")
            alarm.setdefault("dismissed", False)
            alarm.setdefault("fired", False)
            alarm.setdefault("snoozed_until", None)
            alarm.setdefault("last_fired_at", None)
            alarm.setdefault("fire_count", 0)
            managed = alarm.get("managed_automation")
            if not isinstance(managed, dict):
                managed = {}
            merged_managed = _managed_defaults()
            merged_managed.update({
                "enabled": bool(managed.get("enabled", merged_managed["enabled"])),
                "automation_entity_id": managed.get("automation_entity_id", merged_managed["automation_entity_id"]),
                "ownership_verified": bool(managed.get("ownership_verified", merged_managed["ownership_verified"])),
                "sync_state": managed.get("sync_state", merged_managed["sync_state"]),
                "last_sync_at": managed.get("last_sync_at", merged_managed["last_sync_at"]),
                "last_sync_error": managed.get("last_sync_error", merged_managed["last_sync_error"]),
            })
            alarm["managed_automation"] = merged_managed
            direct_execution = alarm.get("direct_execution")
            if not isinstance(direct_execution, dict):
                direct_execution = {}
            merged_direct = _direct_defaults()
            merged_direct.update({
                "last_executed_at": direct_execution.get("last_executed_at", merged_direct["last_executed_at"]),
                "last_state": direct_execution.get("last_state", merged_direct["last_state"]),
                "last_error": direct_execution.get("last_error", merged_direct["last_error"]),
                "last_backend_results": direct_execution.get("last_backend_results", merged_direct["last_backend_results"]),
                "last_fire_marker": direct_execution.get("last_fire_marker", merged_direct["last_fire_marker"]),
            })
            if not isinstance(merged_direct.get("last_backend_results"), dict):
                merged_direct["last_backend_results"] = {}
            alarm["direct_execution"] = merged_direct
            delivery = alarm.get("delivery")
            if not isinstance(delivery, dict):
                delivery = {}
            merged_delivery = _delivery_defaults()
            merged_delivery.update({
                "source_device_id": str(delivery.get("source_device_id") or "").strip() or None,
                "source_satellite_id": str(delivery.get("source_satellite_id") or "").strip() or None,
                "tts_targets": self._normalize_tts_targets(delivery.get("tts_targets")),
                "wake_text": self._normalize_wake_text_options(delivery.get("wake_text")),
            })
            alarm["delivery"] = merged_delivery
            display_id = alarm.get("display_id")
            if not isinstance(display_id, str) or not display_id.strip():
                display_id = self._generate_display_id(
                    label=str(alarm.get("label") or "Alarm"),
                    when_iso=str(alarm.get("scheduled_for") or now_iso),
                    existing_ids=used_display_ids,
                )
            else:
                display_id = self._ensure_unique_display_id(display_id, used_display_ids)
            alarm["display_id"] = display_id
            used_display_ids.add(display_id)
            normalized.append(alarm)

        self._data = {
            "version": PERSISTENT_ALARM_STORAGE_VERSION,
            "alarms": normalized,
        }
        self._dirty = False

    def update_alarm(
        self,
        alarm_id: str,
        updates: dict[str, Any],
        *,
        reactivate: bool = False,
    ) -> tuple[dict[str, Any] | None, str]:
        """Update editable alarm fields with lifecycle guards."""
        alarm = self._find_alarm(alarm_id)
        if alarm is None:
            return None, "Alarm not found"

        status = str(alarm.get("status") or "")
        active = bool(alarm.get("active", False))
        if not active and status in {"fired", "dismissed"} and not reactivate:
            return None, "Alarm can only be edited when reactivated"

        changed = False

        if "label" in updates:
            label_value = str(updates.get("label") or "Alarm").strip() or "Alarm"
            if label_value != alarm.get("label"):
                alarm["label"] = label_value
                changed = True

        if "message" in updates:
            message_value = str(updates.get("message") or "").strip()
            if message_value != alarm.get("message"):
                alarm["message"] = message_value
                changed = True

        if "scheduled_for" in updates:
            when_iso = str(updates.get("scheduled_for") or "")
            trigger_dt = self._parse_datetime(when_iso)
            if trigger_dt is None:
                return None, "Invalid datetime format"
            if trigger_dt <= dt_util.now():
                return None, "Alarm time must be in the future"
            alarm["scheduled_for"] = trigger_dt.isoformat()
            alarm["next_scheduled_for"] = trigger_dt.isoformat()
            alarm["snoozed_until"] = None
            changed = True

        if "recurrence" in updates:
            recurrence_payload = updates.get("recurrence")
            normalized_recurrence = self._normalize_recurrence(
                recurrence_payload if isinstance(recurrence_payload, dict) else None,
                self._parse_datetime(str(alarm.get("scheduled_for") or "")),
            )
            if recurrence_payload is not None and normalized_recurrence is None:
                return None, "Invalid recurrence configuration"
            if recurrence_payload is None:
                normalized_recurrence = None
            if normalized_recurrence != alarm.get("recurrence"):
                alarm["recurrence"] = normalized_recurrence
                changed = True

        if "delivery" in updates:
            delivery_updates = updates.get("delivery")
            if isinstance(delivery_updates, dict):
                current_delivery = alarm.get("delivery")
                if not isinstance(current_delivery, dict):
                    current_delivery = _delivery_defaults()

                next_delivery = dict(current_delivery)
                if "tts_targets" in delivery_updates:
                    next_delivery["tts_targets"] = self._normalize_tts_targets(delivery_updates.get("tts_targets"))
                if "source_device_id" in delivery_updates:
                    next_delivery["source_device_id"] = str(delivery_updates.get("source_device_id") or "").strip() or None
                if "source_satellite_id" in delivery_updates:
                    next_delivery["source_satellite_id"] = str(delivery_updates.get("source_satellite_id") or "").strip() or None
                if "wake_text" in delivery_updates:
                    next_delivery["wake_text"] = self._normalize_wake_text_options(delivery_updates.get("wake_text"))

                if next_delivery != current_delivery:
                    alarm["delivery"] = next_delivery
                    changed = True

        if reactivate:
            alarm["active"] = True
            alarm["dismissed"] = False
            alarm["fired"] = False
            alarm["status"] = "active"
            alarm["snoozed_until"] = None
            changed = True

        if not changed:
            return dict(alarm), "No changes"

        alarm["updated_at"] = dt_util.now().isoformat()
        self._dirty = True
        return dict(alarm), "Alarm updated"

    def export_state(self) -> dict[str, Any]:
        """Return a copy of persisted state (for diagnostics/tests)."""
        return {
            "version": self._data.get("version", PERSISTENT_ALARM_STORAGE_VERSION),
            "alarms": [dict(alarm) for alarm in self._data.get("alarms", [])],
        }

    def mark_managed_sync_state(
        self,
        alarm_id: str,
        sync_state: str,
        last_sync_error: str | None = None,
        at_iso: str | None = None,
    ) -> bool:
        """Update managed automation sync state metadata for alarm."""
        alarm = self._find_alarm(alarm_id)
        if alarm is None:
            return False

        managed = alarm.get("managed_automation")
        if not isinstance(managed, dict):
            managed = _managed_defaults()
            alarm["managed_automation"] = managed

        managed["sync_state"] = sync_state
        managed["last_sync_error"] = last_sync_error
        managed["last_sync_at"] = at_iso or dt_util.now().isoformat()
        alarm["updated_at"] = dt_util.now().isoformat()
        self._dirty = True
        return True

    def set_managed_linkage(
        self,
        alarm_id: str,
        enabled: bool,
        automation_entity_id: str | None,
        ownership_verified: bool,
    ) -> bool:
        """Set managed automation linkage metadata for alarm."""
        alarm = self._find_alarm(alarm_id)
        if alarm is None:
            return False

        managed = alarm.get("managed_automation")
        if not isinstance(managed, dict):
            managed = _managed_defaults()
            alarm["managed_automation"] = managed

        managed["enabled"] = bool(enabled)
        managed["automation_entity_id"] = automation_entity_id
        managed["ownership_verified"] = bool(ownership_verified)
        alarm["updated_at"] = dt_util.now().isoformat()
        self._dirty = True
        return True

    def clear_managed_linkage_if_unverified(self, alarm_id: str) -> bool:
        """Clear managed linkage for alarm only when ownership is not verified."""
        alarm = self._find_alarm(alarm_id)
        if alarm is None:
            return False

        managed = alarm.get("managed_automation")
        if not isinstance(managed, dict):
            return False

        if managed.get("ownership_verified") is True:
            return False

        changed = False
        if managed.get("automation_entity_id") is not None:
            managed["automation_entity_id"] = None
            changed = True
        if managed.get("enabled"):
            managed["enabled"] = False
            changed = True
        if changed:
            alarm["updated_at"] = dt_util.now().isoformat()
            self._dirty = True
        return changed

    def has_direct_execution_marker(self, alarm_id: str, fire_marker: str) -> bool:
        """Return whether alarm already processed given direct fire marker."""
        alarm = self._find_alarm(alarm_id)
        if alarm is None:
            return False

        direct = alarm.get("direct_execution")
        if not isinstance(direct, dict):
            return False
        return str(direct.get("last_fire_marker") or "") == str(fire_marker or "")

    def mark_direct_execution_result(
        self,
        alarm_id: str,
        *,
        fire_marker: str | None,
        state: str,
        error: str | None = None,
        backend_results: dict[str, Any] | None = None,
        at_iso: str | None = None,
    ) -> bool:
        """Update direct execution metadata for an alarm."""
        alarm = self._find_alarm(alarm_id)
        if alarm is None:
            return False

        direct = alarm.get("direct_execution")
        if not isinstance(direct, dict):
            direct = _direct_defaults()
            alarm["direct_execution"] = direct

        direct["last_executed_at"] = at_iso or dt_util.now().isoformat()
        direct["last_state"] = state
        direct["last_error"] = error
        direct["last_backend_results"] = dict(backend_results or {})
        direct["last_fire_marker"] = fire_marker

        alarm["updated_at"] = dt_util.now().isoformat()
        self._dirty = True
        return True

    def _find_alarm(self, alarm_id: str) -> dict[str, Any] | None:
        """Find mutable alarm by machine id or display id."""
        target = self._normalize_lookup_value(alarm_id)
        if not target:
            return None

        for alarm in self._data.get("alarms", []):
            if self._normalize_lookup_value(str(alarm.get("id") or "")) == target:
                return alarm
            if self._normalize_lookup_value(str(alarm.get("display_id") or "")) == target:
                return alarm
        return None

    def _normalize_lookup_value(self, value: str) -> str:
        """Normalize alarm lookup values for tolerant matching."""
        normalized = (value or "").strip().casefold()
        normalized = normalized.replace("_", "-")
        normalized = re.sub(r"\s+", "-", normalized)
        normalized = re.sub(r"[^a-z0-9\-]", "", normalized)
        normalized = re.sub(r"-+", "-", normalized)
        return normalized.strip("-")

    def _generate_display_id(
        self,
        label: str,
        when_iso: str,
        existing_ids: set[str] | None = None,
    ) -> str:
        """Generate a stable human-readable unique display id."""
        used_ids = existing_ids if existing_ids is not None else {
            str(alarm.get("display_id"))
            for alarm in self._data.get("alarms", [])
            if isinstance(alarm.get("display_id"), str)
        }

        label_slug = self._slugify(label) or "alarm"
        trigger_dt = self._parse_datetime(when_iso)
        hhmm = trigger_dt.strftime("%H%M") if trigger_dt else "0000"
        base = f"{label_slug}-{hhmm}"

        for _ in range(10):
            suffix = uuid.uuid4().hex[:4]
            candidate = f"{base}-{suffix}"
            if candidate not in used_ids:
                if existing_ids is not None:
                    existing_ids.add(candidate)
                return candidate

        fallback = f"{base}-{uuid.uuid4().hex[:6]}"
        if existing_ids is not None:
            existing_ids.add(fallback)
        return fallback

    def _ensure_unique_display_id(self, display_id: str, used_ids: set[str]) -> str:
        """Return unique display id preserving provided id where possible."""
        normalized = self._normalize_lookup_value(display_id)
        if not normalized:
            return self._generate_display_id("alarm", dt_util.now().isoformat(), used_ids)
        if normalized not in used_ids:
            used_ids.add(normalized)
            return normalized

        for _ in range(10):
            candidate = f"{normalized}-{uuid.uuid4().hex[:3]}"
            if candidate not in used_ids:
                used_ids.add(candidate)
                return candidate

        fallback = f"{normalized}-{uuid.uuid4().hex[:6]}"
        used_ids.add(fallback)
        return fallback

    def _slugify(self, value: str) -> str:
        """Convert text to lowercase ASCII slug."""
        raw = unicodedata.normalize("NFKD", value or "")
        ascii_value = raw.encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
        slug = re.sub(r"-+", "-", slug)
        return slug

    def _next_trigger_datetime(self, alarm: dict[str, Any]) -> datetime | None:
        """Resolve next trigger datetime for alarm."""
        trigger_value = alarm.get("snoozed_until") or alarm.get("scheduled_for")
        if not isinstance(trigger_value, str):
            return None
        return self._parse_datetime(trigger_value)

    def _normalize_recurrence(
        self,
        recurrence: dict[str, Any] | None,
        scheduled_for: datetime | None,
    ) -> dict[str, Any] | None:
        """Normalize recurrence payload into canonical representation."""
        if recurrence is None:
            return None

        frequency = str(recurrence.get("frequency") or "").strip().lower()
        if frequency not in {"daily", "weekly"}:
            return None

        interval_raw = recurrence.get("interval", 1)
        try:
            interval = int(interval_raw)
        except (TypeError, ValueError):
            return None
        if interval <= 0:
            return None

        timezone = str(recurrence.get("timezone") or dt_util.DEFAULT_TIME_ZONE)
        normalized: dict[str, Any] = {
            "frequency": frequency,
            "interval": interval,
            "timezone": timezone,
        }

        if frequency == "weekly":
            weekdays = recurrence.get("byweekday")
            normalized_weekdays = self._normalize_weekdays(weekdays, scheduled_for)
            if not normalized_weekdays:
                return None
            normalized["byweekday"] = normalized_weekdays

        return normalized

    def _normalize_weekdays(
        self,
        weekdays: Any,
        scheduled_for: datetime | None,
    ) -> list[int]:
        """Normalize weekday values into sorted unique list of ints (0=Mon)."""
        if weekdays is None:
            if scheduled_for is None:
                return []
            return [int(scheduled_for.weekday())]

        values = weekdays if isinstance(weekdays, list) else [weekdays]
        result: set[int] = set()
        full_weekdays = {name.lower(): idx for idx, name in enumerate(calendar.day_name)}
        for item in values:
            if isinstance(item, int):
                weekday = item
            else:
                raw = str(item or "").strip().lower()
                if raw in full_weekdays:
                    weekday = full_weekdays[raw]
                elif raw in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
                    weekday = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(raw)
                else:
                    try:
                        weekday = int(raw)
                    except ValueError:
                        return []
            if weekday < 0 or weekday > 6:
                return []
            result.add(weekday)
        return sorted(result)

    def _normalize_tts_targets(self, targets: Any) -> list[str]:
        """Normalize TTS targets into unique ordered media_player entity ids."""
        if targets is None:
            return []

        values = targets if isinstance(targets, list) else [targets]
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            entity_id = str(value or "").strip().lower()
            if not entity_id or not entity_id.startswith("media_player."):
                continue
            if entity_id in seen:
                continue
            seen.add(entity_id)
            normalized.append(entity_id)
        return normalized

    def _normalize_wake_text_options(self, wake_text: Any) -> dict[str, bool]:
        """Normalize wake text options into canonical booleans."""
        defaults = _delivery_defaults()["wake_text"]
        if not isinstance(wake_text, dict):
            return dict(defaults)

        return {
            "dynamic": bool(wake_text.get("dynamic", defaults["dynamic"])),
            "include_weather": bool(wake_text.get("include_weather", defaults["include_weather"])),
            "include_news": bool(wake_text.get("include_news", defaults["include_news"])),
        }

    def _compute_next_occurrence(
        self,
        scheduled_for: datetime | None,
        recurrence: dict[str, Any],
        reference: datetime,
    ) -> datetime | None:
        """Compute next occurrence after reference for a recurring alarm."""
        if scheduled_for is None:
            return None

        frequency = str(recurrence.get("frequency") or "")
        interval = int(recurrence.get("interval") or 1)

        if frequency == "daily":
            next_dt = scheduled_for
            for _ in range(2048):
                next_dt = next_dt + timedelta(days=interval)
                if next_dt > reference:
                    return next_dt
            return None

        if frequency == "weekly":
            weekdays = recurrence.get("byweekday") if isinstance(recurrence.get("byweekday"), list) else []
            weekday_set = {int(day) for day in weekdays if isinstance(day, int)}
            if not weekday_set:
                weekday_set = {int(scheduled_for.weekday())}

            candidate = scheduled_for + timedelta(days=1)
            base_week_start = scheduled_for - timedelta(days=scheduled_for.weekday())
            for _ in range(4096):
                candidate_week_start = candidate - timedelta(days=candidate.weekday())
                weeks_since_base = int((candidate_week_start - base_week_start).days // 7)
                if weeks_since_base >= 0 and weeks_since_base % interval == 0:
                    if candidate.weekday() in weekday_set and candidate > reference:
                        return candidate
                candidate = candidate + timedelta(days=1)
            return None

        return None

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
