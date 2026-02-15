"""Managed alarm automation synchronization service.

Keeps Smart Assist-owned automation artifacts in sync with persistent alarm records,
without mutating non-owned user automations.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    MANAGED_ALARM_ALIAS_PREFIX,
    MANAGED_ALARM_ERROR_INVALID_PAYLOAD,
    MANAGED_ALARM_ERROR_NOT_FOUND,
    MANAGED_ALARM_ERROR_OWNERSHIP_MISMATCH,
    MANAGED_ALARM_ERROR_SERVICE_FAILED,
    MANAGED_ALARM_MANAGED_VERSION,
    MANAGED_ALARM_MARKER_ALARM_ID_KEY,
    MANAGED_ALARM_MARKER_ENTRY_ID_KEY,
    MANAGED_ALARM_MARKER_OWNER_KEY,
    MANAGED_ALARM_MARKER_PREFIX,
    MANAGED_ALARM_MARKER_VERSION_KEY,
    MANAGED_ALARM_OWNER,
    MANAGED_ALARM_SYNC_FAILED,
    MANAGED_ALARM_SYNC_SKIPPED,
    MANAGED_ALARM_SYNC_SYNCED,
)
from .persistent_alarms import PersistentAlarmManager

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ManagedAlarmSyncResult:
    """Result of a managed alarm sync operation."""

    success: bool
    category: str | None = None
    automation_entity_id: str | None = None
    ownership_verified: bool = False
    message: str = ""


def _slug(value: str) -> str:
    """Return slug-safe chunk for entity ids."""
    slug = re.sub(r"[^a-z0-9_]", "_", (value or "").strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "alarm"


class ManagedAlarmAutomationService:
    """Synchronize Smart Assist managed alarm automations."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        alarm_manager: PersistentAlarmManager,
        auto_repair: bool = True,
    ) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._alarm_manager = alarm_manager
        self._auto_repair = bool(auto_repair)

    def _automation_entity_id_for(self, alarm: dict[str, Any]) -> str:
        alarm_id = _slug(str(alarm.get("id") or "alarm"))[:40]
        entry_chunk = _slug(self._entry_id)[:12]
        return f"automation.smart_assist_alarm_{entry_chunk}_{alarm_id}"

    def _marker(self, alarm: dict[str, Any]) -> dict[str, Any]:
        return {
            MANAGED_ALARM_MARKER_OWNER_KEY: MANAGED_ALARM_OWNER,
            MANAGED_ALARM_MARKER_ENTRY_ID_KEY: self._entry_id,
            MANAGED_ALARM_MARKER_ALARM_ID_KEY: str(alarm.get("id") or ""),
            MANAGED_ALARM_MARKER_VERSION_KEY: MANAGED_ALARM_MANAGED_VERSION,
        }

    def _description_with_marker(self, alarm: dict[str, Any]) -> str:
        marker_json = json.dumps(self._marker(alarm), separators=(",", ":"), sort_keys=True)
        return (
            "Managed by Smart Assist. "
            f"{MANAGED_ALARM_MARKER_PREFIX}{marker_json}"
        )

    def _desired_payload(self, alarm: dict[str, Any], entity_id: str) -> dict[str, Any]:
        label = str(alarm.get("label") or "Alarm")
        message = str(alarm.get("message") or "").strip()
        trigger_at = alarm.get("snoozed_until") or alarm.get("scheduled_for")

        if not isinstance(trigger_at, str) or not trigger_at:
            raise ValueError("missing trigger datetime")

        actions = [
            {
                "event": "smart_assist_alarm_fired",
                "event_data": {
                    "entry_id": self._entry_id,
                    "alarm_id": alarm.get("id"),
                    "display_id": alarm.get("display_id"),
                    "label": alarm.get("label"),
                    "message": alarm.get("message"),
                    "source": "managed_automation",
                },
            }
        ]

        if message:
            actions.append(
                {
                    "service": "persistent_notification.create",
                    "data": {
                        "title": f"Smart Assist Alarm: {label}",
                        "message": message,
                        "notification_id": f"smart_assist_alarm_{alarm.get('id')}",
                    },
                }
            )

        return {
            "entity_id": entity_id,
            "alias": f"{MANAGED_ALARM_ALIAS_PREFIX} {label}",
            "description": self._description_with_marker(alarm),
            "mode": "single",
            "trigger": [
                {
                    "platform": "time",
                    "at": trigger_at,
                }
            ],
            "condition": [],
            "action": actions,
        }

    def _extract_marker(self, description: str | None) -> dict[str, Any] | None:
        if not description or MANAGED_ALARM_MARKER_PREFIX not in description:
            return None
        raw = description.split(MANAGED_ALARM_MARKER_PREFIX, 1)[1].strip()
        try:
            marker = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return marker if isinstance(marker, dict) else None

    def _verify_ownership(self, entity_id: str, alarm_id: str) -> bool:
        state = self._hass.states.get(entity_id)
        if state is None:
            return False

        alias = str(state.attributes.get("friendly_name") or "")
        if not alias.startswith(MANAGED_ALARM_ALIAS_PREFIX):
            return False

        marker = self._extract_marker(state.attributes.get("description"))
        if not marker:
            return False

        return (
            marker.get(MANAGED_ALARM_MARKER_OWNER_KEY) == MANAGED_ALARM_OWNER
            and marker.get(MANAGED_ALARM_MARKER_ENTRY_ID_KEY) == self._entry_id
            and marker.get(MANAGED_ALARM_MARKER_ALARM_ID_KEY) == alarm_id
        )

    async def _async_call_first(self, service_names: list[str], payload: dict[str, Any]) -> bool:
        for service_name in service_names:
            if not self._hass.services.has_service("automation", service_name):
                continue
            await self._hass.services.async_call(
                "automation",
                service_name,
                payload,
                blocking=True,
            )
            return True
        return False

    async def _upsert(self, payload: dict[str, Any]) -> bool:
        create_payload = dict(payload)
        update_payload = dict(payload)
        return (
            await self._async_call_first(["upsert", "create", "edit"], create_payload)
            or await self._async_call_first(["update", "edit"], update_payload)
        )

    async def _remove(self, entity_id: str) -> bool:
        payload = {"entity_id": entity_id}
        return await self._async_call_first(["delete", "remove"], payload)

    async def async_reconcile_alarm(self, alarm: dict[str, Any]) -> ManagedAlarmSyncResult:
        """Reconcile one alarm to managed automation state."""
        alarm_id = str(alarm.get("id") or "")
        if not alarm_id:
            return ManagedAlarmSyncResult(False, MANAGED_ALARM_ERROR_INVALID_PAYLOAD, message="Missing alarm id")

        managed = alarm.get("managed_automation")
        if not isinstance(managed, dict):
            managed = {}

        entity_id = str(managed.get("automation_entity_id") or self._automation_entity_id_for(alarm))
        should_exist = bool(alarm.get("status") in ("active", "snoozed") and not alarm.get("dismissed"))
        now_iso = dt_util.now().isoformat()

        if should_exist:
            owned = self._verify_ownership(entity_id, alarm_id)
            exists = self._hass.states.get(entity_id) is not None

            if exists and not owned:
                self._alarm_manager.set_managed_linkage(alarm_id, True, entity_id, False)
                self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_FAILED, MANAGED_ALARM_ERROR_OWNERSHIP_MISMATCH, now_iso)
                self._alarm_manager.clear_managed_linkage_if_unverified(alarm_id)
                return ManagedAlarmSyncResult(
                    success=False,
                    category=MANAGED_ALARM_ERROR_OWNERSHIP_MISMATCH,
                    automation_entity_id=entity_id,
                    ownership_verified=False,
                    message="Ownership mismatch",
                )

            if exists and owned:
                self._alarm_manager.set_managed_linkage(alarm_id, True, entity_id, True)
                self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_SYNCED, None, now_iso)
                return ManagedAlarmSyncResult(
                    success=True,
                    automation_entity_id=entity_id,
                    ownership_verified=True,
                    message="Managed automation verified",
                )

            if not self._auto_repair:
                self._alarm_manager.set_managed_linkage(alarm_id, True, entity_id, False)
                self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_FAILED, MANAGED_ALARM_ERROR_NOT_FOUND, now_iso)
                return ManagedAlarmSyncResult(
                    success=False,
                    category=MANAGED_ALARM_ERROR_NOT_FOUND,
                    automation_entity_id=entity_id,
                    ownership_verified=False,
                    message="Managed automation missing",
                )

            try:
                payload = self._desired_payload(alarm, entity_id)
            except ValueError:
                self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_FAILED, MANAGED_ALARM_ERROR_INVALID_PAYLOAD, now_iso)
                return ManagedAlarmSyncResult(
                    success=False,
                    category=MANAGED_ALARM_ERROR_INVALID_PAYLOAD,
                    automation_entity_id=entity_id,
                    ownership_verified=False,
                    message="Invalid automation payload",
                )

            try:
                changed = await self._upsert(payload)
            except Exception as err:
                _LOGGER.warning("Managed alarm upsert failed for %s: %s", alarm_id, err)
                self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_FAILED, MANAGED_ALARM_ERROR_SERVICE_FAILED, now_iso)
                return ManagedAlarmSyncResult(
                    success=False,
                    category=MANAGED_ALARM_ERROR_SERVICE_FAILED,
                    automation_entity_id=entity_id,
                    ownership_verified=False,
                    message=str(err),
                )

            if not changed:
                self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_FAILED, MANAGED_ALARM_ERROR_SERVICE_FAILED, now_iso)
                return ManagedAlarmSyncResult(
                    success=False,
                    category=MANAGED_ALARM_ERROR_SERVICE_FAILED,
                    automation_entity_id=entity_id,
                    ownership_verified=False,
                    message="No supported automation upsert service",
                )

            self._alarm_manager.set_managed_linkage(alarm_id, True, entity_id, True)
            self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_SYNCED, None, now_iso)
            return ManagedAlarmSyncResult(
                success=True,
                automation_entity_id=entity_id,
                ownership_verified=True,
                message="Managed automation upserted",
            )

        managed_entity = str(managed.get("automation_entity_id") or entity_id)
        if self._hass.states.get(managed_entity) is None:
            self._alarm_manager.set_managed_linkage(alarm_id, False, None, False)
            self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_SKIPPED, None, now_iso)
            return ManagedAlarmSyncResult(
                success=True,
                category=MANAGED_ALARM_SYNC_SKIPPED,
                automation_entity_id=None,
                ownership_verified=False,
                message="No managed automation to remove",
            )

        if not self._verify_ownership(managed_entity, alarm_id):
            self._alarm_manager.set_managed_linkage(alarm_id, False, managed_entity, False)
            self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_FAILED, MANAGED_ALARM_ERROR_OWNERSHIP_MISMATCH, now_iso)
            self._alarm_manager.clear_managed_linkage_if_unverified(alarm_id)
            return ManagedAlarmSyncResult(
                success=False,
                category=MANAGED_ALARM_ERROR_OWNERSHIP_MISMATCH,
                automation_entity_id=managed_entity,
                ownership_verified=False,
                message="Ownership mismatch",
            )

        try:
            removed = await self._remove(managed_entity)
        except Exception as err:
            _LOGGER.warning("Managed alarm remove failed for %s: %s", alarm_id, err)
            self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_FAILED, MANAGED_ALARM_ERROR_SERVICE_FAILED, now_iso)
            return ManagedAlarmSyncResult(
                success=False,
                category=MANAGED_ALARM_ERROR_SERVICE_FAILED,
                automation_entity_id=managed_entity,
                ownership_verified=True,
                message=str(err),
            )

        if not removed:
            self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_FAILED, MANAGED_ALARM_ERROR_SERVICE_FAILED, now_iso)
            return ManagedAlarmSyncResult(
                success=False,
                category=MANAGED_ALARM_ERROR_SERVICE_FAILED,
                automation_entity_id=managed_entity,
                ownership_verified=True,
                message="No supported automation remove service",
            )

        self._alarm_manager.set_managed_linkage(alarm_id, False, None, False)
        self._alarm_manager.mark_managed_sync_state(alarm_id, MANAGED_ALARM_SYNC_SYNCED, None, now_iso)
        return ManagedAlarmSyncResult(
            success=True,
            automation_entity_id=None,
            ownership_verified=False,
            message="Managed automation removed",
        )

    async def async_reconcile_all(self) -> list[ManagedAlarmSyncResult]:
        """Reconcile all known alarms."""
        results: list[ManagedAlarmSyncResult] = []
        alarms = self._alarm_manager.list_alarms(active_only=False)
        for alarm in alarms:
            result = await self.async_reconcile_alarm(alarm)
            results.append(result)
        return results
