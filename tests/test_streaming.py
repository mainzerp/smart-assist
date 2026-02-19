"""Tests for streaming guardrails and classifier-driven intent routing."""

from __future__ import annotations

import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock

# Add custom_components to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from custom_components.smart_assist.streaming import (  # noqa: E402
    _extract_json_object,
    call_llm_streaming_with_tools,
)
from custom_components.smart_assist.llm.models import (  # noqa: E402
    ChatMessage,
    ChatResponse,
    LLMError,
    MessageRole,
    ToolCall,
)
from custom_components.smart_assist.tools.base import ToolResult  # noqa: E402


class _FakeConversationManager:
    def __init__(self) -> None:
        self._pending: dict[str, dict] = {}

    def get_pending_critical_action(self, session_id: str):
        return self._pending.get(session_id)

    def set_pending_critical_action(self, session_id: str, action: dict) -> None:
        self._pending[session_id] = action

    def clear_pending_critical_action(self, session_id: str) -> None:
        self._pending.pop(session_id, None)

    def increment_followup(self, session_id: str) -> int:
        return 0

    def reset_followups(self, session_id: str) -> None:
        return None


class _FakeChatLog:
    delta_listener = None

    async def async_add_delta_content_stream(self, entity_id, stream):
        raise RuntimeError("streaming disabled in test")
        yield


class _FakeEntity:
    def __init__(self, llm_responses, registry_execute_result=None):
        from unittest.mock import AsyncMock, MagicMock

        self.entity_id = "conversation.test"
        self._conversation_manager = _FakeConversationManager()
        self._persistent_alarm_manager = None
        self._hass = MagicMock()
        self._hass.states.get = MagicMock(return_value=None)
        self._llm_client = MagicMock()
        self._llm_client.chat = AsyncMock(side_effect=llm_responses)
        self._registry = MagicMock()
        self._registry.execute = AsyncMock(return_value=registry_execute_result or ToolResult(success=True, message="OK"))

    async def _get_tool_registry(self):
        return self._registry

    def _get_config(self, key, default=None):
        return default

    def _track_entity_from_tool_call(self, conversation_id, tool_name, arguments):
        return None


@pytest.mark.asyncio
async def test_unclear_pending_critical_action_keeps_guardrail(monkeypatch) -> None:
    async def _fake_classifier(entity, user_text, pending_action):
        return "unclear", "low"

    monkeypatch.setattr(
        "custom_components.smart_assist.streaming._classify_pending_confirmation_intent",
        _fake_classifier,
    )

    entity = _FakeEntity([])
    entity._conversation_manager.set_pending_critical_action(
        "conv1",
        {"tool_name": "control", "arguments": {"entity_id": "lock.front_door", "action": "lock"}},
    )

    content, await_response, _, records = await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="sounds good")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    assert "explicitly confirm" in content.lower()
    assert await_response is True
    assert records == []
    entity._registry.execute.assert_not_awaited()
    assert entity._conversation_manager.get_pending_critical_action("conv1") is not None


@pytest.mark.asyncio
async def test_critical_action_requires_confirmation_before_execution() -> None:
    tool_call = ToolCall(id="t1", name="control", arguments={"entity_id": "lock.front_door", "action": "lock"})
    entity = _FakeEntity([
        ChatResponse(content="", tool_calls=[tool_call]),
    ])

    content, await_response, _, records = await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="lock the front door")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    assert "critical action" in content.lower()
    assert await_response is True
    assert records == []
    entity._registry.execute.assert_not_awaited()
    assert entity._conversation_manager.get_pending_critical_action("conv1") is not None


