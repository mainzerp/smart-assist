"""Timer tools for Smart Assist."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceNotFound

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class TimerTool(BaseTool):
    """Tool to manage Home Assistant timers.
    
    Note: This requires the timer integration to be set up in HA.
    Timers are helper entities created via Settings > Devices & Services > Helpers.
    """

    name = "timer"
    description = """Manage Home Assistant timers. 
Actions:
- start: Start a timer with optional duration (e.g., "00:05:00" for 5 minutes)
- cancel: Cancel/stop a running timer
- pause: Pause a running timer
- finish: Immediately finish a timer (triggers timer.finished event)
- change: Modify duration of a running timer

If no timer_id is specified, will try to find an available timer."""
    
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Timer action: start, cancel, pause, finish, change",
            required=True,
            enum=["start", "cancel", "pause", "finish", "change"],
        ),
        ToolParameter(
            name="timer_id",
            type="string",
            description="Timer entity ID (e.g., timer.kitchen). If not specified, finds first available timer.",
            required=False,
        ),
        ToolParameter(
            name="duration",
            type="string",
            description="Duration in HH:MM:SS format (e.g., '00:05:00' for 5 minutes). Required for 'start' action.",
            required=False,
        ),
    ]

    async def execute(
        self,
        action: str,
        timer_id: str | None = None,
        duration: str | None = None,
    ) -> ToolResult:
        """Execute timer action."""
        # Find timer entity if not specified
        if not timer_id:
            timer_id = self._find_available_timer(action)
            if not timer_id:
                return ToolResult(
                    success=False,
                    message="No timer entities found. Create a timer helper in Settings > Devices & Services > Helpers.",
                )
        
        # Ensure proper entity ID format
        if not timer_id.startswith("timer."):
            timer_id = f"timer.{timer_id}"
        
        # Check if timer exists
        state = self._hass.states.get(timer_id)
        if not state:
            available = self._get_all_timers()
            if available:
                return ToolResult(
                    success=False,
                    message=f"Timer '{timer_id}' not found. Available timers: {', '.join(available)}",
                )
            return ToolResult(
                success=False,
                message=f"Timer '{timer_id}' not found. No timers configured.",
            )
        
        current_state = state.state
        
        try:
            if action == "start":
                service_data: dict[str, Any] = {"entity_id": timer_id}
                if duration:
                    service_data["duration"] = duration
                await self._hass.services.async_call(
                    "timer", "start", service_data, blocking=True
                )
                duration_str = f" for {duration}" if duration else ""
                return ToolResult(
                    success=True,
                    message=f"Timer {timer_id} started{duration_str}.",
                )
            
            elif action == "cancel":
                if current_state == "idle":
                    return ToolResult(
                        success=True,
                        message=f"Timer {timer_id} is not running (already idle).",
                    )
                await self._hass.services.async_call(
                    "timer", "cancel", {"entity_id": timer_id}, blocking=True
                )
                return ToolResult(
                    success=True,
                    message=f"Timer {timer_id} cancelled.",
                )
            
            elif action == "pause":
                if current_state != "active":
                    return ToolResult(
                        success=False,
                        message=f"Timer {timer_id} cannot be paused (current state: {current_state}).",
                    )
                await self._hass.services.async_call(
                    "timer", "pause", {"entity_id": timer_id}, blocking=True
                )
                return ToolResult(
                    success=True,
                    message=f"Timer {timer_id} paused.",
                )
            
            elif action == "finish":
                if current_state == "idle":
                    return ToolResult(
                        success=True,
                        message=f"Timer {timer_id} is not running.",
                    )
                await self._hass.services.async_call(
                    "timer", "finish", {"entity_id": timer_id}, blocking=True
                )
                return ToolResult(
                    success=True,
                    message=f"Timer {timer_id} finished.",
                )
            
            elif action == "change":
                if not duration:
                    return ToolResult(
                        success=False,
                        message="Duration required for 'change' action.",
                    )
                if current_state != "active":
                    return ToolResult(
                        success=False,
                        message=f"Timer {timer_id} is not active (current state: {current_state}).",
                    )
                await self._hass.services.async_call(
                    "timer", "change", {"entity_id": timer_id, "duration": duration}, blocking=True
                )
                return ToolResult(
                    success=True,
                    message=f"Timer {timer_id} duration changed to {duration}.",
                )
            
            else:
                return ToolResult(
                    success=False,
                    message=f"Unknown action: {action}. Use: start, cancel, pause, finish, change.",
                )
                
        except ServiceNotFound:
            return ToolResult(
                success=False,
                message="Timer integration not available. Make sure the timer helper is configured.",
            )
        except Exception as err:
            _LOGGER.error("Timer action failed: %s", err)
            return ToolResult(
                success=False,
                message=f"Failed to {action} timer: {err}",
            )

    def _get_all_timers(self) -> list[str]:
        """Get all timer entity IDs."""
        return [
            state.entity_id
            for state in self._hass.states.async_all()
            if state.entity_id.startswith("timer.")
        ]

    def _find_available_timer(self, action: str) -> str | None:
        """Find an available timer for the action.
        
        For 'start': prefer idle timers
        For other actions: prefer active/paused timers
        """
        timers = self._get_all_timers()
        if not timers:
            return None
        
        if action == "start":
            # Find an idle timer
            for timer_id in timers:
                state = self._hass.states.get(timer_id)
                if state and state.state == "idle":
                    return timer_id
            # If all are busy, return first one anyway
            return timers[0]
        else:
            # Find an active or paused timer
            for timer_id in timers:
                state = self._hass.states.get(timer_id)
                if state and state.state in ("active", "paused"):
                    return timer_id
            # Return first timer if none active
            return timers[0] if timers else None
