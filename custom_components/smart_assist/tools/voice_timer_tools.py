"""Voice Timer tools for Smart Assist using native Assist intents.

These are the built-in voice timers from Home Assistant Assist.
They don't require Timer Helper entities - they work like voice assistant
timers (per-satellite/pipeline).

Available intents:
- HassStartTimer: Start a timer
- HassCancelTimer: Cancel a timer  
- HassPauseTimer: Pause a timer
- HassUnpauseTimer: Resume a timer
- HassTimerStatus: Get timer status
- HassIncreaseTimer: Add time to a timer
- HassDecreaseTimer: Remove time from a timer
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class VoiceTimerTool(BaseTool):
    """Tool to manage native Assist voice timers.
    
    Uses the built-in HassStartTimer, HassCancelTimer etc. intents.
    These timers are managed by the voice assistant pipeline and
    do NOT require Timer Helper entities.
    """

    name = "voice_timer"
    description = """Manage voice assistant timers (native Assist timers).
    
These are the built-in voice timers - they don't require timer helper entities.

Actions:
- start: Start a timer with duration (hours, minutes, seconds) and optional name
- cancel: Cancel a timer (by name or area)
- pause: Pause a running timer
- resume: Resume a paused timer  
- status: Get status of all timers or a specific timer
- add_time: Add time to a timer
- remove_time: Remove time from a timer

