"""Scene and automation tools for Smart Assist."""

from __future__ import annotations

import logging

from homeassistant.const import ATTR_ENTITY_ID

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class RunSceneTool(BaseTool):
    """Tool to activate a scene."""

    name = "run_scene"
    description = "Activate a predefined scene."
    parameters = [
        ToolParameter(
            name="scene_id",
            type="string",
            description="The scene entity ID (e.g., scene.movie_night)",
            required=True,
        ),
    ]

    async def execute(self, scene_id: str) -> ToolResult:
        """Execute the run_scene tool."""
        # Ensure it's a scene entity
        if not scene_id.startswith("scene."):
            scene_id = f"scene.{scene_id}"

        try:
            await self._hass.services.async_call(
                "scene",
                "turn_on",
                {ATTR_ENTITY_ID: scene_id},
                blocking=True,
            )

            return ToolResult(
                success=True,
                message=f"Activated scene {scene_id}.",
            )
        except Exception as err:
            return ToolResult(
                success=False,
                message=f"Failed to activate scene: {err}",
            )


class TriggerAutomationTool(BaseTool):
    """Tool to manually trigger an automation."""

    name = "trigger_automation"
    description = "Manually trigger a Home Assistant automation."
    parameters = [
        ToolParameter(
            name="automation_id",
            type="string",
            description="The automation entity ID",
            required=True,
        ),
    ]

    async def execute(self, automation_id: str) -> ToolResult:
        """Execute the trigger_automation tool."""
        # Ensure it's an automation entity
        if not automation_id.startswith("automation."):
            automation_id = f"automation.{automation_id}"

        try:
            await self._hass.services.async_call(
                "automation",
                "trigger",
                {ATTR_ENTITY_ID: automation_id},
                blocking=True,
            )

            return ToolResult(
                success=True,
                message=f"Triggered automation {automation_id}.",
            )
        except Exception as err:
            return ToolResult(
                success=False,
                message=f"Failed to trigger automation: {err}",
            )