@pytest.mark.asyncio
async def test_confirmed_pending_critical_action_executes(monkeypatch) -> None:
    async def _fake_classifier(entity, user_text, pending_action):
        return "confirm", "medium"

    monkeypatch.setattr(
        "custom_components.smart_assist.streaming._classify_pending_confirmation_intent",
        _fake_classifier,
    )

    entity = _FakeEntity([], registry_execute_result=ToolResult(success=True, message="Locked"))
    entity._conversation_manager.set_pending_critical_action(
        "conv1",
        {"tool_name": "control", "arguments": {"entity_id": "lock.front_door", "action": "lock"}},
    )

    content, await_response, _, records = await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="yes, do it")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    assert "Locked" in content
    assert await_response is False
    assert len(records) == 1
    entity._registry.execute.assert_awaited_once()
    assert entity._conversation_manager.get_pending_critical_action("conv1") is None


@pytest.mark.asyncio
async def test_denied_pending_critical_action_clears_without_execution(monkeypatch) -> None:
    async def _fake_classifier(entity, user_text, pending_action):
        return "deny", "high"

    monkeypatch.setattr(
        "custom_components.smart_assist.streaming._classify_pending_confirmation_intent",
        _fake_classifier,
    )

    entity = _FakeEntity([])
    entity._conversation_manager.set_pending_critical_action(
        "conv1",
        {"tool_name": "control", "arguments": {"entity_id": "lock.front_door", "action": "lock"}},
    )

    content, await_response, _, _ = await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="no")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    assert "cancelled" in content.lower()
    assert await_response is False
    entity._registry.execute.assert_not_awaited()
    assert entity._conversation_manager.get_pending_critical_action("conv1") is None


@pytest.mark.asyncio
async def test_non_critical_tool_executes_without_confirmation_gate() -> None:
    tool_call = ToolCall(id="t1", name="control", arguments={"entity_id": "light.kitchen", "action": "turn_on"})
    entity = _FakeEntity([
        ChatResponse(content="", tool_calls=[tool_call]),
        ChatResponse(content="Kitchen light turned on.", tool_calls=[]),
    ])

    content, await_response, _, records = await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="turn on kitchen light")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    assert content == "Kitchen light turned on."
    assert await_response is False
    assert len(records) == 1
    entity._registry.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_tool_alarm_route_triggers_retry_nudge(monkeypatch) -> None:
    async def _fake_route_classifier(entity, user_text, assistant_text):
        return {
            "route": "alarm",
            "alarm_mode": "absolute",
            "needs_tool_retry": True,
            "confidence": "high",
            "reason": "alarm_set_intent",
        }

    monkeypatch.setattr(
        "custom_components.smart_assist.streaming._classify_missing_tool_intent_route",
        _fake_route_classifier,
    )

    entity = _FakeEntity([
        ChatResponse(content="Okay, alarm set.", tool_calls=[]),
        ChatResponse(content="Done.", tool_calls=[]),
    ])

    _, _, iterations, _ = await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="Please set an alarm for tomorrow at 06:30")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    assert iterations == 2


@pytest.mark.asyncio
async def test_malformed_tool_arguments_trigger_deterministic_correction_retry() -> None:
    malformed_call = ToolCall(
        id="t1",
        name="control",
        arguments={},
        parse_status="malformed_json",
    )
    valid_call = ToolCall(
        id="t2",
        name="control",
        arguments={"entity_id": "light.kitchen", "action": "turn_on"},
    )

    entity = _FakeEntity(
        [
            ChatResponse(content="", tool_calls=[malformed_call]),
            ChatResponse(content="", tool_calls=[valid_call]),
            ChatResponse(content="Kitchen light turned on.", tool_calls=[]),
        ]
    )

    content, await_response, iterations, records = await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="turn on kitchen light")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    assert content == "Kitchen light turned on."
    assert await_response is False
    assert iterations == 3
    assert len(records) == 1
    entity._registry.execute.assert_awaited_once()

    all_message_batches = [call.kwargs["messages"] for call in entity._llm_client.chat.await_args_list]
    system_messages = [
        msg.content
        for batch in all_message_batches
        for msg in batch
        if msg.role == MessageRole.SYSTEM
    ]
    assert any("malformed JSON" in content for content in system_messages)
    assert any("exactly one corrected tool call" in content for content in system_messages)
    assert any("Do not return free text or claim success" in content for content in system_messages)


