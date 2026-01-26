"""Sensor platform for Smart Assist metrics."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Signal name for metrics updates
SIGNAL_METRICS_UPDATED = f"{DOMAIN}_metrics_updated"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Smart Assist sensors from a config entry."""
    sensors = [
        SmartAssistResponseTimeSensor(hass, entry),
        SmartAssistRequestCountSensor(hass, entry),
        SmartAssistSuccessRateSensor(hass, entry),
        SmartAssistTokensSensor(hass, entry),
        SmartAssistCacheHitsSensor(hass, entry),
    ]
    
    async_add_entities(sensors)


class SmartAssistSensorBase(SensorEntity):
    """Base class for Smart Assist sensors."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False  # We use signals instead of polling

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Smart Assist",
            "manufacturer": "Smart Assist",
            "model": "Conversation Agent",
            "entry_type": "service",
        }

    async def async_added_to_hass(self) -> None:
        """Register signal listener when added to hass."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_METRICS_UPDATED}_{self._entry.entry_id}",
                self._handle_metrics_update,
            )
        )

    @callback
    def _handle_metrics_update(self) -> None:
        """Handle metrics update signal."""
        self.async_write_ha_state()

    def _get_metrics(self) -> dict[str, Any] | None:
        """Get aggregated metrics from all conversation agents.
        
        With the subentry architecture, each agent has its own LLM client.
        This method aggregates metrics from all agents.
        """
        domain_data = self.hass.data.get(DOMAIN, {})
        entry_data = domain_data.get(self._entry.entry_id, {})
        agents = entry_data.get("agents", {})
        
        if not agents:
            return None
        
        # Aggregate metrics from all agents
        aggregated = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_retries": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_response_time_ms": 0.0,
            "cache_hits": 0,
            "cache_misses": 0,
        }
        
        for agent_info in agents.values():
            llm_client = agent_info.get("llm_client")
            if llm_client and hasattr(llm_client, "metrics"):
                # Access metrics object directly (not to_dict) to get raw values
                metrics = llm_client.metrics
                aggregated["total_requests"] += metrics.total_requests
                aggregated["successful_requests"] += metrics.successful_requests
                aggregated["failed_requests"] += metrics.failed_requests
                aggregated["total_retries"] += metrics.total_retries
                aggregated["total_prompt_tokens"] += metrics.total_prompt_tokens
                aggregated["total_completion_tokens"] += metrics.total_completion_tokens
                aggregated["total_response_time_ms"] += metrics.total_response_time_ms
                aggregated["cache_hits"] += metrics.cache_hits
                aggregated["cache_misses"] += metrics.cache_misses
        
        # Calculate derived metrics
        if aggregated["successful_requests"] > 0:
            aggregated["average_response_time_ms"] = (
                aggregated["total_response_time_ms"] / aggregated["successful_requests"]
            )
        else:
            aggregated["average_response_time_ms"] = 0.0
        
        if aggregated["total_requests"] > 0:
            aggregated["success_rate"] = (
                aggregated["successful_requests"] / aggregated["total_requests"]
            ) * 100
        else:
            aggregated["success_rate"] = 100.0
        
        return aggregated


class SmartAssistResponseTimeSensor(SmartAssistSensorBase):
    """Sensor for average response time."""

    _attr_name = "Average Response Time"
    _attr_native_unit_of_measurement = "ms"
    _attr_icon = "mdi:timer-outline"
    _attr_suggested_display_precision = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_response_time"

    @property
    def native_value(self) -> float | None:
        """Return the average response time."""
        metrics = self._get_metrics()
        if metrics:
            return metrics.get("average_response_time_ms", 0)
        return None


class SmartAssistRequestCountSensor(SmartAssistSensorBase):
    """Sensor for total request count."""

    _attr_name = "Total Requests"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:counter"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_total_requests"

    @property
    def native_value(self) -> int | None:
        """Return the total request count."""
        metrics = self._get_metrics()
        if metrics:
            return metrics.get("total_requests", 0)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        metrics = self._get_metrics()
        if metrics:
            return {
                "successful": metrics.get("successful_requests", 0),
                "failed": metrics.get("failed_requests", 0),
                "retries": metrics.get("total_retries", 0),
            }
        return {}


class SmartAssistSuccessRateSensor(SmartAssistSensorBase):
    """Sensor for success rate."""

    _attr_name = "Success Rate"
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:check-circle-outline"
    _attr_suggested_display_precision = 1

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_success_rate"

    @property
    def native_value(self) -> float | None:
        """Return the success rate."""
        metrics = self._get_metrics()
        if metrics:
            return metrics.get("success_rate", 100.0)
        return None


class SmartAssistTokensSensor(SmartAssistSensorBase):
    """Sensor for total tokens used."""

    _attr_name = "Total Tokens"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:file-document-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_total_tokens"

    @property
    def native_value(self) -> int | None:
        """Return the total tokens used."""
        metrics = self._get_metrics()
        if metrics:
            prompt = metrics.get("total_prompt_tokens", 0)
            completion = metrics.get("total_completion_tokens", 0)
            return prompt + completion
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        metrics = self._get_metrics()
        if metrics:
            return {
                "prompt_tokens": metrics.get("total_prompt_tokens", 0),
                "completion_tokens": metrics.get("total_completion_tokens", 0),
            }
        return {}


class SmartAssistCacheHitsSensor(SmartAssistSensorBase):
    """Sensor for cache performance."""

    _attr_name = "Cache Hits"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:cached"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_cache_hits"

    @property
    def native_value(self) -> int | None:
        """Return the cache hits count."""
        metrics = self._get_metrics()
        if metrics:
            return metrics.get("cache_hits", 0)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        metrics = self._get_metrics()
        if metrics:
            hits = metrics.get("cache_hits", 0)
            misses = metrics.get("cache_misses", 0)
            total = hits + misses
            hit_rate = (hits / total * 100) if total > 0 else 0
            return {
                "cache_misses": misses,
                "cache_hit_rate": round(hit_rate, 1),
            }
        return {}