Examples:
- Start 5 minute timer: action=start, minutes=5
- Start named timer: action=start, minutes=10, name="Pizza"
- Cancel pizza timer: action=cancel, name="Pizza"
- Timer status: action=status"""
    
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Timer action: start, cancel, pause, resume, status, add_time, remove_time",
            required=True,
            enum=["start", "cancel", "pause", "resume", "status", "add_time", "remove_time"],
        ),
        ToolParameter(
            name="hours",
            type="number",
            description="Number of hours for the timer duration",
            required=False,
        ),
        ToolParameter(
            name="minutes",
            type="number",
            description="Number of minutes for the timer duration",
            required=False,
        ),
        ToolParameter(
            name="seconds",
            type="number",
            description="Number of seconds for the timer duration",
            required=False,
        ),
        ToolParameter(
            name="name",
            type="string",
            description="Name for the timer (e.g., 'Pizza', 'Laundry')",
            required=False,
        ),
        ToolParameter(
            name="area",
            type="string",
            description="Area of the device that started the timer",
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
        area: str | None = None,
    ) -> ToolResult:
        """Execute voice timer action using native Assist intents."""
        
        try:
            if action == "start":
                return await self._start_timer(hours, minutes, seconds, name)
            elif action == "cancel":
                return await self._cancel_timer(name, area)
            elif action == "pause":
                return await self._pause_timer(name, area)
            elif action == "resume":
                return await self._resume_timer(name, area)
            elif action == "status":
                return await self._timer_status(name, area)
            elif action == "add_time":
                return await self._add_time(hours, minutes, seconds, name, area)
            elif action == "remove_time":
                return await self._remove_time(hours, minutes, seconds, name, area)
            else:
                return ToolResult(
                    success=False,
                    message=f"Unknown action: {action}",
                )
        except intent.IntentNotRegistered:
            return ToolResult(
                success=False,
                message="Timer intents not available. Voice timers may not be enabled.",
            )
        except intent.IntentError as err:
            _LOGGER.error("Timer intent error: %s", err)
            return ToolResult(
                success=False,
                message=f"Timer operation failed: {err}",
            )
        except Exception as err:
            _LOGGER.error("Voice timer error: %s", err)
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
    ) -> ToolResult:
        """Start a new timer."""
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
        
        response = await intent.async_handle(
            self._hass,
            "smart_assist",
            "HassStartTimer",
            slots,
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
        
        # Get speech response if available
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        return ToolResult(
            success=True,
            message=f"Timer{name_str} started for {duration_str}.",
        )

    async def _cancel_timer(
        self,
        name: str | None,
        area: str | None,
    ) -> ToolResult:
        """Cancel a timer."""
        slots: dict[str, Any] = {}
        
        if name:
            slots["name"] = {"value": name}
        if area:
            slots["area"] = {"value": area}
        
        response = await intent.async_handle(
            self._hass,
            "smart_assist",
            "HassCancelTimer",
            slots,
        )
        
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        name_str = f" '{name}'" if name else ""
        return ToolResult(
            success=True,
            message=f"Timer{name_str} cancelled.",
        )

    async def _pause_timer(
        self,
        name: str | None,
        area: str | None,
    ) -> ToolResult:
        """Pause a timer."""
        slots: dict[str, Any] = {}
        
        if name:
            slots["name"] = {"value": name}
        if area:
            slots["area"] = {"value": area}
        
        response = await intent.async_handle(
            self._hass,
            "smart_assist",
            "HassPauseTimer",
            slots,
        )
        
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        name_str = f" '{name}'" if name else ""
        return ToolResult(
            success=True,
            message=f"Timer{name_str} paused.",
        )

    async def _resume_timer(
        self,
        name: str | None,
        area: str | None,
    ) -> ToolResult:
        """Resume a paused timer."""
        slots: dict[str, Any] = {}
        
        if name:
            slots["name"] = {"value": name}
        if area:
            slots["area"] = {"value": area}
        
        response = await intent.async_handle(
            self._hass,
            "smart_assist",
            "HassUnpauseTimer",
            slots,
        )
        
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        name_str = f" '{name}'" if name else ""
        return ToolResult(
            success=True,
            message=f"Timer{name_str} resumed.",
        )

    async def _timer_status(
        self,
        name: str | None,
        area: str | None,
    ) -> ToolResult:
        """Get timer status."""
        slots: dict[str, Any] = {}
        
        if name:
            slots["name"] = {"value": name}
        if area:
            slots["area"] = {"value": area}
        
        response = await intent.async_handle(
            self._hass,
            "smart_assist",
            "HassTimerStatus",
            slots,
        )
        
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        return ToolResult(
            success=True,
            message="Timer status retrieved.",
        )

    async def _add_time(
        self,
        hours: int | None,
        minutes: int | None,
        seconds: int | None,
        name: str | None,
        area: str | None,
    ) -> ToolResult:
        """Add time to a timer."""
        if not any([hours, minutes, seconds]):
            return ToolResult(
                success=False,
                message="Please specify time to add (hours, minutes, or seconds).",
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
        if area:
            slots["area"] = {"value": area}
        
        response = await intent.async_handle(
            self._hass,
            "smart_assist",
            "HassIncreaseTimer",
            slots,
        )
        
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        return ToolResult(
            success=True,
            message="Time added to timer.",
        )

    async def _remove_time(
        self,
        hours: int | None,
        minutes: int | None,
        seconds: int | None,
        name: str | None,
        area: str | None,
    ) -> ToolResult:
        """Remove time from a timer."""
        if not any([hours, minutes, seconds]):
            return ToolResult(
                success=False,
                message="Please specify time to remove (hours, minutes, or seconds).",
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
        if area:
            slots["area"] = {"value": area}
        
        response = await intent.async_handle(
            self._hass,
            "smart_assist",
            "HassDecreaseTimer",
            slots,
        )
        
        speech = self._get_speech(response)
        if speech:
            return ToolResult(success=True, message=speech)
        
        return ToolResult(
            success=True,
            message="Time removed from timer.",
        )

    def _get_speech(self, response: intent.IntentResponse) -> str | None:
        """Extract speech text from intent response."""
        if response.speech:
            # Try plain text first
            if "plain" in response.speech:
                return response.speech["plain"].get("speech")
            # Try SSML
            if "ssml" in response.speech:
                return response.speech["ssml"].get("speech")
        return None
