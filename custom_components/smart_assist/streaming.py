"""LLM streaming and tool execution loop for Smart Assist conversation."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any, TYPE_CHECKING

from .const import (
    CONF_TOOL_LATENCY_BUDGET_MS,
    CONF_TOOL_MAX_RETRIES,
    CRITICAL_DOMAINS,
    DEFAULT_TOOL_LATENCY_BUDGET_MS,
    DEFAULT_TOOL_MAX_RETRIES,
    MAX_CONSECUTIVE_FOLLOWUPS,
    MAX_TOOL_ITERATIONS,
    REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH,
    TTS_STREAM_MIN_CHARS,
)
from .context.request_history import RequestHistoryStore, ToolCallRecord
from .llm.models import ChatMessage, MessageRole, ToolCall

if TYPE_CHECKING:
    from homeassistant.components.conversation import AssistantContentDeltaDict, ChatLog
    from .conversation import SmartAssistConversationEntity

_LOGGER = logging.getLogger(__name__)

_CONFIRM_TOKENS = {
    "yes", "confirm", "confirmed", "proceed", "do it", "go ahead", "ja", "bestaetigt", "ok",
}
_DENY_TOKENS = {
    "no", "cancel", "stop", "don't", "do not", "nein", "abbrechen", "stopp",
}


def _get_latest_user_text(messages: list[ChatMessage]) -> str:
    """Return the latest non-empty user message text."""
    for msg in reversed(messages):
        if msg.role == MessageRole.USER and msg.content:
            return msg.content
    return ""


def _looks_like_timer_request(user_text: str) -> bool:
    """Heuristic: detect timer-related user intent in EN/DE phrasing."""
    text = (user_text or "").lower()
    if "timer" not in text and "countdown" not in text:
        return False

    duration_pattern = re.compile(
        r"\b\d+\s*(h|hr|hour|hours|std|stunde|stunden|min|minute|minuten|sec|second|seconds|sek|sekunde|sekunden)\b"
    )
    action_tokens = (
        "stell",
        "set",
        "start",
        "starte",
        "cancel",
        "stop",
        "pause",
        "resume",
        "status",
        "läuft",
    )

    return bool(duration_pattern.search(text) or any(token in text for token in action_tokens))


def _should_force_timer_tool_retry(user_text: str, assistant_text: str) -> bool:
    """Require a timer tool call if a timer action was requested but none was emitted."""
    if not assistant_text.strip():
        return False
    return _looks_like_timer_request(user_text)


def _is_explicit_confirmation(user_text: str) -> bool:
    """Check if user text is an explicit confirmation."""
    text = (user_text or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in _CONFIRM_TOKENS)


def _is_explicit_denial(user_text: str) -> bool:
    """Check if user text is an explicit deny/cancel."""
    text = (user_text or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in _DENY_TOKENS)


def _extract_target_domains(arguments: dict[str, Any]) -> set[str]:
    """Extract target domains from tool arguments."""
    domains: set[str] = set()
    for key in ("entity_id", "target", "entity"):
        value = arguments.get(key)
        if isinstance(value, str) and "." in value:
            domains.add(value.split(".", 1)[0])
    entity_ids = arguments.get("entity_ids")
    if isinstance(entity_ids, list):
        for item in entity_ids:
            if isinstance(item, str) and "." in item:
                domains.add(item.split(".", 1)[0])
    explicit_domain = arguments.get("domain")
    if isinstance(explicit_domain, str) and explicit_domain:
        domains.add(explicit_domain)
    return domains


def _is_critical_tool_call(tool_call: ToolCall) -> bool:
    """Return True if tool call targets a critical control domain."""
    if tool_call.name != "control":
        return False
    target_domains = _extract_target_domains(tool_call.arguments)
    return any(domain in CRITICAL_DOMAINS for domain in target_domains)


async def call_llm_streaming_with_tools(
    entity: SmartAssistConversationEntity,
    messages: list[ChatMessage],
    tools: list[dict[str, Any]],
    cached_prefix_length: int,
    chat_log: ChatLog,
    conversation_id: str | None = None,
    max_iterations: int = MAX_TOOL_ITERATIONS,
) -> tuple[str, bool, int, list[ToolCallRecord]]:
    """Call LLM with streaming and handle tool calls in-loop.

    Implements streaming with tool execution. Content deltas are sent
    to the ChatLog's delta_listener for real-time TTS streaming.
    Tool calls are executed between LLM iterations.

    Args:
        entity: The conversation entity instance
        messages: Initial message list for LLM
        tools: Tool schemas for LLM
        cached_prefix_length: Number of messages to cache
        chat_log: Home Assistant ChatLog for streaming
        conversation_id: Optional conversation ID for entity tracking
        max_iterations: Maximum tool call iterations

    Returns:
        Tuple of (final_response_text, await_response_called, llm_iterations, tool_call_records)
        - final_response_text: The final response after all tool calls
        - await_response_called: True if await_response tool was called
        - llm_iterations: Number of LLM call rounds
        - tool_call_records: List of ToolCallRecord for history tracking
    """
    iteration = 0
    working_messages = messages.copy()
    final_content = ""
    await_response_called = False
    all_tool_call_records: list[ToolCallRecord] = []
    latest_user_text = _get_latest_user_text(working_messages)

    tool_max_retries = int(entity._get_config(CONF_TOOL_MAX_RETRIES, DEFAULT_TOOL_MAX_RETRIES))
    tool_latency_budget_ms = int(
        entity._get_config(CONF_TOOL_LATENCY_BUDGET_MS, DEFAULT_TOOL_LATENCY_BUDGET_MS)
    )

    if conversation_id:
        pending_action = entity._conversation_manager.get_pending_critical_action(conversation_id)
        if pending_action:
            if _is_explicit_denial(latest_user_text):
                entity._conversation_manager.clear_pending_critical_action(conversation_id)
                return "Okay, I cancelled that critical action.", False, iteration, all_tool_call_records

            if _is_explicit_confirmation(latest_user_text):
                result = await (await entity._get_tool_registry()).execute(
                    pending_action.get("tool_name", "control"),
                    pending_action.get("arguments", {}),
                    max_retries=tool_max_retries,
                    latency_budget_ms=tool_latency_budget_ms,
                )
                entity._conversation_manager.clear_pending_critical_action(conversation_id)
                all_tool_call_records.append(
                    ToolCallRecord(
                        name=pending_action.get("tool_name", "control"),
                        success=result.success,
                        execution_time_ms=result.data.get("execution_time_ms", 0.0),
                        arguments_summary=RequestHistoryStore.truncate(
                            str(pending_action.get("arguments", {})),
                            REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH,
                        ),
                        timed_out=result.data.get("timed_out", False),
                        retries_used=result.data.get("retries_used", 0),
                        latency_budget_ms=result.data.get("latency_budget_ms"),
                    )
                )
                return result.to_string(), False, 1, all_tool_call_records

            pending_tool = pending_action.get("tool_name", "control")
            return (
                f"Please confirm before I run the critical action '{pending_tool}'. Reply with yes to proceed or no to cancel.",
                True,
                iteration,
                all_tool_call_records,
            )

    while iteration < max_iterations:
        iteration += 1
        # Log message structure for cache debugging
        msg_summary = [f"{i}:{m.role.value}:{len(m.content)}c" for i, m in enumerate(working_messages)]
        _LOGGER.debug("[USER-REQUEST] LLM iteration %d, messages: %s", iteration, msg_summary)

        # Create delta stream and consume it through ChatLog
        iteration_content = ""
        tool_calls: list[ToolCall] = []

        # Only use streaming in the first iteration
        # Subsequent iterations after tool calls use non-streaming to avoid
        # issues with ChatLog/TTS pipeline that expects a single stream
        use_streaming = (iteration == 1)

        if use_streaming:
            # Use streaming for the first iteration
            try:
                async for content_or_result in chat_log.async_add_delta_content_stream(
                    entity.entity_id or "",
                    create_delta_stream(
                        entity,
                        messages=working_messages,
                        tools=tools,
                        cached_prefix_length=cached_prefix_length,
                    ),
                ):
                    # async_add_delta_content_stream yields AssistantContent or ToolResultContent
                    content_type = type(content_or_result).__name__
                    if content_type == "AssistantContent":
                        if content_or_result.content:
                            iteration_content = content_or_result.content
                        if content_or_result.tool_calls:
                            # Convert HA ToolInput back to our ToolCall format for tool execution
                            for tc in content_or_result.tool_calls:
                                tool_calls.append(ToolCall(
                                    id=tc.id,
                                    name=tc.tool_name,
                                    arguments=tc.tool_args,
                                ))
            except Exception as stream_err:
                _LOGGER.warning(
                    "[USER-REQUEST] Stream error in iteration %d: %s. Falling back to non-streaming.",
                    iteration, stream_err
                )
                use_streaming = False  # Fall through to non-streaming below

        if not use_streaming:
            # Non-streaming for iterations after tool calls
            # This avoids issues with ChatLog expecting a single stream
            response = await entity._llm_client.chat(
                messages=working_messages,
                tools=tools,
            )
            if response.content:
                iteration_content = response.content
            if response.tool_calls:
                for tc in response.tool_calls:
                    tool_calls.append(tc)

            if response.tool_calls:
                # Report tool calls to HA's ChatLog so they appear in pipeline traces
                try:
                    async for content_or_result in chat_log.async_add_delta_content_stream(
                        entity.entity_id or "",
                        wrap_response_as_delta_stream(
                            entity,
                            content=iteration_content,
                            tool_calls=response.tool_calls,
                        ),
                    ):
                        pass  # Tool calls already collected above
                except Exception as stream_err:
                    _LOGGER.debug(
                        "[USER-REQUEST] Failed to report tool calls to chat_log: %s",
                        stream_err,
                    )
            elif iteration_content:
                # Final iteration (content, no tool calls) - trigger TTS streaming
                try:
                    if chat_log.delta_listener:
                        # Send role first
                        chat_log.delta_listener(chat_log, {"role": "assistant"})
                        # Pad content to exceed STREAM_RESPONSE_CHARS threshold (60)
                        # This triggers tts_start_streaming for Companion App
                        content_for_delta = iteration_content
                        if len(content_for_delta) < TTS_STREAM_MIN_CHARS:
                            content_for_delta = content_for_delta + " " * (TTS_STREAM_MIN_CHARS - len(content_for_delta))
                        chat_log.delta_listener(chat_log, {"content": content_for_delta})
                except Exception as delta_err:
                    # delta_listener may throw if ChatLog is in invalid state
                    # The content was likely already sent, so just log and continue
                    _LOGGER.debug(
                        "[USER-REQUEST] delta_listener error (content may still be delivered): %s",
                        delta_err
                    )

        # Update final content with this iteration's result
        if iteration_content:
            final_content = iteration_content

        # Remove retry nudge if it was added (avoid permanent token waste)
        if (working_messages
                and working_messages[-1].role == MessageRole.SYSTEM
                and "empty response" in working_messages[-1].content.lower()):
            working_messages.pop()

        # If no tool calls, we're done
        if not tool_calls:
            # Guardrail: avoid false timer confirmations without actual timer tool execution.
            if iteration == 1:
                latest_user_text = _get_latest_user_text(working_messages)
                if _should_force_timer_tool_retry(latest_user_text, final_content):
                    _LOGGER.warning(
                        "[USER-REQUEST] Timer-like request answered without tool call in first iteration. Retrying with timer-tool nudge."
                    )
                    working_messages.append(
                        ChatMessage(
                            role=MessageRole.SYSTEM,
                            content=(
                                "The user requested timer handling. You MUST call the timer tool for start/cancel/pause/resume/status. "
                                "Do not claim timer success unless timer tool call succeeds. "
                                "If required timer details are missing, ask one concise clarification using await_response."
                            ),
                        )
                    )
                    continue

            # Retry once if response is empty/useless on first iteration
            # This handles cases where the LLM doesn't know what to do (e.g., smart_discovery with no entity context)
            if iteration == 1 and not final_content.strip():
                _LOGGER.warning(
                    "[USER-REQUEST] Empty response with no tool calls on first iteration. "
                    "Retrying with nudge."
                )
                # Add a system nudge to push the LLM toward tool usage
                working_messages.append(
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=(
                            "You returned an empty response. The user is asking you to do something. "
                            "Use the get_entities tool to discover entities, then use control to act on them. "
                            "Call a tool now."
                        ),
                    )
                )
                continue  # Re-enter the while loop for another LLM call

            _LOGGER.debug("[USER-REQUEST] Complete (iteration %d, no tool calls)", iteration)
            return final_content, await_response_called, iteration, all_tool_call_records

        # Check if await_response is in the tool calls (signal, not executed with others)
        await_response_calls = [tc for tc in tool_calls if tc.name == "await_response"]
        other_tool_calls = [tc for tc in tool_calls if tc.name != "await_response"]

        if await_response_calls:
            await_response_called = True
            _LOGGER.debug("[USER-REQUEST] await_response tool called - conversation will continue")

            # Check consecutive followup limit to prevent infinite loops
            # (e.g., satellite triggered by TV audio causing repeated clarification requests)
            if conversation_id:
                followup_count = entity._conversation_manager.increment_followup(conversation_id)
                if followup_count >= MAX_CONSECUTIVE_FOLLOWUPS:
                    _LOGGER.warning(
                        "[USER-REQUEST] Max consecutive followups (%d) reached - aborting to prevent loop",
                        MAX_CONSECUTIVE_FOLLOWUPS
                    )
                    # Return a polite abort message instead of continuing
                    return "I did not understand. Please try again.", False, iteration, all_tool_call_records

            # Extract message from await_response tool call
            if await_response_calls[0].arguments:
                await_message = await_response_calls[0].arguments.get("message", "")
                if await_message:
                    # Use the message from the tool as the response
                    final_content = await_message
                    _LOGGER.debug("[USER-REQUEST] Using message from await_response: %s", await_message[:50])

            # If only await_response was called, we're done
            if not other_tool_calls:
                if not final_content.strip():
                    _LOGGER.warning("[USER-REQUEST] await_response called without message - check tool definition")
                return final_content, await_response_called, iteration, all_tool_call_records

        # Check if nevermind tool was called (cancel/abort signal)
        nevermind_calls = [tc for tc in tool_calls if tc.name == "nevermind"]
        if nevermind_calls:
            other_tool_calls = [tc for tc in other_tool_calls if tc.name != "nevermind"]
            _LOGGER.debug("[USER-REQUEST] nevermind tool called - marking as cancel")

            # Extract message from nevermind tool call
            if nevermind_calls[0].arguments:
                nevermind_message = nevermind_calls[0].arguments.get("message", "OK.")
                if nevermind_message:
                    final_content = nevermind_message

            # If only nevermind was called (no other tools), we're done
            if not other_tool_calls:
                return final_content, False, iteration, all_tool_call_records

        # Execute other tool calls (not await_response) and add results to messages for next iteration
        if other_tool_calls:
            # Deduplicate tool calls by ID (LLM sometimes sends duplicates)
            seen_ids: set[str] = set()
            unique_tool_calls: list[ToolCall] = []
            for tc in other_tool_calls:
                if tc.id not in seen_ids:
                    seen_ids.add(tc.id)
                    unique_tool_calls.append(tc)
                else:
                    _LOGGER.debug("[USER-REQUEST] Skipping duplicate tool call: %s (id=%s)", tc.name, tc.id)

            if len(unique_tool_calls) < len(other_tool_calls):
                _LOGGER.debug("[USER-REQUEST] Deduplicated %d -> %d tool calls", len(other_tool_calls), len(unique_tool_calls))
                other_tool_calls = unique_tool_calls

            _LOGGER.debug("[USER-REQUEST] Executing %d tool calls", len(other_tool_calls))

            if conversation_id:
                critical_calls = [tc for tc in other_tool_calls if _is_critical_tool_call(tc)]
                if critical_calls:
                    critical_call = critical_calls[0]
                    entity._conversation_manager.set_pending_critical_action(
                        conversation_id,
                        {
                            "tool_name": critical_call.name,
                            "arguments": critical_call.arguments,
                            "created_at": iteration,
                            "target_domains": list(_extract_target_domains(critical_call.arguments)),
                        },
                    )
                    confirmation_question = (
                        "This is a critical action. Please confirm explicitly: yes to proceed or no to cancel."
                    )
                    return confirmation_question, True, iteration, all_tool_call_records

            # Add assistant message with tool calls to working messages
            working_messages.append(
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=iteration_content,
                    tool_calls=other_tool_calls,
                )
            )

            # Execute all tools in parallel
            async def execute_tool(tool_call: ToolCall) -> tuple[ToolCall, Any]:
                """Execute a single tool and return result with metadata."""
                _LOGGER.debug("Executing tool: %s", tool_call.name)
                result = await (await entity._get_tool_registry()).execute(
                    tool_call.name,
                    tool_call.arguments,
                    max_retries=tool_max_retries,
                    latency_budget_ms=tool_latency_budget_ms,
                )
                return (tool_call, result)

            tool_results = await asyncio.gather(
                *[execute_tool(tc) for tc in other_tool_calls],
                return_exceptions=True
            )

            # Add tool results to working messages
            for i, item in enumerate(tool_results):
                if isinstance(item, Exception):
                    _LOGGER.error("Tool execution failed: %s", item)
                    failed_tc = other_tool_calls[i]
                    all_tool_call_records.append(ToolCallRecord(
                        name=failed_tc.name,
                        success=False,
                        execution_time_ms=0.0,
                        arguments_summary=RequestHistoryStore.truncate(
                            str(failed_tc.arguments), REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH
                        ),
                        timed_out=isinstance(item, asyncio.TimeoutError),
                        retries_used=tool_max_retries,
                        latency_budget_ms=tool_latency_budget_ms,
                    ))
                    working_messages.append(
                        ChatMessage(
                            role=MessageRole.TOOL,
                            content=f"Error: {item}",
                            tool_call_id=failed_tc.id,
                            name=failed_tc.name,
                        )
                    )
                    continue
                tool_call, result = item  # type: ignore[misc]
                all_tool_call_records.append(ToolCallRecord(
                    name=tool_call.name,
                    success=result.success,
                    execution_time_ms=result.data.get("execution_time_ms", 0.0),
                    arguments_summary=RequestHistoryStore.truncate(
                        str(tool_call.arguments), REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH
                    ),
                    timed_out=result.data.get("timed_out", False),
                    retries_used=result.data.get("retries_used", 0),
                    latency_budget_ms=result.data.get("latency_budget_ms"),
                ))
                working_messages.append(
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content=result.to_string(),
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                )

                # Track entities from successful control operations for pronoun resolution
                if conversation_id and result.success:
                    entity._track_entity_from_tool_call(
                        conversation_id, tool_call.name, tool_call.arguments
                    )

            # Reset consecutive followup counter after successful tool execution
            # This breaks the followup loop when user provides meaningful input
            if conversation_id:
                entity._conversation_manager.reset_followups(conversation_id)
                _LOGGER.debug("[USER-REQUEST] Reset followup counter after tool execution")
        else:
            # Only await_response was called, no other tools to execute
            # This shouldn't happen normally since we return above, but handle it
            pass

    # Max iterations reached
    _LOGGER.warning("Max tool iterations (%d) reached", max_iterations)
    return final_content, await_response_called, iteration, all_tool_call_records


async def create_delta_stream(
    entity: SmartAssistConversationEntity,
    messages: list[ChatMessage],
    tools: list[dict[str, Any]],
    cached_prefix_length: int,
) -> AsyncGenerator[AssistantContentDeltaDict, None]:
    """Create a delta stream from LLM response for HA's ChatLog.

    Yields AssistantContentDeltaDict objects that conform to HA's
    streaming protocol. Each yield with "role" starts a new message.
    Content and tool_calls are accumulated until the next role.
    """
    from homeassistant.helpers import llm as ha_llm

    # Start with role indicator for new assistant message
    yield {"role": "assistant"}

    async for delta in entity._llm_client.chat_stream_full(
        messages=messages,
        tools=tools,
        cached_prefix_length=cached_prefix_length,
    ):
        # Handle content chunks
        if "content" in delta and delta["content"]:
            yield {"content": delta["content"]}

        # Yield tool calls when complete
        if "tool_calls" in delta and delta["tool_calls"]:
            tool_inputs = []
            for tc in delta["tool_calls"]:
                tool_inputs.append(
                    ha_llm.ToolInput(
                        id=tc.id,
                        tool_name=tc.name,
                        tool_args=tc.arguments,
                        external=True,  # Mark as external - we handle execution
                    )
                )
            yield {"tool_calls": tool_inputs}


async def wrap_response_as_delta_stream(
    entity: SmartAssistConversationEntity,
    content: str,
    tool_calls: list[ToolCall],
) -> AsyncGenerator[AssistantContentDeltaDict, None]:
    """Wrap a non-streaming LLM response as a delta stream for ChatLog.

    This allows non-streaming iterations to report tool calls to HA's
    pipeline trace, just like the streaming path does.
    """
    from homeassistant.helpers import llm as ha_llm

    yield {"role": "assistant"}

    if content:
        yield {"content": content}

    if tool_calls:
        tool_inputs = []
        for tc in tool_calls:
            tool_inputs.append(
                ha_llm.ToolInput(
                    id=tc.id,
                    tool_name=tc.name,
                    tool_args=tc.arguments,
                    external=True,
                )
            )
        yield {"tool_calls": tool_inputs}
