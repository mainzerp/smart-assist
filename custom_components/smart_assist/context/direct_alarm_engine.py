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
    CONF_CANCEL_INTENT_AGENT,
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
    DEFAULT_CANCEL_INTENT_AGENT,
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
from ..llm import ChatMessage
from ..llm.models import MessageRole
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

        message = await self._resolve_tts_message(alarm)
        targets = self._resolve_tts_targets(alarm)
        tts_engine_entity_id = (
            self._resolve_tts_engine_entity_id(alarm)
            if (domain == "tts" and service == "speak")
            else None
        )

        if domain == "tts" and service == "speak" and not tts_engine_entity_id:
            _LOGGER.warning(
                "Direct alarm TTS engine resolution failed for %s (tts.speak). No tts.* entity found.",
                alarm.get("id"),
            )
            return self._failure_result(DIRECT_ALARM_ERROR_VALIDATION, "tts_engine_required")

        if not targets:
            if domain == "tts" and service == "speak":
                raw_delivery = alarm.get("delivery")
                delivery: dict[str, Any] = raw_delivery if isinstance(raw_delivery, dict) else {}
                _LOGGER.warning(
                    "Direct alarm TTS target resolution failed for %s (tts.speak). source_device_id=%s, source_satellite_id=%s, configured_target=%s",
                    alarm.get("id"),
                    delivery.get("source_device_id"),
                    delivery.get("source_satellite_id"),
                    self._config.get(CONF_DIRECT_ALARM_TTS_TARGET, DEFAULT_DIRECT_ALARM_TTS_TARGET),
                )
                return self._failure_result(DIRECT_ALARM_ERROR_VALIDATION, "tts_target_required")
            payload: dict[str, Any] = {"message": message}
            await self._async_call_service(domain, service, payload)
            return self._ok_result(f"{domain}.{service}")

        successful = 0
        failed = 0
        for target in targets:
            payload = self._build_tts_call_payload(
                domain,
                service,
                message,
                target,
                tts_engine_entity_id=tts_engine_entity_id,
            )
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

    async def _resolve_tts_message(self, alarm: dict[str, Any]) -> str:
        """Resolve final TTS text, optionally generated dynamically by LLM."""
        fallback = str(alarm.get("message") or "").strip() or f"Alarm {alarm.get('label', 'Alarm')} fired"
        raw_delivery = alarm.get("delivery")
        delivery: dict[str, Any] = raw_delivery if isinstance(raw_delivery, dict) else {}
        raw_wake_text = delivery.get("wake_text")
        wake_text: dict[str, Any] = raw_wake_text if isinstance(raw_wake_text, dict) else {}

        if not bool(wake_text.get("dynamic", False)):
            return fallback

        llm_client = self._get_llm_client()
        if llm_client is None:
            return fallback

        context_parts: list[str] = []
        if bool(wake_text.get("include_weather", False)):
            weather_context = self._collect_weather_context()
            if weather_context:
                context_parts.append(f"Weather: {weather_context}")
        if bool(wake_text.get("include_news", False)):
            news_context = await self._collect_news_context()
            if news_context:
                context_parts.append(f"News: {news_context}")

        extra_context = "\n".join(context_parts) if context_parts else ""
        language = str(getattr(self._hass.config, "language", "en") or "en")

        try:
            messages = [
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "You write wake-up TTS messages for a smart home alarm. "
                        "Respond in the requested language. Keep it concise and natural: max 2 short sentences. "
                        "No markdown, no emojis."
                    ),
                ),
                ChatMessage(
                    role=MessageRole.USER,
                    content=(
                        f"Language: {language}\n"
                        f"Alarm label: {alarm.get('label', 'Alarm')}\n"
                        f"Fallback message: {fallback}\n"
                        f"Current local time: {dt_util.now().strftime('%H:%M')}\n"
                        f"Optional context:\n{extra_context if extra_context else 'none'}\n"
                        "Generate the final wake-up message now."
                    ),
                ),
            ]
            llm_response = await llm_client.chat(messages=messages, tools=[])
            candidate = str(llm_response.content or "").strip()
            if candidate:
                if len(candidate) > 260:
                    candidate = candidate[:260].rstrip()
                return candidate
        except Exception as err:
            _LOGGER.debug("Dynamic wake text generation failed for %s: %s", alarm.get("id"), err)

        return fallback

    def _collect_weather_context(self) -> str:
        """Return compact weather context from first available weather entity."""
        weather_entities = [
            state for state in self._hass.states.async_all() if state.entity_id.startswith("weather.")
        ]
        if not weather_entities:
            return ""

        state = weather_entities[0]
        attrs = state.attributes
        temperature = attrs.get("temperature")
        temperature_unit = attrs.get("temperature_unit", "C")
        wind_speed = attrs.get("wind_speed")
        wind_unit = attrs.get("wind_speed_unit", "km/h")
        segments = [f"{state.state}"]
        if temperature is not None:
            segments.append(f"{temperature}°{temperature_unit}")
        if wind_speed is not None:
            segments.append(f"wind {wind_speed} {wind_unit}")
        return ", ".join(segments)

    async def _collect_news_context(self) -> str:
        """Return compact latest-news context using DDGS web search."""
        try:
            from ..tools.search_tools import WebSearchTool

            result = await WebSearchTool(self._hass).execute(
                query="latest news headlines",
                max_results=3,
            )
            if not result.success:
                return ""

            entries = result.data.get("results") if isinstance(result.data, dict) else []
        except Exception:
            return ""

        headlines: list[str] = []
        for item in entries if isinstance(entries, list) else []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if title:
                headlines.append(title)
        if not headlines:
            return ""
        return " | ".join(headlines[:3])

    def _get_llm_client(self):
        """Get preferred LLM client from entry agents for dynamic wake text."""
        entry_data = self._hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        agents = entry_data.get("agents", {}) if isinstance(entry_data, dict) else {}
        entry = self._hass.config_entries.async_get_entry(self._entry_id)

        fallback_client = None
        for subentry_id, agent_info in agents.items():
            llm_client = agent_info.get("llm_client") if isinstance(agent_info, dict) else None
            if llm_client is None:
                continue

            if entry is not None:
                subentry = entry.subentries.get(subentry_id)
                if subentry is not None and subentry.data.get(CONF_CANCEL_INTENT_AGENT, DEFAULT_CANCEL_INTENT_AGENT):
                    return llm_client

            if fallback_client is None:
                fallback_client = llm_client

        return fallback_client

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

    def _build_tts_call_payload(
        self,
        domain: str,
        service: str,
        message: str,
        target: str,
        tts_engine_entity_id: str | None = None,
    ) -> dict[str, Any]:
        """Build backend-specific TTS payload for one target."""
        payload: dict[str, Any] = {"message": message}
        if domain == "tts" and service == "speak":
            if tts_engine_entity_id:
                payload["entity_id"] = tts_engine_entity_id
            payload["media_player_entity_id"] = target
        else:
            payload["entity_id"] = target
        return payload

    def _resolve_tts_engine_entity_id(self, alarm: dict[str, Any]) -> str | None:
        """Resolve a tts.* entity id for use with tts.speak.

        Priority:
        1) last known TTS engine from the source conversation agent
        2) first available global tts.* entity
        """
        raw_delivery = alarm.get("delivery")
        delivery: dict[str, Any] = raw_delivery if isinstance(raw_delivery, dict) else {}
        source_agent_id = str(delivery.get("source_conversation_agent_id") or "").strip()
        if source_agent_id:
            preferred = self._resolve_tts_engine_from_source_agent(source_agent_id)
            if preferred:
                return preferred

        candidates: list[str] = []
        try:
            scoped_states = self._hass.states.async_all("tts")
            for state in scoped_states if isinstance(scoped_states, list) else []:
                entity_id = str(getattr(state, "entity_id", "") or "").strip().lower()
                if entity_id.startswith("tts."):
                    candidates.append(entity_id)
        except Exception:
            pass

        if candidates:
            return candidates[0]

        try:
            all_states = self._hass.states.async_all()
            for state in all_states if isinstance(all_states, list) else []:
                entity_id = str(getattr(state, "entity_id", "") or "").strip().lower()
                if entity_id.startswith("tts."):
                    candidates.append(entity_id)
        except Exception:
            return None

        return candidates[0] if candidates else None

    def _resolve_tts_engine_from_source_agent(self, source_agent_id: str) -> str | None:
        """Resolve preferred tts.* entity from source conversation agent context."""
        entry_data = self._hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        agents = entry_data.get("agents") if isinstance(entry_data, dict) else None
        if not isinstance(agents, dict):
            return None

        candidate_ids: list[str] = []

        direct = agents.get(source_agent_id)
        if isinstance(direct, dict):
            entity = direct.get("entity")
            candidate = str(getattr(entity, "_last_tts_engine_entity_id", "") or "").strip().lower()
            if candidate:
                candidate_ids.append(candidate)

        for agent_info in agents.values():
            if not isinstance(agent_info, dict):
                continue
            entity = agent_info.get("entity")
            entity_id = str(getattr(entity, "entity_id", "") or "").strip()
            if entity_id != source_agent_id:
                continue
            candidate = str(getattr(entity, "_last_tts_engine_entity_id", "") or "").strip().lower()
            if candidate:
                candidate_ids.append(candidate)

        for candidate in candidate_ids:
            if candidate.startswith("tts.") and self._hass.states.get(candidate) is not None:
                return candidate

        return None

    def _resolve_tts_targets(self, alarm: dict[str, Any]) -> list[str]:
        """Resolve TTS targets with per-alarm override and source-aware defaults."""
        raw_delivery = alarm.get("delivery")
        delivery: dict[str, Any] = raw_delivery if isinstance(raw_delivery, dict) else {}
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