@pytest.mark.asyncio
async def test_missing_tool_relative_snooze_requires_recent_fired_context(monkeypatch) -> None:
    async def _fake_route_classifier(entity, user_text, assistant_text):
        return {
            "route": "alarm",
            "alarm_mode": "relative_snooze",
            "needs_tool_retry": True,
            "confidence": "high",
            "reason": "relative_snooze",
        }

    monkeypatch.setattr(
        "custom_components.smart_assist.streaming._classify_missing_tool_intent_route",
        _fake_route_classifier,
    )

    entity = _FakeEntity([
        ChatResponse(content="Okay.", tool_calls=[]),
    ])

    _, _, iterations, _ = await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="snooze it a bit")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    assert iterations == 1


@pytest.mark.asyncio
async def test_implicit_area_command_prefers_single_group_entity_over_batch() -> None:
    """For implicit area commands, control batch should normalize to one preferred target."""
    tool_call = ToolCall(
        id="t1",
        name="control",
        arguments={
            "action": "turn_on",
            "entity_ids": [
                "light.kuche_steckdose_1_2",
                "light.kuche",
                "light.esstisch",
            ],
        },
    )
    entity = _FakeEntity(
        [
            ChatResponse(content="", tool_calls=[tool_call]),
            ChatResponse(content="Küche eingeschaltet.", tool_calls=[]),
        ]
    )

    # Treat light.kuche as group-like target to prefer it for implicit area requests
    entity._hass.states.get.side_effect = (
        lambda eid: MagicMock(attributes={"entity_id": ["light.a", "light.b"]})
        if eid == "light.kuche"
        else MagicMock(attributes={})
    )

    await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="Küche einschalten.")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    call_args = entity._registry.execute.await_args_list[0].args
    assert call_args[0] == "control"
    assert call_args[1]["entity_id"] == "light.kuche"
    assert "entity_ids" not in call_args[1]


@pytest.mark.asyncio
async def test_explicit_all_area_command_keeps_batch_control() -> None:
    """Explicit batch flag should preserve multi-entity control arguments."""
    tool_call = ToolCall(
        id="t1",
        name="control",
        arguments={
            "action": "turn_on",
            "batch": True,
            "entity_ids": [
                "light.kuche_steckdose_1_2",
                "light.kuche",
                "light.esstisch",
            ],
        },
    )
    entity = _FakeEntity(
        [
            ChatResponse(content="", tool_calls=[tool_call]),
            ChatResponse(content="Alle Küchenlichter eingeschaltet.", tool_calls=[]),
        ]
    )

    await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="Schalte alle Lichter in der Küche ein.")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    call_args = entity._registry.execute.await_args_list[0].args
    assert call_args[0] == "control"
    assert call_args[1]["batch"] is True
    assert "entity_ids" in call_args[1]
    assert len(call_args[1]["entity_ids"]) == 3


def test_extract_json_object_handles_code_fence_and_trailing_text() -> None:
    raw = """Here is the result:\n```json\n{\n  \"route\": \"alarm\",\n  \"alarm_mode\": \"absolute\",\n  \"needs_tool_retry\": true,\n  \"confidence\": \"high\",\n  \"reason\": \"intent_detected\"\n}\n```\nThanks."""

    parsed = _extract_json_object(raw)

    assert parsed is not None
    assert parsed["route"] == "alarm"
    assert parsed["needs_tool_retry"] is True


@pytest.mark.asyncio
async def test_conflicting_control_calls_same_target_keep_last() -> None:
    first = ToolCall(
        id="t1",
        name="control",
        arguments={"entity_id": "light.keller", "action": "turn_on"},
    )
    second = ToolCall(
        id="t2",
        name="control",
        arguments={"entity_id": "light.keller", "action": "turn_off"},
    )

    entity = _FakeEntity(
        [
            ChatResponse(content="", tool_calls=[first, second]),
            ChatResponse(content="Keller aus.", tool_calls=[]),
        ]
    )

    await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="Schalte Kellerlicht aus.")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    assert entity._registry.execute.await_count == 1
    call_args = entity._registry.execute.await_args_list[0].args
    assert call_args[0] == "control"
    assert call_args[1]["entity_id"] == "light.keller"
    assert call_args[1]["action"] == "turn_off"


