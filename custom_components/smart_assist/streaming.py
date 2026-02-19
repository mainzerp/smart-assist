"""LLM streaming and tool execution loop for Smart Assist conversation."""

from __future__ import annotations

import json
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
    MALFORMED_TOOL_RECOVERY_MAX_RETRIES,
    MAX_CONSECUTIVE_FOLLOWUPS,
    MISSING_TOOL_ROUTE_RECOVERY_MAX_RETRIES,
    MAX_TOOL_ITERATIONS,
    POST_FIRE_SNOOZE_CONTEXT_WINDOW_MINUTES,
    REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH,
    TTS_STREAM_MIN_CHARS,
)
from .context.request_history import RequestHistoryStore, ToolCallRecord
from .llm.models import ChatMessage, MessageRole, ToolCall
from .tool_executor import execute_tool_calls
from .utils import extract_target_domains

if TYPE_CHECKING:
    from homeassistant.components.conversation import AssistantContentDeltaDict, ChatLog
    from .conversation import SmartAssistConversationEntity

_LOGGER = logging.getLogger(__name__)

_PENDING_CONFIRMATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["confirm", "deny", "unclear"],
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "reason": {"type": "string"},
    },
    "required": ["decision", "confidence", "reason"],
    "additionalProperties": False,
}

_MISSING_TOOL_ROUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "route": {
            "type": "string",
            "enum": ["alarm", "timer", "none"],
        },
        "alarm_mode": {
            "type": "string",
            "enum": ["absolute", "relative_snooze", "other"],
        },
        "needs_tool_retry": {"type": "boolean"},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "reason": {"type": "string"},
    },
    "required": ["route", "alarm_mode", "needs_tool_retry", "confidence", "reason"],
    "additionalProperties": False,
}


def _get_latest_user_text(messages: list[ChatMessage]) -> str:
    """Return the latest non-empty user message text."""
    for msg in reversed(messages):
        if msg.role == MessageRole.USER and msg.content:
            return msg.content
    return ""


def _extract_json_object(content: str) -> dict[str, Any] | None:
    """Extract first JSON object from model output."""
    text = (content or "").strip()
    if not text:
        return None

    candidates = [text]

    fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    if fenced_match:
        candidates.append(fenced_match.group(1))

    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(text[idx:idx + len(json.dumps(parsed))])
            break

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


def _extract_pseudo_await_response_message(content: str) -> str | None:
    """Extract a natural-language message from textual await_response(...) output."""
    text = (content or "").strip()
    if not text:
        return None

    lowered = text.lower()
    if "await_response(" not in lowered:
        return None

    message_patterns = [
        r'message\s*=\s*"([^"]+)"',
        r"message\s*=\s*'([^']+)'",
        r'message\s+equals\s+"([^"]+)"',
        r"message\s+equals\s+'([^']+)'",
    ]
    for pattern in message_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            extracted = match.group(1).strip()
            return extracted or None

    generic = re.search(r"await_response\((.*)\)", text, flags=re.IGNORECASE | re.DOTALL)
    if generic:
        fallback = generic.group(1).strip()
        return fallback or None

    return None


def _is_missing_query_web_search_error(message: str) -> bool:
    """Return True when tool message indicates a missing-query web search validation failure."""
    normalized = (message or "").strip().lower()
    return "missing query text" in normalized


