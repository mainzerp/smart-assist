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
    description = """Signal that you expect user input to continue the conversation.

WHEN TO USE:
- Asking a clarifying question ("Which light - living room or bedroom?")
- Offering multiple choices or options
- Requesting confirmation for critical actions (locks, alarms)
- Proactively offering further help ("Is there anything else I can help with?")

WHEN NOT TO USE:
- Simple action confirmations ("Light is on")
- Information responses that don't need follow-up
- Error messages

Call this tool AFTER your message text, not before."""

    parameters = [
        ToolParameter(
            name="reason",
            type="string",
            description="Brief reason: 'clarification', 'confirmation', 'choice', or 'follow_up'",
            required=False,
            enum=["clarification", "confirmation", "choice", "follow_up"],
        )
    ]

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the tool."""
        super().__init__(hass)

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the await_response signal.
        
        This tool doesn't actually do anything - it's a signal to the
        conversation handler that user input is expected.
        """
        reason = kwargs.get("reason", "clarification")
        _LOGGER.debug("await_response tool called with reason: %s", reason)
        
        return ToolResult(
            success=True,
            message="Awaiting user response",
            data={"reason": reason, "await_response": True}
        )