@pytest.mark.asyncio
async def test_textual_await_response_output_retries_until_real_tool_call() -> None:
    entity = _FakeEntity(
        [
            ChatResponse(
                content='await_response(message="Ich habe keinen Schalter namens Teller gefunden.", reason="clarification")',
                tool_calls=[],
            ),
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="a1",
                        name="await_response",
                        arguments={
                            "message": "Ich habe keinen Schalter namens Teller gefunden.",
                            "reason": "clarification",
                        },
                    )
                ],
            ),
        ]
    )

    content, await_response, iterations, records = await call_llm_streaming_with_tools(
        entity=entity,
        messages=[ChatMessage(role=MessageRole.USER, content="Schalte den Teller aus.")],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    assert content == "Ich habe keinen Schalter namens Teller gefunden."
    assert await_response is True
    assert iterations == 2
    assert records == []

    all_message_batches = [call.kwargs["messages"] for call in entity._llm_client.chat.await_args_list]
    system_messages = [
        msg.content
        for batch in all_message_batches
        for msg in batch
        if msg.role == MessageRole.SYSTEM
    ]
    assert any("Do not output await_response(...) as plain text" in content for content in system_messages)
    assert any("exactly one await_response tool call" in content for content in system_messages)


@pytest.mark.asyncio
async def test_provider_chat_error_propagates_without_provider_specific_retry() -> None:
    err = LLMError("Provider request failed", status_code=400)
    entity = _FakeEntity(
        [
            ChatResponse(content="", tool_calls=[ToolCall(id="w1", name="local_web_search", arguments={"query": "q"})]),
            err,
        ]
    )

    with pytest.raises(LLMError):
        await call_llm_streaming_with_tools(
            entity=entity,
            messages=[ChatMessage(role=MessageRole.USER, content="Bitte such das im Web")],
            tools=[],
            cached_prefix_length=0,
            chat_log=_FakeChatLog(),
            conversation_id="conv1",
        )


@pytest.mark.asyncio
async def test_repeated_local_web_search_missing_query_forces_final_answer() -> None:
    entity = _FakeEntity(
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCall(id="w1", name="local_web_search", arguments={"query": "Das perfekte Dinner heute neu oder Wiederholung"})
                ],
            ),
            ChatResponse(
                content="",
                tool_calls=[ToolCall(id="w2", name="local_web_search", arguments={"cursor": 2, "id": 2})],
            ),
            ChatResponse(
                content="",
                tool_calls=[ToolCall(id="w3", name="local_web_search", arguments={"cursor": 3, "id": 2})],
            ),
            ChatResponse(content="Laut den gefundenen Quellen ist es heute voraussichtlich eine Wiederholung.", tool_calls=[]),
        ]
    )

    async def _execute_side_effect(name, arguments, **kwargs):
        if name == "local_web_search" and "query" in arguments:
            return ToolResult(success=True, message="Search results for 'test':\n- Treffer")
        if name == "local_web_search":
            return ToolResult(success=False, message="Search failed: missing query text.")
        return ToolResult(success=True, message="OK")

    entity._registry.execute = AsyncMock(side_effect=_execute_side_effect)

    content, await_response, iterations, records = await call_llm_streaming_with_tools(
        entity=entity,
        messages=[
            ChatMessage(
                role=MessageRole.USER,
                content="Ist die heutige Das perfekte Dinner Folge neu oder Wiederholung?",
            )
        ],
        tools=[],
        cached_prefix_length=0,
        chat_log=_FakeChatLog(),
        conversation_id="conv1",
    )

    assert await_response is False
    assert iterations == 3
    assert len(records) == 3
    assert "wiederholung" in content.lower()