async def _finalize_web_search_answer_without_tools(
    entity: SmartAssistConversationEntity,
    user_text: str,
    working_messages: list[ChatMessage],
) -> str:
    """Force a final no-tool answer from already collected web-search evidence."""
    web_evidence: list[str] = []
    for msg in reversed(working_messages):
        if msg.role != MessageRole.TOOL:
            continue
        if msg.name not in {"local_web_search", "web_search"}:
            continue
        if not msg.content or msg.content.lower().startswith("error:"):
            continue
        web_evidence.append(msg.content[:1200])
        if len(web_evidence) >= 2:
            break

    if not web_evidence:
        try:
            response = await entity._llm_client.chat(
                messages=[
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=(
                            "Reply in the same language as the user with one concise sentence asking the user to retry the request. "
                            "Do not call tools."
                        ),
                    ),
                    ChatMessage(role=MessageRole.USER, content=user_text or "Please retry."),
                ],
                tools=None,
            )
            content = (response.content or "").strip()
            if content:
                return content
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("[USER-REQUEST] Localized retry fallback synthesis failed: %s", err)
        return "Please ask again."

    web_evidence.reverse()

    try:
        response = await entity._llm_client.chat(
            messages=[
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "Answer the user in the same language as the user question using only the provided web-search evidence. "
                        "Do not call tools. If evidence is inconclusive, clearly say so in one concise sentence."
                    ),
                ),
                ChatMessage(
                    role=MessageRole.USER,
                    content=(
                        f"User question: {user_text}\n\n"
                        f"Web evidence:\n\n{chr(10).join(web_evidence)}"
                    ),
                ),
            ],
            tools=None,
        )
        content = (response.content or "").strip()
        if content:
            return content
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("[USER-REQUEST] Final no-tool web-answer synthesis failed: %s", err)

    try:
        response = await entity._llm_client.chat(
            messages=[
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "Reply in the same language as the user with one concise sentence asking the user to retry with slightly different wording. "
                        "Do not call tools."
                    ),
                ),
                ChatMessage(role=MessageRole.USER, content=user_text or "Please retry."),
            ],
            tools=None,
        )
        content = (response.content or "").strip()
        if content:
            return content
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("[USER-REQUEST] Localized fallback synthesis failed: %s", err)

    return "Please ask again."


async def _classify_pending_confirmation_intent(
    entity: SmartAssistConversationEntity,
    user_text: str,
    pending_action: dict[str, Any],
) -> tuple[str, str]:
    """Classify whether user confirms/denies a pending critical action."""
    try:
        response = await entity._llm_client.chat(
            messages=[
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "Classify whether the user's latest message confirms or denies a pending critical action. "
                        "Output JSON only matching the schema."
                    ),
                ),
                ChatMessage(
                    role=MessageRole.USER,
                    content=(
                        f"Pending action: {pending_action}.\n"
                        f"User message: {user_text}"
                    ),
                ),
            ],
            tools=None,
            response_schema=_PENDING_CONFIRMATION_SCHEMA,
            response_schema_name="smart_assist_pending_confirmation",
            use_native_structured_output=True,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("[USER-REQUEST] Pending confirmation classifier failed: %s", err)
        return "unclear", "low"

    payload = _extract_json_object(response.content)
    if payload is None:
        _LOGGER.warning("[USER-REQUEST] Pending confirmation classifier returned invalid JSON")
        return "unclear", "low"

    decision = payload.get("decision")
    confidence = payload.get("confidence")

    if decision not in {"confirm", "deny", "unclear"}:
        return "unclear", "low"
    if confidence not in {"high", "medium", "low"}:
        return "unclear", "low"

    return str(decision), str(confidence)


async def _classify_missing_tool_intent_route(
    entity: SmartAssistConversationEntity,
    user_text: str,
    assistant_text: str,
) -> dict[str, Any]:
    """Classify route for first-iteration no-tool replies."""
    if not assistant_text.strip():
        return {
            "route": "none",
            "alarm_mode": "other",
            "needs_tool_retry": False,
            "confidence": "low",
            "reason": "assistant_reply_empty",
        }

    try:
        response = await entity._llm_client.chat(
            messages=[
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "Classify if the user message requires alarm or timer tool routing when no tool was called. "
                        "Output JSON only matching the schema."
                    ),
                ),
                ChatMessage(
                    role=MessageRole.USER,
                    content=(
                        f"User message: {user_text}\n"
                        f"Assistant reply without tool call: {assistant_text}"
                    ),
                ),
            ],
            tools=None,
            response_schema=_MISSING_TOOL_ROUTE_SCHEMA,
            response_schema_name="smart_assist_missing_tool_route",
            use_native_structured_output=True,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("[USER-REQUEST] Missing-tool route classifier failed: %s", err)
        return {
            "route": "none",
            "alarm_mode": "other",
            "needs_tool_retry": False,
            "confidence": "low",
            "reason": "classifier_failed",
        }

    payload = _extract_json_object(response.content)
    if payload is None:
        _LOGGER.warning("[USER-REQUEST] Missing-tool route classifier returned invalid JSON")
        return {
            "route": "none",
            "alarm_mode": "other",
            "needs_tool_retry": False,
            "confidence": "low",
            "reason": "invalid_json",
        }

    route = payload.get("route")
    alarm_mode = payload.get("alarm_mode")
    needs_tool_retry = payload.get("needs_tool_retry")
    confidence = payload.get("confidence")
    reason = payload.get("reason")

    if route not in {"alarm", "timer", "none"}:
        route = "none"
    if alarm_mode not in {"absolute", "relative_snooze", "other"}:
        alarm_mode = "other"
    if not isinstance(needs_tool_retry, bool):
        needs_tool_retry = False
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    if not isinstance(reason, str):
        reason = "invalid_reason"

    return {
        "route": route,
        "alarm_mode": alarm_mode,
        "needs_tool_retry": needs_tool_retry,
        "confidence": confidence,
        "reason": reason,
    }


