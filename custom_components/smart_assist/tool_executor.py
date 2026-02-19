"""Shared tool execution utilities for Smart Assist.

Provides a common tool execution function used by both the conversation
streaming handler (streaming.py) and the AI Task entity (ai_task.py)
to avoid duplicated tool execution loops (ARCH-1).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .context.request_history import RequestHistoryStore, ToolCallRecord
from .llm.models import ToolCall
from .tools.base import ToolRegistry, ToolResult

_LOGGER = logging.getLogger(__name__)

WEB_SEARCH_MIN_LATENCY_BUDGET_MS = 3000


async def execute_tool_calls(
    tool_calls: list[ToolCall],
    tool_registry: ToolRegistry,
    max_retries: int,
    latency_budget_ms: int,
    request_history_max_length: int = 500,
) -> list[tuple[ToolCall, ToolResult | Exception, ToolCallRecord]]:
    """Execute tool calls in parallel with retry/timeout support.

    This is the single source of truth for tool execution logic,
    used by both streaming.py and ai_task.py.

    Args:
        tool_calls: List of tool calls to execute
        tool_registry: Registry to look up and execute tools
        max_retries: Maximum retry count per tool
        latency_budget_ms: Latency budget in milliseconds
        request_history_max_length: Max length for truncated argument summaries

    Returns:
        List of (tool_call, result_or_exception, record) tuples preserving order.
        result_or_exception is ToolResult on success, Exception on failure.
    """

    async def _execute_single(tool_call: ToolCall) -> tuple[ToolCall, ToolResult | Exception, ToolCallRecord]:
        """Execute a single tool call and return result with tracking record."""
        started = time.monotonic()
        effective_latency_budget_ms = latency_budget_ms
        if tool_call.name in ("local_web_search", "web_search"):
            effective_latency_budget_ms = max(latency_budget_ms, WEB_SEARCH_MIN_LATENCY_BUDGET_MS)
        try:
            try:
                result = await tool_registry.execute(
                    tool_call.name,
                    tool_call.arguments,
                    max_retries=max_retries,
                    latency_budget_ms=effective_latency_budget_ms,
                )
            except TypeError:
                # Fallback for registries that don't support retry/latency params
                result = await tool_registry.execute(
                    tool_call.name,
                    tool_call.arguments,
                )

            result_data = result.data if isinstance(result.data, dict) else {}
            execution_time_ms = float(
                result_data.get(
                    "execution_time_ms",
                    (time.monotonic() - started) * 1000,
                )
            )
            record = ToolCallRecord(
                name=tool_call.name,
                success=bool(result.success),
                execution_time_ms=execution_time_ms,
                arguments_summary=RequestHistoryStore.truncate(
                    str(tool_call.arguments), request_history_max_length
                ),
                timed_out=bool(result_data.get("timed_out", False)),
                retries_used=int(result_data.get("retries_used", 0)),
                latency_budget_ms=(
                    int(result_data.get("latency_budget_ms", effective_latency_budget_ms))
                    if isinstance(result_data.get("latency_budget_ms"), (int, float))
                    else effective_latency_budget_ms
                ),
            )
            return tool_call, result, record

        except Exception as err:
            execution_time_ms = (time.monotonic() - started) * 1000
            _LOGGER.error("Tool execution failed for %s: %s", tool_call.name, err)
            record = ToolCallRecord(
                name=tool_call.name,
                success=False,
                execution_time_ms=execution_time_ms,
                arguments_summary=RequestHistoryStore.truncate(
                    str(tool_call.arguments), request_history_max_length
                ),
                timed_out=isinstance(err, asyncio.TimeoutError),
                # Conservative semantics for hard failures without ToolResult payload:
                # retries_used is unknown here, so we record 0 instead of inferring.
                retries_used=0,
                latency_budget_ms=effective_latency_budget_ms,
            )
            return tool_call, err, record

    results = await asyncio.gather(
        *[_execute_single(tc) for tc in tool_calls],
        return_exceptions=False,  # Exceptions are caught inside _execute_single
    )

    return list(results)
