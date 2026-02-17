"""Timer tool for Smart Assist - unified timer management.

This tool uses native Assist voice timer intents (HassStartTimer, HassCancelTimer, etc.)
which work WITHOUT Timer Helper entities. These are the built-in voice timers
that work per voice satellite/pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent as ha_intent

# Import timer-specific exceptions (may not exist in older HA versions)
try:
    from homeassistant.components.intent.timers import TimerNotFoundError
except ImportError:
    TimerNotFoundError = None

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class TimerTool(BaseTool):
    """Tool to manage timers using native Assist intents.
    
    Uses HassStartTimer, HassCancelTimer, etc. intents which are built into
    Home Assistant Assist. These work WITHOUT Timer Helper entities.
    """

    name = "timer"
    description = (
        "Manage Assist timers (start, cancel, pause, resume, status) with optional labels and reminder commands. "
        "When action=start, provide at least one of hours/minutes/seconds; command is used only for start."
    )
    
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Timer operation: start, cancel, pause, resume, or status.",
            required=True,
            enum=["start", "cancel", "pause", "resume", "status"],
        ),
        ToolParameter(
            name="hours",
            type="number",
            description="Duration hours. Required with action=start when minutes and seconds are not provided; ignored for non-start actions.",
            required=False,
            minimum=0,
        ),
        ToolParameter(
            name="minutes",
            type="number",
            description="Duration minutes. Required with action=start when hours and seconds are not provided; ignored for non-start actions.",
            required=False,
            minimum=0,
        ),
        ToolParameter(
            name="seconds",
            type="number",
            description="Duration seconds. Required with action=start when hours and minutes are not provided; ignored for non-start actions.",
            required=False,
            minimum=0,
        ),
        ToolParameter(
            name="name",
            type="string",
            description="Timer label (e.g., 'Pizza')",
            required=False,
        ),
        ToolParameter(
            name="command",
            type="string",
            description="Voice command to run when timer ends. Only used for action=start; ignored for cancel/pause/resume/status.",
            required=False,
        ),
    ]

    async def execute(
        self,
        action: str,
        hours: int | None = None,
        minutes: int | None = None,
        seconds: int | None = None,
        name: str | None = None,
        command: str | None = None,
    ) -> ToolResult:
        """Execute timer action using native Assist intents."""
        
        try:
            if action == "start":
                return await self._start_timer(hours, minutes, seconds, name, command)
            elif action == "cancel":
                return await self._cancel_timer(name)
            elif action == "pause":
                return await self._pause_timer(name)
            elif action == "resume":
                return await self._resume_timer(name)
            elif action == "status":
                return await self._timer_status(name)
            else:
                return ToolResult(
                    success=False,
                    message=f"Unknown action: {action}. Use: start, cancel, pause, resume, status",
                )
        except ha_intent.IntentHandleError as err:
            # Common errors like "no timer to cancel"
            error_msg = str(err)
            if "no timer" in error_msg.lower() or "not found" in error_msg.lower():
                if action == "cancel":
                    return ToolResult(success=True, message="No active timer to cancel.")
                elif action == "pause":
                    return ToolResult(success=True, message="No running timer to pause.")
                elif action == "resume":
                    return ToolResult(success=True, message="No paused timer to resume.")
                elif action == "status":
                    return ToolResult(success=True, message="No active timers.")
            return ToolResult(success=False, message=f"Timer error: {error_msg}")
        except Exception as err:
            # Catch TimerNotFoundError and other timer-specific exceptions
            err_name = type(err).__name__
            if err_name == "TimerNotFoundError" or "not found" in str(err).lower():
                if action == "cancel":
                    return ToolResult(success=True, message="No active timer to cancel.")
                elif action == "pause":
                    return ToolResult(success=True, message="No running timer to pause.")
                elif action == "resume":
                    return ToolResult(success=True, message="No paused timer to resume.")
                elif action == "status":
                    return ToolResult(success=True, message="No active timers.")
            _LOGGER.warning("Unexpected timer error (%s): %s", err_name, err)
            return ToolResult(
                success=False,
                message=f"Failed to execute timer action: {err}",
            )

    async def _start_timer(
        self,
        hours: int | None,
        minutes: int | None,
        seconds: int | None,
        name: str | None,
        command: str | None,
    ) -> ToolResult:
        """Start a new timer or reminder."""
        if not any([hours, minutes, seconds]):
            return ToolResult(
                success=False,
                message="Please specify a duration (hours, minutes, or seconds).",
            )
        
        slots: dict[str, Any] = {}
        
        if hours:
            slots["hours"] = {"value": hours}
        if minutes:
            slots["minutes"] = {"value": minutes}
        if seconds:
            slots["seconds"] = {"value": seconds}
        if name:
            slots["name"] = {"value": name}
        if command:
            slots["conversation_command"] = {"value": command}
        
        response = await ha_intent.async_handle(
            self._hass,
            "smart_assist",
            "HassStartTimer",
            slots,
            device_id=self._device_id,
            conversation_agent_id=self._conversation_agent_id,
        )
        
        # Build duration string for response
        parts = []
        if hours:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        if seconds:
            parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")
        duration_str = " and ".join(parts) if parts else "unknown duration"
        
        name_str = f" named '{name}'" if name else ""
        command_str = f" with command '{command}'" if command else ""
        
        # Get speech response if available
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        # Custom message for reminders/commands
        if command:
            return ToolResult(
                success=True,
                message=f"Reminder set for {duration_str}. Will execute: {command}",
            )
        
        return ToolResult(
            success=True,
            message=f"Timer{name_str} started for {duration_str}.",
        )

    async def _cancel_timer(self, name: str | None) -> ToolResult:
        """Cancel a timer."""
        slots: dict[str, Any] = {}
        
        if name:
            slots["name"] = {"value": name}
        
        response = await ha_intent.async_handle(
            self._hass,
            "smart_assist",
            "HassCancelTimer",
            slots,
            device_id=self._device_id,
        )
        
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        name_str = f" '{name}'" if name else ""
        return ToolResult(
            success=True,
            message=f"Timer{name_str} cancelled.",
        )

    async def _pause_timer(self, name: str | None) -> ToolResult:
        """Pause a timer."""
        slots: dict[str, Any] = {}
        
        if name:
            slots["name"] = {"value": name}
        
        response = await ha_intent.async_handle(
            self._hass,
            "smart_assist",
            "HassPauseTimer",
            slots,
            device_id=self._device_id,
        )
        
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        name_str = f" '{name}'" if name else ""
        return ToolResult(
            success=True,
            message=f"Timer{name_str} paused.",
        )

    async def _resume_timer(self, name: str | None) -> ToolResult:
        """Resume a paused timer."""
        slots: dict[str, Any] = {}
        
        if name:
            slots["name"] = {"value": name}
        
        response = await ha_intent.async_handle(
            self._hass,
            "smart_assist",
            "HassUnpauseTimer",
            slots,
            device_id=self._device_id,
        )
        
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        name_str = f" '{name}'" if name else ""
        return ToolResult(
            success=True,
            message=f"Timer{name_str} resumed.",
        )

    async def _timer_status(self, name: str | None) -> ToolResult:
        """Get timer status."""
        slots: dict[str, Any] = {}
        
        if name:
            slots["name"] = {"value": name}
        
        response = await ha_intent.async_handle(
            self._hass,
            "smart_assist",
            "HassTimerStatus",
            slots,
            device_id=self._device_id,
        )
        
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        return ToolResult(
            success=True,
            message="No active timers.",
        )

    def _get_speech(self, response: ha_intent.IntentResponse) -> str | None:
        """Extract speech text from intent response."""
        if response.speech:
            # Try plain text first
            if "plain" in response.speech:
                return response.speech["plain"].get("speech")
            # Try SSML
            if "ssml" in response.speech:
                return response.speech["ssml"].get("speech")
        return None