def _has_recent_fired_alarm_context(entity: SmartAssistConversationEntity) -> bool:
    """Return True when at least one recent fired alarm can be resolved safely."""
    manager = getattr(entity, "_persistent_alarm_manager", None)
    if manager is None:
        return False
    try:
        return bool(
            manager.get_recent_fired_alarms(
                window_minutes=POST_FIRE_SNOOZE_CONTEXT_WINDOW_MINUTES,
                limit=3,
            )
        )
    except Exception:  # noqa: BLE001
        return False


def _is_critical_tool_call(tool_call: ToolCall) -> bool:
    """Return True if tool call targets a critical control domain."""
    if tool_call.name != "control":
        return False
    target_domains = extract_target_domains(tool_call.arguments)
    return any(domain in CRITICAL_DOMAINS for domain in target_domains)


def _control_target_key(arguments: dict[str, Any]) -> tuple[str, ...] | None:
    """Build a stable target key for control calls, if possible."""
    entity_id = arguments.get("entity_id")
    if isinstance(entity_id, str) and entity_id:
        return (entity_id,)

    entity_ids = arguments.get("entity_ids")
    if isinstance(entity_ids, list):
        normalized = sorted(str(item) for item in entity_ids if isinstance(item, str) and item)
        if normalized:
            return tuple(normalized)

    return None


def _collapse_conflicting_control_calls(tool_calls: list[ToolCall]) -> list[ToolCall]:
    """Keep only the last control call per target within one iteration."""
    last_control_index_by_target: dict[tuple[str, ...], int] = {}

    for idx, tool_call in enumerate(tool_calls):
        if tool_call.name != "control":
            continue
        target_key = _control_target_key(tool_call.arguments)
        if target_key is None:
            continue
        last_control_index_by_target[target_key] = idx

    collapsed: list[ToolCall] = []
    dropped = 0
    for idx, tool_call in enumerate(tool_calls):
        if tool_call.name != "control":
            collapsed.append(tool_call)
            continue
        target_key = _control_target_key(tool_call.arguments)
        if target_key is None:
            collapsed.append(tool_call)
            continue
        if last_control_index_by_target.get(target_key) == idx:
            collapsed.append(tool_call)
        else:
            dropped += 1

    if dropped:
        _LOGGER.warning(
            "[USER-REQUEST] Dropped %d conflicting control tool call(s) for duplicate targets in one iteration.",
            dropped,
        )

    return collapsed


def _pick_preferred_single_entity(
    entity_ids: list[str],
    entity: SmartAssistConversationEntity,
) -> str | None:
    """Pick best single-entity candidate for non-explicit batch control requests."""
    if not entity_ids:
        return None

    best: tuple[int, int, str] | None = None
    for entity_id in entity_ids:
        score = 0

        state = entity._hass.states.get(entity_id)
        if state is not None and isinstance(state.attributes.get("entity_id"), list):
            score += 100

        candidate = (score, -len(entity_id), entity_id)
        if best is None or candidate > best:
            best = candidate

    return best[2] if best is not None else None


