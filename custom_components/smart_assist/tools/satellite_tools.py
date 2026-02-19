"""Assist satellite announcement tools for Smart Assist."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class SatelliteAnnounceTool(BaseTool):
    """Tool for direct Assist satellite announcements."""

    name = "satellite_announce"
    description = (
        "Announce a spoken message on one or more Assist satellites via assist_satellite.announce. "
        "Use this for direct voice output."
    )

    parameters = [
        ToolParameter(
            name="message",
            type="string",
            description="Text to announce on the selected satellite(s).",
            required=True,
        ),
        ToolParameter(
            name="satellite_entity_id",
            type="string",
            description="Single satellite target as entity id (assist_satellite.*) or alias/friendly name (e.g. kitchen, Küche).",
            required=False,
        ),
        ToolParameter(
            name="satellite_entity_ids",
            type="array",
            description="Multiple satellite targets as entity ids and/or aliases/friendly names for batch announce.",
            required=False,
            items={"type": "string"},
            min_items=1,
        ),
        ToolParameter(
            name="batch",
            type="boolean",
            description="Set true to explicitly allow multi-satellite announce with satellite_entity_ids.",
            required=False,
            default=False,
        ),
        ToolParameter(
            name="all",
            type="boolean",
            description="Announce on all available assist_satellite entities. Must not be combined with explicit target parameters.",
            required=False,
            default=False,
        ),
    ]

    async def execute(
        self,
        message: str,
        satellite_entity_id: str | None = None,
        satellite_entity_ids: list[str] | None = None,
        batch: bool | None = None,
        all: bool | None = None,
    ) -> ToolResult:
        """Announce a message on one or more satellites."""
        if not self._hass.services.has_service("assist_satellite", "announce"):
            return ToolResult(
                success=False,
                message="assist_satellite.announce service is unavailable.",
            )

        text = (message or "").strip()
        if not text:
            return ToolResult(success=False, message="Parameter 'message' must not be empty.")

        if satellite_entity_id and satellite_entity_ids:
            return ToolResult(
                success=False,
                message="Pass exactly one of 'satellite_entity_id' or 'satellite_entity_ids', not both.",
            )

        if all and (satellite_entity_id or satellite_entity_ids):
            return ToolResult(
                success=False,
                message="Parameter 'all=true' must not be combined with explicit satellite target parameters.",
            )

        if satellite_entity_ids and len(satellite_entity_ids) > 1 and batch is not True:
            return ToolResult(
                success=False,
                message="Batch announce requires explicit batch=true when using multiple satellite_entity_ids.",
            )

        if all:
            raw_targets = [entity_id for entity_id, _friendly in self._get_available_satellites()]
            if not raw_targets:
                return ToolResult(success=False, message="No assist_satellite entities available for all=true.")
        elif satellite_entity_ids:
            raw_targets = satellite_entity_ids
        elif satellite_entity_id:
            raw_targets = [satellite_entity_id]
        elif self._satellite_id:
            raw_targets = [self._satellite_id]
        else:
            return ToolResult(
                success=False,
                message=(
                    "No satellite target provided. Set satellite_entity_id or satellite_entity_ids "
                    "(or execute from a satellite conversation context)."
                ),
            )

        targets: list[str] = []
        seen: set[str] = set()
        for value in raw_targets:
            resolved_target, error = self._resolve_satellite_target(str(value or ""))
            if error:
                return ToolResult(success=False, message=error)
            if not resolved_target or resolved_target in seen:
                continue
            seen.add(resolved_target)
            targets.append(resolved_target)

        if not targets:
            return ToolResult(success=False, message="No valid satellite targets resolved.")

        successful = 0
        failed_targets: list[str] = []
        for target in targets:
            try:
                await self._hass.services.async_call(
                    "assist_satellite",
                    "announce",
                    {
                        "entity_id": target,
                        "message": text,
                    },
                    blocking=True,
                )
                successful += 1
            except Exception as err:
                _LOGGER.warning("Satellite announce failed on %s: %s", target, err)
                failed_targets.append(target)

        if successful == 0:
            return ToolResult(
                success=False,
                message="Satellite announce failed for all targets.",
                data={"targets": targets, "failed_targets": failed_targets},
            )

        if failed_targets:
            return ToolResult(
                success=True,
                message=(
                    f"Announced on {successful}/{len(targets)} satellite(s). "
                    f"Failed: {', '.join(failed_targets)}"
                ),
                data={
                    "targets": targets,
                    "successful": successful,
                    "failed_targets": failed_targets,
                },
            )

        return ToolResult(
            success=True,
            message=f"Announced on {successful} satellite(s).",
            data={"targets": targets, "successful": successful, "failed_targets": []},
        )

    def _resolve_satellite_target(self, raw_target: str) -> tuple[str | None, str | None]:
        """Resolve one target value to assist_satellite entity id.

        Accepts either explicit entity ids or fuzzy aliases/friendly names.
        Returns (entity_id, error_message).
        """
        target = (raw_target or "").strip()
        if not target:
            return None, "Satellite target must not be empty."

        available = self._get_available_satellites()
        available_ids = [entity_id for entity_id, _friendly in available]

        if target.startswith("assist_satellite."):
            if target in available_ids:
                return target, None
            return None, (
                f"Satellite '{target}' not found. Available satellites: "
                f"{', '.join(available_ids) if available_ids else 'none'}"
            )

        normalized_target = self._normalize_satellite_token(target)
        candidates: list[tuple[int, str]] = []
        for entity_id, friendly_name in available:
            slug = entity_id.replace("assist_satellite.", "", 1)
            normalized_slug = self._normalize_satellite_token(slug)
            normalized_friendly = self._normalize_satellite_token(friendly_name)

            score: int | None = None
            if normalized_target == normalized_slug or normalized_target == normalized_friendly:
                score = 0
            elif normalized_slug.startswith(normalized_target) or normalized_friendly.startswith(normalized_target):
                score = 1
            elif normalized_target in normalized_slug or normalized_target in normalized_friendly:
                score = 2

            if score is not None:
                candidates.append((score, entity_id))

        if not candidates:
            return None, (
                f"Satellite alias '{target}' not found. Available satellites: "
                f"{', '.join(available_ids) if available_ids else 'none'}"
            )

        candidates.sort(key=lambda item: (item[0], len(item[1]), item[1]))
        best_score = candidates[0][0]
        best_matches = sorted([entity_id for score, entity_id in candidates if score == best_score])
        if len(best_matches) > 1:
            return None, (
                f"Satellite alias '{target}' is ambiguous. Matches: {', '.join(best_matches)}. "
                "Please specify the exact entity_id."
            )

        return best_matches[0], None

    def _get_available_satellites(self) -> list[tuple[str, str]]:
        """Return available assist_satellite entities as (entity_id, friendly_name)."""
        states = self._hass.states.async_all("assist_satellite")
        satellites: list[tuple[str, str]] = []
        for state in states:
            entity_id = str(getattr(state, "entity_id", "") or "").strip()
            if not entity_id.startswith("assist_satellite."):
                continue
            friendly_name = str(state.attributes.get("friendly_name") or entity_id)
            satellites.append((entity_id, friendly_name))
        return satellites

    @staticmethod
    def _normalize_satellite_token(value: str) -> str:
        """Normalize satellite alias tokens for fuzzy matching."""
        lowered = (value or "").strip().lower()
        translation = str.maketrans(
            {
                "ä": "ae",
                "ö": "oe",
                "ü": "ue",
                "ß": "ss",
                " ": "_",
                "-": "_",
            }
        )
        return lowered.translate(translation)
