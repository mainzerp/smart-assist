"""Entity manager for Smart Assist."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import area_registry, entity_registry

# Try the newer async_should_expose API first (HA 2024+)
try:
    from homeassistant.components.homeassistant.exposed_entities import async_should_expose
    HAS_EXPOSED_ENTITIES = True
except ImportError:
    HAS_EXPOSED_ENTITIES = False
    async_should_expose = None

from ..const import SUPPORTED_DOMAINS

_LOGGER = logging.getLogger(__name__)

@dataclass
class EntityInfo:
    """Compact entity information for index."""

    entity_id: str
    domain: str
    friendly_name: str
    area_name: str | None


@dataclass
class EntityState:
    """Entity state with key attributes."""

    entity_id: str
    state: str
    attributes: dict[str, Any]

    def to_compact_string(self, hass: Any = None) -> str:
        """Convert to compact string representation.
        
        Args:
            hass: Optional HomeAssistant instance. If provided, group member
                  states are resolved to show on/off breakdown.
        """
        parts = [f"{self.entity_id}: {self.state}"]

        # Check if this is a group entity (has member entity_ids)
        member_ids = self.attributes.get("entity_id")
        if isinstance(member_ids, list) and member_ids:
            # Show group indicator with member on/off breakdown
            if hass is not None:
                on_count = sum(
                    1 for mid in member_ids
                    if (s := hass.states.get(mid)) and s.state == "on"
                )
                off_count = len(member_ids) - on_count
                parts.append(f"GROUP({len(member_ids)} members: {on_count} on, {off_count} off)")
            else:
                parts.append(f"GROUP({len(member_ids)} members)")

        # Add domain-specific key attributes
        domain = self.entity_id.split(".")[0]

        if domain == "light":
            if brightness := self.attributes.get("brightness"):
                parts.append(f"{int(brightness / 255 * 100)}%")
            if color_temp := self.attributes.get("color_temp_kelvin"):
                parts.append(f"{color_temp}K")

        elif domain == "climate":
            if current_temp := self.attributes.get("current_temperature"):
                parts.append(f"current={current_temp}C")
            if target_temp := self.attributes.get("temperature"):
                parts.append(f"target={target_temp}C")
            if hvac_mode := self.attributes.get("hvac_mode"):
                parts.append(hvac_mode)

        elif domain == "cover":
            if position := self.attributes.get("current_position"):
                parts.append(f"{position}%")

        elif domain == "media_player":
            if source := self.attributes.get("source"):
                parts.append(source)
            if volume := self.attributes.get("volume_level"):
                parts.append(f"vol={int(volume * 100)}%")

        elif domain == "sensor":
            if unit := self.attributes.get("unit_of_measurement"):
                parts[0] = f"{self.entity_id}: {self.state}{unit}"

        return ", ".join(parts)


class EntityManager:
    """Manages entity context for LLM interactions."""

    def __init__(
        self,
        hass: HomeAssistant,
        exposed_only: bool = True,
    ) -> None:
        """Initialize the entity manager."""
        self._hass = hass
        self._exposed_only = exposed_only
        self._entity_index_cache: list[EntityInfo] | None = None
        self._entity_index_hash: str | None = None
        self._entity_index_text: str | None = None
        self._entity_index_last_check: float = 0.0
        self._entity_index_ttl: float = 30.0  # seconds

    def _get_area_name(self, entity_id: str, ent_reg=None, area_reg=None, dev_reg=None) -> str | None:
        """Get area name for an entity.

        Accepts optional pre-fetched registries for batch lookups.
        """
        if ent_reg is None:
            ent_reg = entity_registry.async_get(self._hass)
        if area_reg is None:
            area_reg = area_registry.async_get(self._hass)

        if entity_entry := ent_reg.async_get(entity_id):
            if entity_entry.area_id:
                if area := area_reg.async_get_area(entity_entry.area_id):
                    return area.name
            # Check device area
            if entity_entry.device_id:
                if dev_reg is None:
                    from homeassistant.helpers import device_registry
                    dev_reg = device_registry.async_get(self._hass)
                if device := dev_reg.async_get(entity_entry.device_id):
                    if device.area_id:
                        if area := area_reg.async_get_area(device.area_id):
                            return area.name
        return None

    def _is_entity_exposed(self, entity_id: str) -> bool:
        """Check if an entity is exposed to the conversation assistant.
        
        Uses HA's async_should_expose API which checks if entity is exposed
        to the 'conversation' assistant.
        """
        if not self._exposed_only:
            return True

        if not HAS_EXPOSED_ENTITIES or async_should_expose is None:
            _LOGGER.debug("Exposed entities API not available, entity %s will be included", entity_id)
            return True

        try:
            # Check if entity is exposed to the 'conversation' assistant
            return async_should_expose(self._hass, "conversation", entity_id)
        except Exception as err:
            _LOGGER.warning("Could not check if %s is exposed (defaulting to hidden): %s", entity_id, err)
            return False

    def get_all_entities(self) -> list[EntityInfo]:
        """Get all available entities as compact info."""
        entities: list[EntityInfo] = []

        # Fetch registries once for the entire index build (PERF-1)
        ent_reg = entity_registry.async_get(self._hass)
        area_reg = area_registry.async_get(self._hass)
        from homeassistant.helpers import device_registry
        dev_reg = device_registry.async_get(self._hass)

        for state in self._hass.states.async_all():
            domain = state.entity_id.split(".")[0]

            # Filter by supported domains
            if domain not in SUPPORTED_DOMAINS:
                continue

            # Filter by exposed entities if enabled
            if self._exposed_only and not self._is_entity_exposed(state.entity_id):
                continue

            entities.append(
                EntityInfo(
                    entity_id=state.entity_id,
                    domain=domain,
                    friendly_name=state.attributes.get("friendly_name", state.entity_id),
                    area_name=self._get_area_name(state.entity_id, ent_reg, area_reg, dev_reg),
                )
            )

        return entities

    def get_entity_index(self, force_refresh: bool = False) -> tuple[str, str]:
        """Get entity index for caching and its hash.

        Uses a time-based TTL to avoid rebuilding on every call.

        Returns:
            Tuple of (index_text, hash)
        """
        now = time.monotonic()

        # Return cached if TTL not expired
        if (
            not force_refresh
            and self._entity_index_text is not None
            and self._entity_index_hash is not None
            and (now - self._entity_index_last_check) < self._entity_index_ttl
        ):
            return self._entity_index_text, self._entity_index_hash

        current_entities = self.get_all_entities()
        current_hash = self._compute_index_hash(current_entities)
        self._entity_index_last_check = now

        # Return cached text if hash matches (entities unchanged)
        if (
            self._entity_index_text is not None
            and self._entity_index_hash == current_hash
        ):
            return self._entity_index_text, current_hash

        # Update cache
        self._entity_index_cache = current_entities
        self._entity_index_hash = current_hash
        self._entity_index_text = self._format_entity_index(current_entities)

        return self._entity_index_text, current_hash

    def _compute_index_hash(self, entities: list[EntityInfo]) -> str:
        """Compute hash of entity index for cache invalidation.
        
        Includes entity_id, friendly_name, and area_name so that
        renames and area reassignments also invalidate the cache.
        """
        data = sorted(
            f"{e.entity_id}:{e.friendly_name}:{e.area_name or ''}"
            for e in entities
        )
        return hashlib.sha256("|".join(data).encode()).hexdigest()[:16]

    def _format_entity_index(self, entities: list[EntityInfo]) -> str:
        """Format entity index for LLM context."""
        # Group by area
        by_area: dict[str, list[EntityInfo]] = {}
        no_area: list[EntityInfo] = []

        for entity in entities:
            if entity.area_name:
                by_area.setdefault(entity.area_name, []).append(entity)
            else:
                no_area.append(entity)

        lines = ["Available entities:"]

        for area_name in sorted(by_area.keys()):
            lines.append(f"\n{area_name}:")
            for entity in sorted(by_area[area_name], key=lambda e: e.entity_id):
                lines.append(f"  {entity.entity_id} ({entity.friendly_name})")

        if no_area:
            lines.append("\nOther:")
            for entity in sorted(no_area, key=lambda e: e.entity_id):
                lines.append(f"  {entity.entity_id} ({entity.friendly_name})")

        return "\n".join(lines)

    def get_entity_state(self, entity_id: str) -> EntityState | None:
        """Get current state of an entity."""
        if state := self._hass.states.get(entity_id):
            return EntityState(
                entity_id=entity_id,
                state=state.state,
                attributes=dict(state.attributes),
            )
        return None

    def get_entity_states(self, entity_ids: list[str]) -> list[EntityState]:
        """Get current states of multiple entities."""
        states = []
        for entity_id in entity_ids:
            if entity_state := self.get_entity_state(entity_id):
                states.append(entity_state)
        return states

    def get_relevant_entity_states(
        self,
        query: str,
        max_entities: int = 10,
    ) -> str:
        """Get entity states relevant to a query.

        Keyword scoring is ranking-only context assistance.
        It is non-authoritative and must not be used as execution intent inference.
        Returns formatted string for LLM context.
        """
        query_lower = query.lower()
        entities = self.get_all_entities()
        scored: list[tuple[int, EntityInfo]] = []

        for entity in entities:
            score = 0

            # Score by name match
            if entity.friendly_name.lower() in query_lower:
                score += 10
            elif any(word in entity.friendly_name.lower() for word in query_lower.split()):
                score += 5

            # Score by area match
            if entity.area_name and entity.area_name.lower() in query_lower:
                score += 8

            # Score by domain match
            domain_keywords = {
                "light": ["light", "lamp", "brightness", "dim"],
                "climate": ["temperature", "thermostat", "heating", "cooling", "hvac"],
                "cover": ["blind", "shutter", "curtain", "cover", "garage"],
                "media_player": ["tv", "speaker", "music", "media", "play"],
                "switch": ["switch", "plug", "outlet"],
                "lock": ["lock", "door"],
            }

            if keywords := domain_keywords.get(entity.domain):
                if any(kw in query_lower for kw in keywords):
                    score += 3

            if score > 0:
                scored.append((score, entity))

        # Sort by score and take top entities
        scored.sort(key=lambda x: x[0], reverse=True)
        relevant = [e for _, e in scored[:max_entities]]

        # Get their current states
        states = self.get_entity_states([e.entity_id for e in relevant])

        if not states:
            return "No relevant entities found for this query."

        lines = ["Current states (info only - always use control tool for actions):"]
        for state in states:
            lines.append(f"  {state.to_compact_string(hass=self._hass)}")

        return "\n".join(lines)

    def get_all_current_states(self) -> str:
        """Get all entity states (for simple queries)."""
        entities = self.get_all_entities()
        states = self.get_entity_states([e.entity_id for e in entities])

        lines = ["All entity states:"]
        for state in states:
            lines.append(f"  {state.to_compact_string(hass=self._hass)}")

        return "\n".join(lines)
