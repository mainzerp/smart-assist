"""Sensor platform for Smart Assist metrics - Per Agent/Task Sensors."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_ENABLE_CACHE_WARMING,
    DEFAULT_ENABLE_CACHE_WARMING,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Signal names for metrics updates (per subentry)
SIGNAL_METRICS_UPDATED = f"{DOMAIN}_metrics_updated"
SIGNAL_CACHE_WARMING_UPDATED = f"{DOMAIN}_cache_warming_updated"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Smart Assist sensors from config entry subentries.
    
    Creates sensors for each Conversation Agent and AI Task subentry.
    Each set of sensors is added with its config_subentry_id for proper grouping.
    """
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == "conversation":
            # Create conversation agent sensors
            sensors = _create_agent_sensors(hass, entry, subentry)
            if sensors:
                async_add_entities(sensors, config_subentry_id=subentry_id)
        elif subentry.subentry_type == "ai_task":
            # Create AI task sensors
            sensors = _create_task_sensors(hass, entry, subentry)
            if sensors:
                async_add_entities(sensors, config_subentry_id=subentry_id)


def _create_agent_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
) -> list[SensorEntity]:
    """Create sensors for a conversation agent subentry."""
    sensors: list[SensorEntity] = [
        AgentResponseTimeSensor(hass, entry, subentry),
        AgentRequestCountSensor(hass, entry, subentry),
        AgentSuccessRateSensor(hass, entry, subentry),
        AgentTokensSensor(hass, entry, subentry),
        AgentCacheHitsSensor(hass, entry, subentry),
        AgentCacheHitRateSensor(hass, entry, subentry),
        AgentAverageCachedTokensSensor(hass, entry, subentry),
    ]
    
    # Add cache warming sensor if warming is enabled
    if subentry.data.get(CONF_ENABLE_CACHE_WARMING, DEFAULT_ENABLE_CACHE_WARMING):
        sensors.append(AgentCacheWarmingSensor(hass, entry, subentry))
    
    return sensors


def _create_task_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
) -> list[SensorEntity]:
    """Create sensors for an AI task subentry."""
    return [
        TaskResponseTimeSensor(hass, entry, subentry),
        TaskRequestCountSensor(hass, entry, subentry),
        TaskSuccessRateSensor(hass, entry, subentry),
        TaskTokensSensor(hass, entry, subentry),
    ]


