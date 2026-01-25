"""Conversation memory manager for Smart Assist."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..llm.models import ChatMessage, MessageRole

_LOGGER = logging.getLogger(__name__)


@dataclass
class ConversationSession:
    """Represents a conversation session."""

    session_id: str
    messages: deque[ChatMessage] = field(default_factory=lambda: deque(maxlen=20))
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)

    def add_message(self, message: ChatMessage) -> None:
        """Add a message to the conversation."""
        self.messages.append(message)
        self.last_active = datetime.now()

    def get_messages(self, max_messages: int | None = None) -> list[ChatMessage]:
        """Get conversation messages."""
        messages = list(self.messages)
        if max_messages:
            messages = messages[-max_messages:]
        return messages

    def clear(self) -> None:
        """Clear conversation history."""
        self.messages.clear()
        self.last_active = datetime.now()

    @property
    def is_expired(self) -> bool:
        """Check if session has expired (30 min inactivity)."""
        return datetime.now() - self.last_active > timedelta(minutes=30)


class ConversationManager:
    """Manages conversation sessions."""

    def __init__(self, max_history: int = 10) -> None:
        """Initialize the conversation manager."""
        self._sessions: dict[str, ConversationSession] = {}
        self._max_history = max_history

    def get_or_create_session(self, session_id: str) -> ConversationSession:
        """Get existing session or create new one."""
        # Clean up expired sessions
        self._cleanup_expired()

        if session_id not in self._sessions:
            self._sessions[session_id] = ConversationSession(session_id=session_id)
            _LOGGER.debug("Created new conversation session: %s", session_id)

        return self._sessions[session_id]

    def add_user_message(self, session_id: str, content: str) -> None:
        """Add a user message to the session."""
        session = self.get_or_create_session(session_id)
        session.add_message(ChatMessage(role=MessageRole.USER, content=content))

    def add_assistant_message(self, session_id: str, content: str) -> None:
        """Add an assistant message to the session."""
        session = self.get_or_create_session(session_id)
        session.add_message(ChatMessage(role=MessageRole.ASSISTANT, content=content))

    def add_tool_result(
        self,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        result: str,
    ) -> None:
        """Add a tool result message to the session."""
        session = self.get_or_create_session(session_id)
        session.add_message(
            ChatMessage(
                role=MessageRole.TOOL,
                content=result,
                tool_call_id=tool_call_id,
                name=tool_name,
            )
        )

    def get_conversation_messages(
        self,
        session_id: str,
        max_messages: int | None = None,
    ) -> list[ChatMessage]:
        """Get messages for a conversation session."""
        if session_id not in self._sessions:
            return []

        session = self._sessions[session_id]
        return session.get_messages(max_messages or self._max_history)

    def clear_session(self, session_id: str) -> None:
        """Clear a specific session."""
        if session_id in self._sessions:
            self._sessions[session_id].clear()
            _LOGGER.debug("Cleared conversation session: %s", session_id)

    def delete_session(self, session_id: str) -> None:
        """Delete a session entirely."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            _LOGGER.debug("Deleted conversation session: %s", session_id)

    def _cleanup_expired(self) -> None:
        """Remove expired sessions."""
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.is_expired
        ]
        for session_id in expired:
            del self._sessions[session_id]
            _LOGGER.debug("Removed expired session: %s", session_id)

    def summarize_conversation(self, session_id: str) -> str:
        """Generate a summary of the conversation.

        This is a simple implementation - could be enhanced with LLM summarization.
        """
        messages = self.get_conversation_messages(session_id)
        if not messages:
            return ""

        # Simple extraction of key actions
        actions = []
        for msg in messages:
            if msg.role == MessageRole.ASSISTANT and msg.content:
                # Extract first sentence as action summary
                first_sentence = msg.content.split(".")[0]
                if len(first_sentence) < 100:
                    actions.append(first_sentence)

        if actions:
            return f"Previous actions: {'; '.join(actions[-3:])}"
        return ""

    def get_session_count(self) -> int:
        """Get number of active sessions."""
        return len(self._sessions)