def _normalize_control_tool_call_for_default_single_target(
    tool_call: ToolCall,
    entity: SmartAssistConversationEntity,
) -> ToolCall:
    """Prefer single/group target unless batch is explicitly requested in tool args."""
    if tool_call.name != "control":
        return tool_call

    raw_ids = tool_call.arguments.get("entity_ids")
    if not isinstance(raw_ids, list):
        return tool_call

    entity_ids = [str(item) for item in raw_ids if isinstance(item, str) and item]
    if len(entity_ids) <= 1:
        return tool_call

    if tool_call.arguments.get("batch") is True:
        return tool_call

    preferred = _pick_preferred_single_entity(entity_ids, entity)
    if not preferred:
        return tool_call

    new_arguments = dict(tool_call.arguments)
    new_arguments.pop("entity_ids", None)
    new_arguments.pop("batch", None)
    new_arguments["entity_id"] = preferred
    _LOGGER.debug(
        "[USER-REQUEST] Normalized non-explicit control batch to single target: %s -> %s",
        entity_ids,
        preferred,
    )
    return ToolCall(id=tool_call.id, name=tool_call.name, arguments=new_arguments)


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
    malformed_recovery_retries = 0
    missing_tool_route_retries = 0
    textual_await_response_retries = 0
    web_search_missing_query_iterations = 0
    has_successful_web_search = False

    tool_max_retries = int(entity._get_config(CONF_TOOL_MAX_RETRIES, DEFAULT_TOOL_MAX_RETRIES))
    tool_latency_budget_ms = int(
        entity._get_config(CONF_TOOL_LATENCY_BUDGET_MS, DEFAULT_TOOL_LATENCY_BUDGET_MS)
    )

    if conversation_id:
        pending_action = entity._conversation_manager.get_pending_critical_action(conversation_id)
        if pending_action:
            decision, confidence = await _classify_pending_confirmation_intent(
                entity,
                latest_user_text,
                pending_action,
            )

            if decision == "deny":
                entity._conversation_manager.clear_pending_critical_action(conversation_id)
                return "Okay, I cancelled that critical action.", False, iteration, all_tool_call_records

            if decision == "confirm" and confidence in {"high", "medium"}:
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
                f"Please explicitly confirm to run the critical action '{pending_tool}', or explicitly decline to cancel.",
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
            try:
                response = await entity._llm_client.chat(
                    messages=working_messages,
                    tools=tools,
                )
            except Exception:
                raise
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

        if not tool_calls:
            pseudo_await_message = _extract_pseudo_await_response_message(final_content)
            if pseudo_await_message:
                if textual_await_response_retries < 1:
                    textual_await_response_retries += 1
                    _LOGGER.warning(
                        "[USER-REQUEST] Model returned textual await_response(...) instead of tool call; retrying with strict tool-call instruction."
                    )
                    working_messages.append(
                        ChatMessage(
                            role=MessageRole.SYSTEM,
                            content=(
                                "Do not output await_response(...) as plain text. "
                                "Now call exactly one await_response tool call with valid JSON arguments and no free text."
                            ),
                        )
                    )
                    final_content = ""
                    continue

                _LOGGER.warning(
                    "[USER-REQUEST] Repeated textual await_response(...) output. Returning safe fallback without function syntax."
                )
                return (
                    "Ich brauche eine kurze Klarstellung, bevor ich fortfahren kann.",
                    False,
                    iteration,
                    all_tool_call_records,
                )

        # Remove retry nudge if it was added (avoid permanent token waste)
        if (working_messages
                and working_messages[-1].role == MessageRole.SYSTEM
                and "empty response" in working_messages[-1].content.lower()):
            working_messages.pop()

        malformed_tool_calls = [
            tc for tc in tool_calls if getattr(tc, "parse_status", "ok") != "ok"
        ]
        if malformed_tool_calls:
            malformed_names = sorted({tc.name or "unknown" for tc in malformed_tool_calls})
            if malformed_recovery_retries < MALFORMED_TOOL_RECOVERY_MAX_RETRIES:
                malformed_recovery_retries += 1
                _LOGGER.warning(
                    "[USER-REQUEST] Malformed tool arguments detected (tools=%s). Requesting one deterministic correction retry.",
                    malformed_names,
                )
                working_messages.append(
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=(
                            "Your previous tool call arguments were malformed JSON. "
                            "Retry now with exactly one corrected tool call using a valid JSON object for function arguments. "
                            "Do not return free text or claim success until the corrected tool call is issued."
                        ),
                    )
                )
                continue

            return (
                "I need one quick clarification before I can run that action. Please restate the exact target and action.",
                True,
                iteration,
                all_tool_call_records,
            )

        # If no tool calls, we're done
        if not tool_calls:
            # Guardrail: avoid false timer/alarm confirmations without actual tool execution.
            if missing_tool_route_retries < MISSING_TOOL_ROUTE_RECOVERY_MAX_RETRIES:
                latest_user_text = _get_latest_user_text(working_messages)
                route_decision = await _classify_missing_tool_intent_route(
                    entity,
                    latest_user_text,
                    final_content,
                )

                if (
                    route_decision["route"] == "alarm"
                    and route_decision["needs_tool_retry"]
                    and (
                        route_decision["alarm_mode"] != "relative_snooze"
                        or _has_recent_fired_alarm_context(entity)
                    )
                ):
                    missing_tool_route_retries += 1
                    _LOGGER.warning(
                        "[USER-REQUEST] Alarm route detected without tool call. Retrying with direct alarm route prompt."
                    )
                    working_messages.append(
                        ChatMessage(
                            role=MessageRole.SYSTEM,
                            content=(
                                "Route directly to the alarm tool now. "
                                "Call alarm for set/list/cancel/snooze/status and do not claim success before a successful alarm tool result. "
                                "If alarm target details are missing, ask one concise clarification via await_response."
                            ),
                        )
                    )
                    continue

                if route_decision["route"] == "timer" and route_decision["needs_tool_retry"]:
                    missing_tool_route_retries += 1
                    _LOGGER.warning(
                        "[USER-REQUEST] Timer route detected without tool call. Retrying with direct timer route prompt."
                    )
                    working_messages.append(
                        ChatMessage(
                            role=MessageRole.SYSTEM,
                            content=(
                                "Route directly to the timer tool now. "
                                "Call timer for start/cancel/pause/resume/status and do not claim success before a successful timer tool result. "
                                "If required timer details are missing, ask one concise clarification via await_response."
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

            other_tool_calls = [
                _normalize_control_tool_call_for_default_single_target(tc, entity)
                for tc in other_tool_calls
            ]

            other_tool_calls = _collapse_conflicting_control_calls(other_tool_calls)

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
                            "target_domains": list(extract_target_domains(critical_call.arguments)),
                        },
                    )
                    confirmation_question = (
                        "This is a critical action. Please explicitly confirm to proceed, or explicitly decline to cancel."
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

            # Execute all tools in parallel using shared executor (ARCH-1)
            tool_results = await execute_tool_calls(
                tool_calls=other_tool_calls,
                tool_registry=await entity._get_tool_registry(),
                max_retries=tool_max_retries,
                latency_budget_ms=tool_latency_budget_ms,
                request_history_max_length=REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH,
            )

            # Add tool results to working messages
            iteration_had_web_search = False
            iteration_all_web_search_missing_query = True
            iteration_had_successful_web_search = False
            for tool_call, result_or_err, record in tool_results:
                all_tool_call_records.append(record)
                if isinstance(result_or_err, Exception):
                    working_messages.append(
                        ChatMessage(
                            role=MessageRole.TOOL,
                            content=f"Error: {result_or_err}",
                            tool_call_id=tool_call.id,
                            name=tool_call.name,
                        )
                    )
                    continue
                working_messages.append(
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content=result_or_err.to_string(),
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                )

                if tool_call.name in {"local_web_search", "web_search"}:
                    iteration_had_web_search = True
                    if result_or_err.success:
                        iteration_had_successful_web_search = True
                        iteration_all_web_search_missing_query = False
                    elif not _is_missing_query_web_search_error(result_or_err.message):
                        iteration_all_web_search_missing_query = False

                # Track entities from successful control operations for pronoun resolution
                if conversation_id and result_or_err.success:
                    entity._track_entity_from_tool_call(
                        conversation_id, tool_call.name, tool_call.arguments
                    )

            if iteration_had_successful_web_search:
                has_successful_web_search = True

            if iteration_had_web_search and iteration_all_web_search_missing_query:
                web_search_missing_query_iterations += 1
            else:
                web_search_missing_query_iterations = 0

            if has_successful_web_search and web_search_missing_query_iterations >= 2:
                _LOGGER.warning(
                    "[USER-REQUEST] Repeated local_web_search missing-query retries detected. Forcing final no-tool answer."
                )
                final_content = await _finalize_web_search_answer_without_tools(
                    entity,
                    latest_user_text,
                    working_messages,
                )
                return final_content, await_response_called, iteration, all_tool_call_records

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
    if not final_content.strip() and has_successful_web_search:
        final_content = await _finalize_web_search_answer_without_tools(
            entity,
            latest_user_text,
            working_messages,
        )
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
