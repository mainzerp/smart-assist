"""Direct alarm execution service for fired persistent alarms."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_DIRECT_ALARM_BACKEND_TIMEOUT_SECONDS,
    CONF_DIRECT_ALARM_ENABLE_NOTIFICATION,
    CONF_DIRECT_ALARM_ENABLE_NOTIFY,
    CONF_DIRECT_ALARM_ENABLE_SCRIPT,
    CONF_DIRECT_ALARM_ENABLE_TTS,
    CONF_DIRECT_ALARM_NOTIFY_SERVICE,
    CONF_DIRECT_ALARM_SCRIPT_ENTITY_ID,
    CONF_DIRECT_ALARM_TTS_SERVICE,
    CONF_DIRECT_ALARM_TTS_TARGET,
    DEFAULT_DIRECT_ALARM_BACKEND_TIMEOUT_SECONDS,
    DEFAULT_DIRECT_ALARM_ENABLE_NOTIFICATION,
    DEFAULT_DIRECT_ALARM_ENABLE_NOTIFY,
    DEFAULT_DIRECT_ALARM_ENABLE_SCRIPT,
    DEFAULT_DIRECT_ALARM_ENABLE_TTS,
    DEFAULT_DIRECT_ALARM_NOTIFY_SERVICE,
    DEFAULT_DIRECT_ALARM_SCRIPT_ENTITY_ID,
    DEFAULT_DIRECT_ALARM_TTS_SERVICE,
    DEFAULT_DIRECT_ALARM_TTS_TARGET,
    DIRECT_ALARM_BACKEND_NOTIFICATION,
    DIRECT_ALARM_BACKEND_NOTIFY,
    DIRECT_ALARM_BACKEND_SCRIPT,
    DIRECT_ALARM_BACKEND_TTS,
    DIRECT_ALARM_ERROR_SERVICE_FAILED,
    DIRECT_ALARM_ERROR_TIMEOUT,
    DIRECT_ALARM_ERROR_UNSUPPORTED,
    DIRECT_ALARM_ERROR_VALIDATION,
    DIRECT_ALARM_STATE_FAILED,
    DIRECT_ALARM_STATE_OK,
    DIRECT_ALARM_STATE_PARTIAL,
    DIRECT_ALARM_STATE_SKIPPED,
    DOMAIN,
)
from .persistent_alarms import PersistentAlarmManager

_LOGGER = logging.getLogger(__name__)


class DirectAlarmEngine:
    """Execute direct alarm actions when alarms are fired."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        alarm_manager: PersistentAlarmManager,
        config: dict[str, Any],
    ) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._alarm_manager = alarm_manager
        self._config = config

    async def execute_for_fired_alarm(self, alarm: dict[str, Any]) -> dict[str, Any]:
        """Execute all enabled direct backends for one fired alarm.

        This method is non-throwing and always returns a structured result payload.
        """
        alarm_id = str(alarm.get("id") or "")
        fire_marker = self._build_fire_marker(alarm)
        now_iso = dt_util.now().isoformat()

        if not alarm_id or not fire_marker:
            return {
                "executed_at": now_iso,
                "fire_marker": fire_marker,
                "state": DIRECT_ALARM_STATE_SKIPPED,
                "error": DIRECT_ALARM_ERROR_VALIDATION,
                "backend_results": {},
            }

        if self._alarm_manager.has_direct_execution_marker(alarm_id, fire_marker):
            return {
                "executed_at": now_iso,
                "fire_marker": fire_marker,
                "state": DIRECT_ALARM_STATE_SKIPPED,
                "error": None,
                "backend_results": {
                    "idempotency": {
                        "success": True,
                        "state": DIRECT_ALARM_STATE_SKIPPED,
                        "category": None,
                        "message": "already_executed_for_fire_marker",
                    }
                },
            }

        backend_results: dict[str, Any] = {}
        for backend in self._enabled_backends():
            backend_results[backend] = await self._execute_backend(backend, alarm)

        state = self._derive_state(backend_results)
        first_error = self._derive_error(backend_results)

        self._alarm_manager.mark_direct_execution_result(
            alarm_id,
            fire_marker=fire_marker,
            state=state,
            error=first_error,
            backend_results=backend_results,
            at_iso=now_iso,
        )

        return {
            "executed_at": now_iso,
            "fire_marker": fire_marker,
            "state": state,
            "error": first_error,
            "backend_results": backend_results,
        }

    def _enabled_backends(self) -> list[str]:
        backends: list[str] = []
        if bool(self._config.get(CONF_DIRECT_ALARM_ENABLE_NOTIFICATION, DEFAULT_DIRECT_ALARM_ENABLE_NOTIFICATION)):
            backends.append(DIRECT_ALARM_BACKEND_NOTIFICATION)
        if bool(self._config.get(CONF_DIRECT_ALARM_ENABLE_NOTIFY, DEFAULT_DIRECT_ALARM_ENABLE_NOTIFY)):
            backends.append(DIRECT_ALARM_BACKEND_NOTIFY)
        if bool(self._config.get(CONF_DIRECT_ALARM_ENABLE_TTS, DEFAULT_DIRECT_ALARM_ENABLE_TTS)):
            backends.append(DIRECT_ALARM_BACKEND_TTS)
        if bool(self._config.get(CONF_DIRECT_ALARM_ENABLE_SCRIPT, DEFAULT_DIRECT_ALARM_ENABLE_SCRIPT)):
            backends.append(DIRECT_ALARM_BACKEND_SCRIPT)
        return backends

    async def _execute_backend(self, backend: str, alarm: dict[str, Any]) -> dict[str, Any]:
        try:
            if backend == DIRECT_ALARM_BACKEND_NOTIFICATION:
                return await self._run_notification_backend(alarm)
            if backend == DIRECT_ALARM_BACKEND_NOTIFY:
                return await self._run_notify_backend(alarm)
            if backend == DIRECT_ALARM_BACKEND_TTS:
                return await self._run_tts_backend(alarm)
            if backend == DIRECT_ALARM_BACKEND_SCRIPT:
                return await self._run_script_backend(alarm)
            return self._failure_result(DIRECT_ALARM_ERROR_UNSUPPORTED, "unknown_backend")
        except asyncio.TimeoutError:
            return self._failure_result(DIRECT_ALARM_ERROR_TIMEOUT, "backend_timeout")
        except Exception as err:  # pragma: no cover - defensive isolation
            _LOGGER.warning("Direct alarm backend '%s' failed for %s: %s", backend, alarm.get("id"), err)
            return self._failure_result(DIRECT_ALARM_ERROR_SERVICE_FAILED, str(err))

    async def _run_notification_backend(self, alarm: dict[str, Any]) -> dict[str, Any]:
        try:
            from homeassistant.components.persistent_notification import async_create

            label = str(alarm.get("label") or "Alarm")
            message = str(alarm.get("message") or "").strip() or (
                f"Alarm '{label}' ({alarm.get('display_id', alarm.get('id'))}) fired at {alarm.get('last_fired_at', '')}."
            )
            async_create(
                self._hass,
                message,
                title=f"Smart Assist Alarm: {label}",
                notification_id=f"{DOMAIN}_alarm_{alarm.get('id')}",
            )
            return self._ok_result("persistent_notification.created")
        except Exception as err:
            return self._failure_result(DIRECT_ALARM_ERROR_SERVICE_FAILED, str(err))

    async def _run_notify_backend(self, alarm: dict[str, Any]) -> dict[str, Any]:
        service_name = str(
            self._config.get(CONF_DIRECT_ALARM_NOTIFY_SERVICE, DEFAULT_DIRECT_ALARM_NOTIFY_SERVICE)
        )
        domain, service, valid = self._split_service(service_name)
        if not valid:
            return self._failure_result(DIRECT_ALARM_ERROR_VALIDATION, "invalid_notify_service")
        if not self._hass.services.has_service(domain, service):
            return self._failure_result(DIRECT_ALARM_ERROR_UNSUPPORTED, "notify_service_unavailable")

        label = str(alarm.get("label") or "Alarm")
        message = str(alarm.get("message") or "").strip() or f"Alarm '{label}' fired."
        payload = {
            "title": f"Smart Assist Alarm: {label}",
            "message": message,
        }
        await self._async_call_service(domain, service, payload)
        return self._ok_result(f"{domain}.{service}")

    async def _run_tts_backend(self, alarm: dict[str, Any]) -> dict[str, Any]:
        service_name = str(self._config.get(CONF_DIRECT_ALARM_TTS_SERVICE, DEFAULT_DIRECT_ALARM_TTS_SERVICE))
        domain, service, valid = self._split_service(service_name)
        if not valid:
            return self._failure_result(DIRECT_ALARM_ERROR_VALIDATION, "invalid_tts_service")
        if not self._hass.services.has_service(domain, service):
            return self._failure_result(DIRECT_ALARM_ERROR_UNSUPPORTED, "tts_service_unavailable")

        message = str(alarm.get("message") or "").strip() or f"Alarm {alarm.get('label', 'Alarm')} fired"
        targets = self._resolve_tts_targets(alarm)

        if not targets:
            payload: dict[str, Any] = {"message": message}
            await self._async_call_service(domain, service, payload)
            return self._ok_result(f"{domain}.{service}")

        successful = 0
        failed = 0
        for target in targets:
            payload = {
                "message": message,
                "entity_id": target,
            }
            try:
                await self._async_call_service(domain, service, payload)
                successful += 1
            except Exception as err:
                _LOGGER.warning("Direct alarm TTS target failed for %s on %s: %s", alarm.get("id"), target, err)
                failed += 1

        if successful == 0:
            return self._failure_result(DIRECT_ALARM_ERROR_SERVICE_FAILED, "tts_all_targets_failed")

        result = self._ok_result(f"{domain}.{service}")
        result["targets"] = targets
        result["target_success_count"] = successful
        result["target_failure_count"] = failed
        return result

    async def _run_script_backend(self, alarm: dict[str, Any]) -> dict[str, Any]:
        script_entity_id = str(
            self._config.get(CONF_DIRECT_ALARM_SCRIPT_ENTITY_ID, DEFAULT_DIRECT_ALARM_SCRIPT_ENTITY_ID) or ""
        ).strip()
        if not script_entity_id.startswith("script."):
            return self._failure_result(DIRECT_ALARM_ERROR_VALIDATION, "invalid_script_entity_id")

        await self._async_call_service(
            "script",
            "turn_on",
            {
                "entity_id": script_entity_id,
                "variables": {
                    "alarm_id": alarm.get("id"),
                    "display_id": alarm.get("display_id"),
                    "label": alarm.get("label"),
                    "message": alarm.get("message"),
                    "scheduled_for": alarm.get("scheduled_for"),
                    "fired_at": alarm.get("last_fired_at"),
                    "fire_count": alarm.get("fire_count"),
                },
            },
        )
        return self._ok_result("script.turn_on")

    async def _async_call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        timeout_seconds = float(
            self._config.get(
                CONF_DIRECT_ALARM_BACKEND_TIMEOUT_SECONDS,
                DEFAULT_DIRECT_ALARM_BACKEND_TIMEOUT_SECONDS,
            )
        )
        await asyncio.wait_for(
            self._hass.services.async_call(
                domain,
                service,
                data,
                blocking=True,
            ),
            timeout=timeout_seconds,
        )

    def _build_fire_marker(self, alarm: dict[str, Any]) -> str:
        alarm_id = str(alarm.get("id") or "")
        fired_at = str(alarm.get("last_fired_at") or "")
        fire_count = int(alarm.get("fire_count") or 0)
        if not alarm_id or not fired_at or fire_count <= 0:
            return ""
        return f"{alarm_id}:{fired_at}:{fire_count}"

    def _derive_state(self, backend_results: dict[str, Any]) -> str:
        if not backend_results:
            return DIRECT_ALARM_STATE_SKIPPED

        successful = sum(1 for value in backend_results.values() if value.get("success") is True)
        total = len(backend_results)
        if successful == 0:
            return DIRECT_ALARM_STATE_FAILED
        if successful < total:
            return DIRECT_ALARM_STATE_PARTIAL
        return DIRECT_ALARM_STATE_OK

    def _derive_error(self, backend_results: dict[str, Any]) -> str | None:
        for value in backend_results.values():
            if value.get("success") is False:
                category = value.get("category")
                if isinstance(category, str) and category:
                    return category
        return None

    def _split_service(self, service_name: str) -> tuple[str, str, bool]:
        raw = str(service_name or "").strip()
        if not raw or "." not in raw:
            return "", "", False
        domain, service = raw.split(".", 1)
        if not domain or not service:
            return "", "", False
        return domain, service, True

    def _resolve_tts_targets(self, alarm: dict[str, Any]) -> list[str]:
        """Resolve TTS targets with per-alarm override and source-aware defaults."""
        delivery = alarm.get("delivery") if isinstance(alarm.get("delivery"), dict) else {}
        explicit_targets = self._normalize_targets(delivery.get("tts_targets"))
        if explicit_targets:
            return explicit_targets

        source_device_id = str(delivery.get("source_device_id") or "").strip()
        source_satellite_id = str(delivery.get("source_satellite_id") or "").strip()

        by_device = self._resolve_media_players_by_device(source_device_id)
        if by_device:
            return by_device

        by_satellite = self._resolve_media_players_by_satellite(source_satellite_id)
        if by_satellite:
            return by_satellite

        configured = str(self._config.get(CONF_DIRECT_ALARM_TTS_TARGET, DEFAULT_DIRECT_ALARM_TTS_TARGET) or "")
        return self._normalize_targets(configured)

    def _normalize_targets(self, targets: Any) -> list[str]:
        """Normalize targets from list or comma-separated string."""
        if targets is None:
            return []
        if isinstance(targets, list):
            raw_values = [str(item or "") for item in targets]
        else:
            raw_values = str(targets).split(",")

        result: list[str] = []
        seen: set[str] = set()
        for value in raw_values:
            entity_id = value.strip().lower()
            if not entity_id or not entity_id.startswith("media_player."):
                continue
            if entity_id in seen:
                continue
            seen.add(entity_id)
            result.append(entity_id)
        return result

    def _resolve_media_players_by_device(self, device_id: str) -> list[str]:
        """Resolve media_player entity ids linked to the source device."""
        if not device_id:
            return []
        try:
            entity_registry = er.async_get(self._hass)
            entries = er.async_entries_for_device(entity_registry, device_id)
        except Exception:
            return []

        players = [
            entry.entity_id
            for entry in entries
            if isinstance(entry.entity_id, str)
            and entry.entity_id.startswith("media_player.")
            and self._hass.states.get(entry.entity_id) is not None
        ]
        return self._normalize_targets(players)

    def _resolve_media_players_by_satellite(self, satellite_id: str) -> list[str]:
        """Best-effort match from satellite id to media_player entities."""
        if not satellite_id:
            return []

        sat_name = satellite_id.lower().replace("assist_satellite.", "")
        sat_parts = sat_name.replace("satellite_", "").replace("_assist_satellit", "").split("_")
        candidates: list[str] = []

        for state in self._hass.states.async_all("media_player"):
            player_id = state.entity_id.lower()
            for part in sat_parts:
                if len(part) >= 3 and part in player_id:
                    candidates.append(state.entity_id)
                    break

        return self._normalize_targets(candidates)

    def _ok_result(self, message: str) -> dict[str, Any]:
        return {
            "success": True,
            "state": DIRECT_ALARM_STATE_OK,
            "category": None,
            "message": message,
        }

    def _failure_result(self, category: str, message: str) -> dict[str, Any]:
        return {
            "success": False,
            "state": DIRECT_ALARM_STATE_FAILED,
            "category": category,
            "message": message,
        }