class SmartAssistSubentrySensorBase(SensorEntity):
    """Base class for Smart Assist subentry-level sensors."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False  # We use signals instead of polling

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        entity_type: str = "conversation",
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._entry = entry
        self._subentry = subentry
        self._subentry_id = subentry.subentry_id
        self._entity_type = entity_type
        
        # Device info links sensor to the subentry's device
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Smart Assist",
            model="Conversation Agent" if entity_type == "conversation" else "AI Task",
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Register signal listener when added to hass."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_METRICS_UPDATED}_{self._subentry_id}",
                self._handle_metrics_update,
            )
        )

    @callback
    def _handle_metrics_update(self) -> None:
        """Handle metrics update signal."""
        self.async_write_ha_state()

    def _get_metrics(self) -> Any | None:
        """Get metrics from the LLM client for this subentry."""
        domain_data = self.hass.data.get(DOMAIN, {})
        entry_data = domain_data.get(self._entry.entry_id, {})
        
        # Check in agents (conversation) or tasks (ai_task)
        if self._entity_type == "conversation":
            agents = entry_data.get("agents", {})
            agent_info = agents.get(self._subentry_id, {})
            llm_client = agent_info.get("llm_client")
        else:
            tasks = entry_data.get("tasks", {})
            task_info = tasks.get(self._subentry_id, {})
            llm_client = task_info.get("llm_client")
        
        if llm_client and hasattr(llm_client, "metrics"):
            return llm_client.metrics
        return None


# =============================================================================
# Conversation Agent Sensors
# =============================================================================


class AgentResponseTimeSensor(SmartAssistSubentrySensorBase):
    """Sensor for average response time of a conversation agent."""

    _attr_name = "Average Response Time"
    _attr_native_unit_of_measurement = "ms"
    _attr_icon = "mdi:timer-outline"
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "conversation")
        self._attr_unique_id = f"{subentry.subentry_id}_response_time"

    @property
    def native_value(self) -> float | None:
        """Return the average response time."""
        metrics = self._get_metrics()
        if metrics:
            return getattr(metrics, "average_response_time_ms", 0)
        return None


class AgentRequestCountSensor(SmartAssistSubentrySensorBase):
    """Sensor for total request count of a conversation agent."""

    _attr_name = "Total Requests"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:counter"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "conversation")
        self._attr_unique_id = f"{subentry.subentry_id}_total_requests"

    @property
    def native_value(self) -> int | None:
        """Return the total request count."""
        metrics = self._get_metrics()
        if metrics:
            return getattr(metrics, "total_requests", 0)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        metrics = self._get_metrics()
        if metrics:
            return {
                "successful": getattr(metrics, "successful_requests", 0),
                "failed": getattr(metrics, "failed_requests", 0),
                "retries": getattr(metrics, "total_retries", 0),
                "empty_responses": getattr(metrics, "empty_responses", 0),
                "stream_timeouts": getattr(metrics, "stream_timeouts", 0),
            }
        return {}


class AgentSuccessRateSensor(SmartAssistSubentrySensorBase):
    """Sensor for success rate of a conversation agent."""

    _attr_name = "Success Rate"
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:check-circle-outline"
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "conversation")
        self._attr_unique_id = f"{subentry.subentry_id}_success_rate"

    @property
    def native_value(self) -> float | None:
        """Return the success rate."""
        metrics = self._get_metrics()
        if metrics:
            return getattr(metrics, "success_rate", 100.0)
        return None


class AgentTokensSensor(SmartAssistSubentrySensorBase):
    """Sensor for total tokens used by a conversation agent."""

    _attr_name = "Total Tokens"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:file-document-outline"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "conversation")
        self._attr_unique_id = f"{subentry.subentry_id}_total_tokens"

    @property
    def native_value(self) -> int | None:
        """Return the total tokens used."""
        metrics = self._get_metrics()
        if metrics:
            prompt = getattr(metrics, "total_prompt_tokens", 0)
            completion = getattr(metrics, "total_completion_tokens", 0)
            return prompt + completion
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        metrics = self._get_metrics()
        if metrics:
            return {
                "prompt_tokens": getattr(metrics, "total_prompt_tokens", 0),
                "completion_tokens": getattr(metrics, "total_completion_tokens", 0),
            }
        return {}


class AgentCacheHitsSensor(SmartAssistSubentrySensorBase):
    """Sensor for cache hits of a conversation agent."""

    _attr_name = "Cache Hits"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:cached"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "conversation")
        self._attr_unique_id = f"{subentry.subentry_id}_cache_hits"

    @property
    def native_value(self) -> int | None:
        """Return the cache hits count."""
        metrics = self._get_metrics()
        if metrics:
            return getattr(metrics, "cache_hits", 0)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        metrics = self._get_metrics()
        if metrics:
            hits = getattr(metrics, "cache_hits", 0)
            misses = getattr(metrics, "cache_misses", 0)
            total = hits + misses
            hit_rate = (hits / total * 100) if total > 0 else 0
            return {
                "cache_misses": misses,
                "cache_hit_rate": round(hit_rate, 1),
            }
        return {}


class AgentCacheHitRateSensor(SmartAssistSubentrySensorBase):
    """Sensor for token-based cache hit rate of a conversation agent.
    
    Formula: cached_tokens / prompt_tokens * 100%
    This shows what percentage of input tokens were served from cache.
    """

    _attr_name = "Cache Hit Rate"
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:speedometer"
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "conversation")
        self._attr_unique_id = f"{subentry.subentry_id}_cache_hit_rate"

    @property
    def native_value(self) -> float | None:
        """Return the cache hit rate percentage."""
        metrics = self._get_metrics()
        if metrics:
            cached = getattr(metrics, "cached_tokens", 0)
            prompt = getattr(metrics, "total_prompt_tokens", 0)
            if prompt > 0:
                return round((cached / prompt) * 100, 1)
            return 0.0
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        metrics = self._get_metrics()
        if metrics:
            cached = getattr(metrics, "cached_tokens", 0)
            prompt = getattr(metrics, "total_prompt_tokens", 0)
            return {
                "cached_tokens": cached,
                "prompt_tokens": prompt,
                "tokens_saved": cached,
            }
        return {}


class AgentAverageCachedTokensSensor(SmartAssistSubentrySensorBase):
    """Sensor for average cached tokens per request.
    
    Formula: cached_tokens / successful_requests
    Shows how many tokens are being cached on average per request.
    """

    _attr_name = "Average Cached Tokens"
    _attr_icon = "mdi:database-clock"
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "conversation")
        self._attr_unique_id = f"{subentry.subentry_id}_avg_cached_tokens"

    @property
    def native_value(self) -> float | None:
        """Return the average cached tokens per request."""
        metrics = self._get_metrics()
        if metrics:
            cached = getattr(metrics, "cached_tokens", 0)
            successful = getattr(metrics, "successful_requests", 0)
            if successful > 0:
                return round(cached / successful, 0)
            return 0.0
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        metrics = self._get_metrics()
        if metrics:
            cached = getattr(metrics, "cached_tokens", 0)
            successful = getattr(metrics, "successful_requests", 0)
            prompt = getattr(metrics, "total_prompt_tokens", 0)
            avg_prompt = round(prompt / successful, 0) if successful > 0 else 0
            return {
                "total_cached_tokens": cached,
                "successful_requests": successful,
                "average_prompt_tokens": avg_prompt,
            }
        return {}


class AgentCacheWarmingSensor(SmartAssistSubentrySensorBase):
    """Sensor for cache warming status of a conversation agent."""

    _attr_name = "Cache Warming"
    _attr_icon = "mdi:fire"
    _attr_state_class = None  # Override: this is a string status, not a measurement

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "conversation")
        self._attr_unique_id = f"{subentry.subentry_id}_cache_warming"

    async def async_added_to_hass(self) -> None:
        """Register signal listeners when added to hass."""
        await super().async_added_to_hass()
        # Also listen for cache warming specific updates
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_CACHE_WARMING_UPDATED}_{self._subentry_id}",
                self._handle_metrics_update,
            )
        )

    def _get_warming_data(self) -> dict[str, Any] | None:
        """Get cache warming data for this subentry."""
        domain_data = self.hass.data.get(DOMAIN, {})
        entry_data = domain_data.get(self._entry.entry_id, {})
        warming_data = entry_data.get("cache_warming", {})
        return warming_data.get(self._subentry_id)

    @property
    def native_value(self) -> str | None:
        """Return the cache warming status."""
        data = self._get_warming_data()
        if data:
            return data.get("status", "inactive")
        return "inactive"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        data = self._get_warming_data()
        if data:
            return {
                "last_warmup": data.get("last_warmup"),
                "next_warmup": data.get("next_warmup"),
                "warmup_count": data.get("warmup_count", 0),
                "warmup_failures": data.get("warmup_failures", 0),
                "warming_enabled": True,
                "interval_minutes": data.get("interval_minutes"),
            }
        return {"warming_enabled": False}


# =============================================================================
# AI Task Sensors
# =============================================================================


class TaskResponseTimeSensor(SmartAssistSubentrySensorBase):
    """Sensor for average response time of an AI task."""

    _attr_name = "Average Response Time"
    _attr_native_unit_of_measurement = "ms"
    _attr_icon = "mdi:timer-outline"
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "ai_task")
        self._attr_unique_id = f"{subentry.subentry_id}_response_time"

    @property
    def native_value(self) -> float | None:
        """Return the average response time."""
        metrics = self._get_metrics()
        if metrics:
            return getattr(metrics, "average_response_time_ms", 0)
        return None


class TaskRequestCountSensor(SmartAssistSubentrySensorBase):
    """Sensor for total request count of an AI task."""

    _attr_name = "Total Requests"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:counter"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "ai_task")
        self._attr_unique_id = f"{subentry.subentry_id}_total_requests"

    @property
    def native_value(self) -> int | None:
        """Return the total request count."""
        metrics = self._get_metrics()
        if metrics:
            return getattr(metrics, "total_requests", 0)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        metrics = self._get_metrics()
        if metrics:
            return {
                "successful": getattr(metrics, "successful_requests", 0),
                "failed": getattr(metrics, "failed_requests", 0),
            }
        return {}


class TaskSuccessRateSensor(SmartAssistSubentrySensorBase):
    """Sensor for success rate of an AI task."""

    _attr_name = "Success Rate"
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:check-circle-outline"
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "ai_task")
        self._attr_unique_id = f"{subentry.subentry_id}_success_rate"

    @property
    def native_value(self) -> float | None:
        """Return the success rate."""
        metrics = self._get_metrics()
        if metrics:
            return getattr(metrics, "success_rate", 100.0)
        return None


class TaskTokensSensor(SmartAssistSubentrySensorBase):
    """Sensor for total tokens used by an AI task."""

    _attr_name = "Total Tokens"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:file-document-outline"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry, subentry, "ai_task")
        self._attr_unique_id = f"{subentry.subentry_id}_total_tokens"

    @property
    def native_value(self) -> int | None:
        """Return the total tokens used."""
        metrics = self._get_metrics()
        if metrics:
            prompt = getattr(metrics, "total_prompt_tokens", 0)
            completion = getattr(metrics, "total_completion_tokens", 0)
            return prompt + completion
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        metrics = self._get_metrics()
        if metrics:
            return {
                "prompt_tokens": getattr(metrics, "total_prompt_tokens", 0),
                "completion_tokens": getattr(metrics, "total_completion_tokens", 0),
            }
        return {}
