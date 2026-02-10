"""User resolver for Smart Assist.

Resolves the current user from conversation context using a layered
identification strategy:
1. HA user_id (Companion App - authenticated)
2. Session identity (user said "This is Anna")
3. Satellite mapping (configured per-satellite -> user)
4. Presence heuristic (only 1 person home)
5. Fallback to 'default'
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class UserResolver:
    """Resolves the current user from conversation context."""

    def __init__(
        self,
        hass: HomeAssistant,
        user_mappings: dict[str, str] | None = None,
        enable_presence_heuristic: bool = False,
    ) -> None:
        """Initialize the user resolver.

        Args:
            hass: Home Assistant instance
            user_mappings: satellite_id -> user_id mapping from config
            enable_presence_heuristic: Whether to use presence-based user detection
        """
        self._hass = hass
        self._user_mappings = user_mappings or {}
        self._enable_presence_heuristic = enable_presence_heuristic

    def update_mappings(self, mappings: dict[str, str]) -> None:
        """Update user-satellite mappings (e.g., after config change)."""
        self._user_mappings = mappings

    async def resolve_user(
        self,
        satellite_id: str | None = None,
        device_id: str | None = None,
        session_user_id: str | None = None,
        context_user_id: str | None = None,
    ) -> str:
        """Resolve user identifier from available context.

        Args:
            satellite_id: Voice satellite entity_id
            device_id: HA device_id for the satellite
            session_user_id: Active session identity (from switch_user)
            context_user_id: HA authenticated user_id (from Companion App)

        Returns:
            User identifier string (e.g., "anna", "max", "default")
        """
        # Layer 1: Companion App (authenticated HA user)
        if context_user_id:
            user_name = await self._resolve_ha_user(context_user_id)
            if user_name:
                _LOGGER.debug("User resolved via HA auth: %s", user_name)
                return user_name

        # Layer 2: Session identity ("This is Anna")
        if session_user_id:
            _LOGGER.debug("User resolved via session identity: %s", session_user_id)
            return session_user_id

        # Layer 3: Satellite mapping
        if satellite_id and satellite_id in self._user_mappings:
            mapped = self._user_mappings[satellite_id]
            if mapped and mapped != "shared":
                _LOGGER.debug(
                    "User resolved via satellite mapping: %s -> %s",
                    satellite_id, mapped,
                )
                return mapped

        # Layer 4: Presence heuristic (only if enabled)
        if self._enable_presence_heuristic:
            presence_user = self._try_presence_heuristic()
            if presence_user:
                _LOGGER.debug("User resolved via presence heuristic: %s", presence_user)
                return presence_user

        # Layer 5: Fallback
        _LOGGER.debug("User resolved to default (no identification available)")
        return "default"

    async def _resolve_ha_user(self, ha_user_id: str) -> str | None:
        """Map HA user_id to a memory user name."""
        try:
            user = await self._hass.auth.async_get_user(ha_user_id)
            if user and user.name:
                return user.name.lower().strip()
        except Exception:
            _LOGGER.debug("Could not resolve HA user_id: %s", ha_user_id)
        return None

    def _try_presence_heuristic(self) -> str | None:
        """If exactly 1 known user is home, return that user."""
        try:
            persons_home = [
                state
                for state in self._hass.states.async_all("person")
                if state.state == "home"
            ]
            if len(persons_home) == 1:
                person_name = (
                    persons_home[0]
                    .attributes.get("friendly_name", "")
                    .lower()
                    .strip()
                )
                # Only use if this person is a known mapped user
                known_users = set(self._user_mappings.values())
                if person_name and person_name in known_users:
                    return person_name
        except Exception:
            _LOGGER.debug("Presence heuristic failed", exc_info=True)
        return None
