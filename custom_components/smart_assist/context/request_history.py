"""Persistent request history for Smart Assist.

Tracks individual conversation requests with metrics for dashboard
trend analysis and tool usage analytics. Uses Home Assistant's
Storage API for persistence across restarts.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import (
    REQUEST_HISTORY_STORAGE_KEY,
    REQUEST_HISTORY_STORAGE_VERSION,
    REQUEST_HISTORY_MAX_ENTRIES,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class ToolCallRecord:
    """Record of a single tool call within a request."""

    name: str
    success: bool
    execution_time_ms: float
    arguments_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "name": self.name,
            "success": self.success,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "arguments_summary": self.arguments_summary,
        }


@dataclass
class RequestHistoryEntry:
    """Record of a single conversation request."""

    id: str
    timestamp: str
    agent_id: str
    agent_name: str
    conversation_id: str | None
    user_id: str
    input_text: str
    response_text: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    response_time_ms: float
    llm_provider: str
    model: str
    llm_iterations: int
    tools_used: list[ToolCallRecord] = field(default_factory=list)
    success: bool = True
    error: str | None = None
    is_nevermind: bool = False
    is_system_call: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "input_text": self.input_text,
            "response_text": self.response_text,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "response_time_ms": round(self.response_time_ms, 2),
            "llm_provider": self.llm_provider,
            "model": self.model,
            "llm_iterations": self.llm_iterations,
            "tools_used": [t.to_dict() for t in self.tools_used],
            "success": self.success,
            "error": self.error,
            "is_nevermind": self.is_nevermind,
            "is_system_call": self.is_system_call,
        }


@dataclass
class ToolAnalytics:
    """Aggregated analytics for a single tool."""

    name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_execution_time_ms: float = 0.0
    last_used: str | None = None

    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.total_calls == 0:
            return 100.0
        return (self.successful_calls / self.total_calls) * 100

    @property
    def average_execution_time_ms(self) -> float:
        """Calculate average execution time."""
        if self.total_calls == 0:
            return 0.0
        return self.total_execution_time_ms / self.total_calls

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "name": self.name,
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "success_rate": round(self.success_rate, 1),
            "average_execution_time_ms": round(self.average_execution_time_ms, 2),
            "total_execution_time_ms": round(self.total_execution_time_ms, 2),
            "last_used": self.last_used,
        }


class RequestHistoryStore:
    """Manages persistent request history for Smart Assist.

    Uses HA's Storage API with debounced saves and FIFO eviction.
    Tool analytics are computed on-demand from stored history entries.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        max_entries: int = REQUEST_HISTORY_MAX_ENTRIES,
    ) -> None:
        """Initialize the request history store."""
        self._hass = hass
        self._store: Store = Store(
            hass, REQUEST_HISTORY_STORAGE_VERSION, REQUEST_HISTORY_STORAGE_KEY
        )
        self._entries: list[dict[str, Any]] = []
        self._max_entries = max_entries
        self._dirty = False
        self._last_save: float = 0.0
        self._save_debounce_seconds = 30.0

    async def async_load(self) -> None:
        """Load history from storage."""
        stored = await self._store.async_load()
        if stored is not None:
            self._entries = stored.get("entries", [])
            self._max_entries = stored.get(
                "max_entries", REQUEST_HISTORY_MAX_ENTRIES
            )
            _LOGGER.info("Loaded request history: %d entries", len(self._entries))
        else:
            self._entries = []
            _LOGGER.info("No existing request history found, starting fresh")

    async def async_save(self) -> None:
        """Save history to storage (debounced)."""
        if not self._dirty:
            return
        now = time.monotonic()
        if now - self._last_save < self._save_debounce_seconds:
            return
        await self._force_save()

    async def _force_save(self) -> None:
        """Force save immediately."""
        try:
            await self._store.async_save({
                "version": REQUEST_HISTORY_STORAGE_VERSION,
                "max_entries": self._max_entries,
                "entries": self._entries,
            })
            self._dirty = False
            self._last_save = time.monotonic()
            _LOGGER.debug("Request history saved (%d entries)", len(self._entries))
        except Exception as err:
            _LOGGER.error("Failed to save request history: %s", err)

    async def async_shutdown(self) -> None:
        """Save pending changes on shutdown."""
        if self._dirty:
            await self._force_save()

    def add_entry(self, entry: RequestHistoryEntry) -> None:
        """Add a new history entry, evicting oldest if over limit."""
        self._entries.append(entry.to_dict())
        # FIFO eviction
        while len(self._entries) > self._max_entries:
            self._entries.pop(0)
        self._dirty = True

    def get_entries(
        self,
        limit: int = 50,
        offset: int = 0,
        agent_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get history entries with optional filtering.

        Returns (entries, total_count) for pagination.
        Entries are returned newest-first.
        """
        filtered = self._entries
        if agent_id:
            filtered = [e for e in filtered if e.get("agent_id") == agent_id]
        total = len(filtered)
        # Newest first
        filtered = list(reversed(filtered))
        return filtered[offset : offset + limit], total

    def get_tool_analytics(
        self, agent_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Compute tool analytics from history entries.

        Args:
            agent_id: Optional filter by agent. None = all agents.

        Returns:
            List of ToolAnalytics dicts, sorted by total_calls descending.
        """
        tools: dict[str, ToolAnalytics] = {}

        for entry in self._entries:
            if agent_id and entry.get("agent_id") != agent_id:
                continue
            for tc in entry.get("tools_used", []):
                name = tc.get("name", "unknown")
                if name not in tools:
                    tools[name] = ToolAnalytics(name=name)
                ta = tools[name]
                ta.total_calls += 1
                if tc.get("success", True):
                    ta.successful_calls += 1
                else:
                    ta.failed_calls += 1
                ta.total_execution_time_ms += tc.get("execution_time_ms", 0.0)
                entry_ts = entry.get("timestamp")
                if entry_ts and (ta.last_used is None or entry_ts > ta.last_used):
                    ta.last_used = entry_ts

        sorted_tools = sorted(
            tools.values(), key=lambda t: t.total_calls, reverse=True
        )
        return [t.to_dict() for t in sorted_tools]

    def get_summary_stats(
        self, agent_id: str | None = None
    ) -> dict[str, Any]:
        """Get summary statistics from history."""
        filtered = self._entries
        if agent_id:
            filtered = [e for e in filtered if e.get("agent_id") == agent_id]

        if not filtered:
            return {
                "total_requests": 0,
                "total_tokens": 0,
                "avg_response_time_ms": 0,
                "avg_tokens_per_request": 0,
                "total_tool_calls": 0,
                "success_rate": 100.0,
            }

        total = len(filtered)
        successful = sum(1 for e in filtered if e.get("success", True))
        total_tokens = sum(
            (e.get("prompt_tokens", 0) + e.get("completion_tokens", 0))
            for e in filtered
        )
        total_response_time = sum(
            e.get("response_time_ms", 0) for e in filtered
        )
        total_tool_calls = sum(
            len(e.get("tools_used", [])) for e in filtered
        )

        return {
            "total_requests": total,
            "successful_requests": successful,
            "total_tokens": total_tokens,
            "avg_response_time_ms": round(total_response_time / total, 2)
            if total > 0
            else 0,
            "avg_tokens_per_request": round(total_tokens / total)
            if total > 0
            else 0,
            "total_tool_calls": total_tool_calls,
            "success_rate": round((successful / total) * 100, 1)
            if total > 0
            else 100.0,
        }

    def clear(self, agent_id: str | None = None) -> int:
        """Clear history entries. Returns count of removed entries.

        Args:
            agent_id: If provided, only clear entries for this agent.
                     If None, clear all entries.
        """
        if agent_id:
            before = len(self._entries)
            self._entries = [
                e for e in self._entries if e.get("agent_id") != agent_id
            ]
            removed = before - len(self._entries)
        else:
            removed = len(self._entries)
            self._entries = []
        if removed > 0:
            self._dirty = True
        return removed

    @staticmethod
    def generate_id() -> str:
        """Generate a unique request ID."""
        ts = int(time.time())
        short = uuid.uuid4().hex[:8]
        return f"req_{ts}_{short}"

    @staticmethod
    def truncate(text: str, max_length: int) -> str:
        """Truncate text to max length with ellipsis."""
        if not text:
            return ""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."
