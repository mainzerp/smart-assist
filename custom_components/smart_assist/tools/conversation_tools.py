"""Conversation control tools for Smart Assist.

Tools that control conversation flow and interaction with the user.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class AwaitResponseTool(BaseTool):
    """Signal that user response is expected.
    
    This tool is a signal to the conversation handler that the microphone
    should stay open for user input. The LLM should call this when asking
    questions or offering choices.
    """

    name = "await_response"
    description = "Ask user a question and keep mic open for response."
    parameters = [
        ToolParameter(
            name="message",
            type="string",
            description="Question/message to speak before waiting",
            required=True,
        ),
        ToolParameter(
            name="reason",
            type="string",
            description="Reason for waiting",
            required=True,
            enum=["clarification", "confirmation", "choice", "follow_up"],
        )
    ]

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the tool."""
        super().__init__(hass)

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the await_response signal.
        
        This tool returns the message that should be spoken to the user.
        The conversation handler will use this as the response text.
        """
        message = kwargs.get("message", "")
        reason = kwargs.get("reason", "clarification")
        _LOGGER.debug("await_response tool called: message='%s', reason=%s", message, reason)
        
        return ToolResult(
            success=True,
            message=message,  # This becomes the spoken response
            data={"reason": reason, "await_response": True, "spoken_message": message}
        )


class NevermindTool(BaseTool):
    """Signal that user wants to cancel/abort the interaction."""

    name = "nevermind"
    description = "Call when user wants to cancel or dismiss the interaction."
    parameters = [
        ToolParameter(
            name="message",
            type="string",
            description="Brief acknowledgment (1-3 words)",
            required=True,
        ),
    ]

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the tool."""
        super().__init__(hass)

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the nevermind signal."""
        message = kwargs.get("message", "OK.")
        _LOGGER.debug("nevermind tool called: message='%s'", message)
        return ToolResult(
            success=True,
            message=message,
            data={"nevermind": True, "spoken_message": message},
        )
