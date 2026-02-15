"""Tests for Smart Assist AI Task entity."""

from __future__ import annotations

import asyncio
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.smart_assist.llm.models import (
    ChatMessage,
    ChatResponse,
    MessageRole,
    ToolCall,
)
from custom_components.smart_assist.tools.base import ToolResult


if "turbojpeg" not in sys.modules:
    turbojpeg_stub = types.ModuleType("turbojpeg")

    class _TurboJPEG:  # pragma: no cover - test import shim
        pass

    turbojpeg_stub.TurboJPEG = _TurboJPEG
    sys.modules["turbojpeg"] = turbojpeg_stub


class TestBuildMessages:
    """Test _build_messages method of SmartAssistAITask."""

    def _create_task_entity(self, **config_overrides):
        """Create a SmartAssistAITask with mocked dependencies."""
        from custom_components.smart_assist.ai_task import SmartAssistAITask

        hass = MagicMock()
        hass.config.language = "en-US"
        hass.data = {"smart_assist": {"test_entry": {"tasks": {}}}}
        hass.async_create_task = lambda coro: coro.close()
        hass.async_create_task = lambda coro: coro.close()

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.data = {"api_key": "test_key"}
        config_entry.options = {}

        subentry = MagicMock()
        subentry.subentry_id = "test_sub"
        subentry.title = "Test Task"
        subentry.data = {
            "model": "openai/gpt-4o-mini",
            "temperature": 0.5,
            "max_tokens": 500,
            "llm_provider": "openrouter",
            **config_overrides,
        }

        with patch(
            "custom_components.smart_assist.ai_task.create_llm_client"
        ) as mock_create, patch(
            "custom_components.smart_assist.ai_task.EntityManager"
        ) as mock_em, patch(
            "custom_components.smart_assist.ai_task.create_tool_registry"
        ) as mock_tr:
            mock_create.return_value = MagicMock()
            mock_em_instance = MagicMock()
            mock_em_instance.get_entity_index.return_value = (
                "light.living_room: Living Room Light\nswitch.kitchen: Kitchen Switch",
                "abc123",
            )
            mock_em.return_value = mock_em_instance
            mock_tr.return_value = MagicMock()

            entity = SmartAssistAITask(hass, config_entry, subentry)

        return entity

    def test_entity_index_tuple_unpacking(self):
        """Test that entity index tuple is properly unpacked (only text used)."""
        entity = self._create_task_entity()
        messages = entity._build_messages("Turn on the lights")

        # System prompt should contain the entity text, not the tuple
        system_content = messages[0].content
        assert "light.living_room" in system_content
        assert "abc123" not in system_content
        # Should NOT contain tuple repr like "('light...', 'abc123')"
        assert "('light" not in system_content

    def test_message_structure(self):
        """Test that messages have correct structure."""
        entity = self._create_task_entity()
        messages = entity._build_messages("Do something")

        assert len(messages) == 2
        assert messages[0].role == MessageRole.SYSTEM
        assert messages[1].role == MessageRole.USER
        assert messages[1].content == "Do something"

    def test_auto_language_detection(self):
        """Test auto language detection from HA config."""
        entity = self._create_task_entity(language="auto")
        entity.hass.config.language = "de-DE"

        messages = entity._build_messages("Test")
        system_content = messages[0].content
        assert "German" in system_content or "Deutsch" in system_content

    def test_explicit_language(self):
        """Test explicit language setting."""
        entity = self._create_task_entity(language="French")
        messages = entity._build_messages("Test")
        system_content = messages[0].content
        assert "French" in system_content

    def test_system_prompt_customization(self):
        """Test custom system prompt is used."""
        entity = self._create_task_entity(
            task_system_prompt="You are a custom task bot."
        )
        messages = entity._build_messages("Test")
        assert "custom task bot" in messages[0].content


class TestProcessWithTools:
    """Test _process_with_tools method (tool execution loop)."""

    def _create_task_entity(self, **config_overrides):
        """Create entity with mocked LLM client and tool registry."""
        from custom_components.smart_assist.ai_task import SmartAssistAITask

        hass = MagicMock()
        hass.config.language = "en-US"
        hass.data = {"smart_assist": {"test_entry": {"tasks": {}}}}
        hass.async_create_task = lambda coro: coro.close()

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.data = {"api_key": "test_key"}
        config_entry.options = {}

        subentry = MagicMock()
        subentry.subentry_id = "test_sub"
        subentry.title = "Test Task"
        subentry.data = {
            "model": "openai/gpt-4o-mini",
            "temperature": 0.5,
            "max_tokens": 500,
            "llm_provider": "openrouter",
            **config_overrides,
        }

        with patch(
            "custom_components.smart_assist.ai_task.create_llm_client"
        ) as mock_create, patch(
            "custom_components.smart_assist.ai_task.EntityManager"
        ) as mock_em, patch(
            "custom_components.smart_assist.ai_task.create_tool_registry"
        ) as mock_tr:
            mock_llm = AsyncMock()
            mock_create.return_value = mock_llm
            mock_em.return_value = MagicMock()
            mock_em.return_value.get_entity_index.return_value = ("entities", "hash")
            mock_registry = MagicMock()
            mock_registry.execute = AsyncMock()
            mock_tr.return_value = mock_registry

            entity = SmartAssistAITask(hass, config_entry, subentry)

        return entity

    @pytest.mark.asyncio
    async def test_no_tool_calls(self):
        """Test simple response without tool calls."""
        entity = self._create_task_entity()
        entity._llm_client.chat = AsyncMock(
            return_value=ChatResponse(
                content="The answer is 42",
                tool_calls=[],
            )
        )

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content="System prompt"),
            ChatMessage(role=MessageRole.USER, content="What is the answer?"),
        ]

        result = await entity._process_with_tools(messages, [])
        assert result == "The answer is 42"
        entity._llm_client.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_tool_call(self):
        """Test response with one tool call followed by final response."""
        entity = self._create_task_entity()

        tool_call = ToolCall(id="tc1", name="control", arguments={"entity_id": "light.test", "action": "turn_on"})

        # First call: LLM returns a tool call
        # Second call: LLM returns final answer
        entity._llm_client.chat = AsyncMock(
            side_effect=[
                ChatResponse(content="", tool_calls=[tool_call]),
                ChatResponse(content="Light turned on.", tool_calls=[]),
            ]
        )

        entity._tool_registry.execute = AsyncMock(
            return_value=ToolResult(success=True, message="OK")
        )

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content="System"),
            ChatMessage(role=MessageRole.USER, content="Turn on the light"),
        ]

        result = await entity._process_with_tools(messages, [])
        assert result == "Light turned on."
        assert entity._llm_client.chat.call_count == 2
        entity._tool_registry.execute.assert_called_once()
        call_args = entity._tool_registry.execute.call_args
        assert call_args.args[0] == "control"
        assert call_args.args[1] == {"entity_id": "light.test", "action": "turn_on"}
        assert "max_retries" in call_args.kwargs
        assert "latency_budget_ms" in call_args.kwargs

    @pytest.mark.asyncio
    async def test_tool_execution_failure_sends_error_to_llm(self):
        """Test that failed tool execution still sends error message to LLM."""
        entity = self._create_task_entity()

        tool_call = ToolCall(id="tc1", name="control", arguments={"entity_id": "light.test"})

        entity._llm_client.chat = AsyncMock(
            side_effect=[
                ChatResponse(content="", tool_calls=[tool_call]),
                ChatResponse(content="Sorry, the light could not be controlled.", tool_calls=[]),
            ]
        )

        # Tool raises an exception
        entity._tool_registry.execute = AsyncMock(
            side_effect=RuntimeError("Service not found")
        )

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content="System"),
            ChatMessage(role=MessageRole.USER, content="Turn on the light"),
        ]

        result = await entity._process_with_tools(messages, [])

        # Should still get a response (LLM receives the error and responds)
        assert result == "Sorry, the light could not be controlled."

        # Verify error message was added to messages
        # Messages should have: system, user, assistant (with tool_call), tool (error), then second LLM call adds nothing
        # The second LLM call's messages arg should contain the error tool message
        second_call_messages = entity._llm_client.chat.call_args_list[1][1].get(
            "messages", entity._llm_client.chat.call_args_list[1][0][0]
        )
        tool_messages = [m for m in second_call_messages if m.role == MessageRole.TOOL]
        assert len(tool_messages) == 1
        assert "Error:" in tool_messages[0].content
        assert tool_messages[0].tool_call_id == "tc1"

    @pytest.mark.asyncio
    async def test_max_iterations_limit(self):
        """Test that tool loop respects max_iterations."""
        entity = self._create_task_entity()

        tool_call = ToolCall(id="tc1", name="control", arguments={})

        # LLM always returns tool calls (infinite loop scenario)
        entity._llm_client.chat = AsyncMock(
            return_value=ChatResponse(content="Still working...", tool_calls=[tool_call])
        )
        entity._tool_registry.execute = AsyncMock(
            return_value=ToolResult(success=True, message="Done")
        )

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content="System"),
            ChatMessage(role=MessageRole.USER, content="Do something"),
        ]

        result = await entity._process_with_tools(messages, [], max_iterations=3)
        assert entity._llm_client.chat.call_count == 3
        assert result == "Still working..."

    @pytest.mark.asyncio
    async def test_multiple_parallel_tool_calls(self):
        """Test concurrent execution of multiple tool calls."""
        entity = self._create_task_entity()

        tc1 = ToolCall(id="tc1", name="control", arguments={"entity_id": "light.a"})
        tc2 = ToolCall(id="tc2", name="control", arguments={"entity_id": "light.b"})

        entity._llm_client.chat = AsyncMock(
            side_effect=[
                ChatResponse(content="", tool_calls=[tc1, tc2]),
                ChatResponse(content="Both lights turned on.", tool_calls=[]),
            ]
        )

        call_order = []

        async def mock_execute(name, args):
            call_order.append(args.get("entity_id"))
            return ToolResult(success=True, message="OK")

        entity._tool_registry.execute = mock_execute

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content="System"),
            ChatMessage(role=MessageRole.USER, content="Turn on both lights"),
        ]

        result = await entity._process_with_tools(messages, [])
        assert result == "Both lights turned on."
        assert set(call_order) == {"light.a", "light.b"}

    @pytest.mark.asyncio
    async def test_ai_task_blocks_control_when_opt_in_disabled(self):
        """Control tool calls are blocked when task_allow_control is disabled."""
        entity = self._create_task_entity(
            task_allow_control=False,
            task_allow_lock_control=False,
        )

        tool_call = ToolCall(
            id="tc1",
            name="control",
            arguments={"entity_id": "light.kitchen", "action": "turn_on"},
        )
        entity._llm_client.chat = AsyncMock(
            side_effect=[
                ChatResponse(content="", tool_calls=[tool_call]),
                ChatResponse(content="Control blocked.", tool_calls=[]),
            ]
        )

        result = await entity._process_with_tools(
            [
                ChatMessage(role=MessageRole.SYSTEM, content="System"),
                ChatMessage(role=MessageRole.USER, content="Turn on kitchen light"),
            ],
            [],
        )

        assert result == "Control blocked."
        entity._tool_registry.execute.assert_not_called()
        second_messages = entity._llm_client.chat.call_args_list[1].kwargs["messages"]
        tool_messages = [m for m in second_messages if m.role == MessageRole.TOOL]
        assert any("disabled" in m.content.lower() for m in tool_messages)

    @pytest.mark.asyncio
    async def test_ai_task_blocks_lock_domain_when_lock_toggle_disabled(self):
        """Lock domain control is blocked when lock toggle is disabled."""
        entity = self._create_task_entity(
            task_allow_control=True,
            task_allow_lock_control=False,
        )

        tool_call = ToolCall(
            id="tc1",
            name="control",
            arguments={"entity_id": "lock.front_door", "action": "unlock"},
        )
        entity._llm_client.chat = AsyncMock(
            side_effect=[
                ChatResponse(content="", tool_calls=[tool_call]),
                ChatResponse(content="Lock blocked.", tool_calls=[]),
            ]
        )

        result = await entity._process_with_tools(
            [
                ChatMessage(role=MessageRole.SYSTEM, content="System"),
                ChatMessage(role=MessageRole.USER, content="Unlock front door"),
            ],
            [],
        )

        assert result == "Lock blocked."
        entity._tool_registry.execute.assert_not_called()
        second_messages = entity._llm_client.chat.call_args_list[1].kwargs["messages"]
        tool_messages = [m for m in second_messages if m.role == MessageRole.TOOL]
        assert any("lock" in m.content.lower() and "disabled" in m.content.lower() for m in tool_messages)

    @pytest.mark.asyncio
    async def test_ai_task_allows_non_lock_control_when_lock_toggle_disabled(self):
        """Non-lock control executes when control is enabled and lock-only toggle is disabled."""
        entity = self._create_task_entity(
            task_allow_control=True,
            task_allow_lock_control=False,
        )

        tool_call = ToolCall(
            id="tc1",
            name="control",
            arguments={"entity_id": "light.kitchen", "action": "turn_on"},
        )
        entity._llm_client.chat = AsyncMock(
            side_effect=[
                ChatResponse(content="", tool_calls=[tool_call]),
                ChatResponse(content="Light updated.", tool_calls=[]),
            ]
        )
        entity._tool_registry.execute = AsyncMock(
            return_value=ToolResult(success=True, message="OK")
        )
        result = await entity._process_with_tools(
            [
                ChatMessage(role=MessageRole.SYSTEM, content="System"),
                ChatMessage(role=MessageRole.USER, content="Turn on kitchen light"),
            ],
            [],
        )

        assert result == "Light updated."
        entity._tool_registry.execute.assert_awaited_once()
        assert entity._tool_registry.execute.await_args.args[0] == "control"

    @pytest.mark.asyncio
    async def test_ai_task_allows_lock_control_when_both_toggles_enabled(self):
        """Lock control executes when both toggles are enabled."""
        entity = self._create_task_entity(
            task_allow_control=True,
            task_allow_lock_control=True,
        )

        tool_call = ToolCall(
            id="tc1",
            name="control",
            arguments={"entity_id": "lock.front_door", "action": "unlock"},
        )
        entity._llm_client.chat = AsyncMock(
            side_effect=[
                ChatResponse(content="", tool_calls=[tool_call]),
                ChatResponse(content="Door unlocked.", tool_calls=[]),
            ]
        )
        entity._tool_registry.execute = AsyncMock(
            return_value=ToolResult(success=True, message="Unlocked")
        )
        result = await entity._process_with_tools(
            [
                ChatMessage(role=MessageRole.SYSTEM, content="System"),
                ChatMessage(role=MessageRole.USER, content="Unlock front door"),
            ],
            [],
        )

        assert result == "Door unlocked."
        entity._tool_registry.execute.assert_awaited_once()
        assert entity._tool_registry.execute.await_args.args[1]["entity_id"] == "lock.front_door"


class TestTaskToolRegistryInitialization:
    """Test AI Task tool registry initialization behavior."""

    def test_tool_registry_receives_subentry_data_in_ai_task_init(self):
        """AI Task initialization passes subentry data into create_tool_registry."""
        from custom_components.smart_assist.ai_task import SmartAssistAITask

        hass = MagicMock()
        hass.config.language = "en-US"
        hass.data = {"smart_assist": {"test_entry": {"tasks": {}}}}

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.data = {"api_key": "test_key"}
        config_entry.options = {}

        subentry = MagicMock()
        subentry.subentry_id = "test_sub"
        subentry.title = "Test Task"
        subentry.data = {
            "model": "openai/gpt-4o-mini",
            "temperature": 0.5,
            "max_tokens": 500,
            "llm_provider": "openrouter",
            "task_allow_control": True,
        }

        with patch(
            "custom_components.smart_assist.ai_task.create_llm_client"
        ) as mock_create, patch(
            "custom_components.smart_assist.ai_task.EntityManager"
        ) as mock_em, patch(
            "custom_components.smart_assist.ai_task.create_tool_registry"
        ) as mock_tr:
            mock_create.return_value = MagicMock()
            mock_em.return_value = MagicMock()
            mock_em.return_value.get_entity_index.return_value = ("entities", "hash")
            mock_tr.return_value = MagicMock()

            SmartAssistAITask(hass, config_entry, subentry)

        assert mock_tr.call_count == 1
        assert mock_tr.call_args.kwargs["subentry_data"] == subentry.data


class TestTaskControlDomainDetection:
    """Test lock-domain detection helper for AI Task control gating."""

    def test_targets_lock_domain_handles_nested_targets(self):
        """Nested targets payloads are parsed for lock-domain detection."""
        from custom_components.smart_assist.ai_task import _targets_lock_domain

        assert _targets_lock_domain(
            {
                "targets": {
                    "entity_ids": ["lock.front_door", "light.kitchen"],
                }
            }
        )
        assert not _targets_lock_domain(
            {
                "targets": {
                    "entity_ids": ["light.kitchen", "switch.garage"],
                }
            }
        )


class TestTaskInitialState:
    """Test initial entity state behavior for AI Task entities."""

    @pytest.mark.asyncio
    async def test_ai_task_sets_ready_state_on_add_when_empty(self):
        """Entity should expose a deterministic state instead of unknown on first add."""
        from custom_components.smart_assist.ai_task import SmartAssistAITask

        hass = MagicMock()
        hass.config.language = "en-US"
        hass.data = {"smart_assist": {"test_entry": {"tasks": {}}}}

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.data = {"api_key": "test_key"}
        config_entry.options = {}

        subentry = MagicMock()
        subentry.subentry_id = "test_sub"
        subentry.title = "Test Task"
        subentry.data = {
            "model": "openai/gpt-4o-mini",
            "temperature": 0.5,
            "max_tokens": 500,
            "llm_provider": "openrouter",
        }

        with patch(
            "custom_components.smart_assist.ai_task.create_llm_client"
        ) as mock_create, patch(
            "custom_components.smart_assist.ai_task.EntityManager"
        ) as mock_em, patch(
            "custom_components.smart_assist.ai_task.create_tool_registry"
        ) as mock_tr, patch(
            "homeassistant.components.ai_task.entity.AITaskEntity.async_added_to_hass",
            new=AsyncMock(),
        ):
            mock_create.return_value = MagicMock()
            mock_em.return_value = MagicMock()
            mock_em.return_value.get_entity_index.return_value = ("entities", "hash")
            mock_tr.return_value = MagicMock()

            entity = SmartAssistAITask(hass, config_entry, subentry)
            entity.async_write_ha_state = MagicMock()

            assert entity.state is None

            await entity.async_added_to_hass()

            assert entity.state == "ready"
            entity.async_write_ha_state.assert_called_once()


class TestGenerateDataErrorSanitization:
    """Ensure task generate-data path does not leak raw backend payloads."""

    def _create_task_entity(self):
        from custom_components.smart_assist.ai_task import SmartAssistAITask

        hass = MagicMock()
        hass.config.language = "en-US"
        hass.data = {"smart_assist": {"test_entry": {"tasks": {}}}}

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.data = {"api_key": "test_key"}
        config_entry.options = {}

        subentry = MagicMock()
        subentry.subentry_id = "test_sub"
        subentry.title = "Test Task"
        subentry.data = {
            "model": "openai/gpt-4o-mini",
            "temperature": 0.5,
            "max_tokens": 500,
            "llm_provider": "openrouter",
        }

        with patch(
            "custom_components.smart_assist.ai_task.create_llm_client"
        ) as mock_create, patch(
            "custom_components.smart_assist.ai_task.EntityManager"
        ) as mock_em, patch(
            "custom_components.smart_assist.ai_task.create_tool_registry"
        ) as mock_tr:
            mock_create.return_value = MagicMock()
            mock_em.return_value = MagicMock()
            mock_em.return_value.get_entity_index.return_value = ("entities", "hash")
            mock_tr.return_value = MagicMock()

            return SmartAssistAITask(hass, config_entry, subentry)

    @pytest.mark.asyncio
    async def test_async_generate_data_sanitizes_raw_backend_error(self):
        entity = self._create_task_entity()
        entity._process_with_tools = AsyncMock(
            side_effect=RuntimeError('API error: 500 - {"error":"provider exploded","trace":"stack details"}')
        )

        task = MagicMock()
        task.task_name = "test"
        task.instructions = "do x"
        task.structure = None
        chat_log = MagicMock()
        chat_log.conversation_id = "conv1"

        result = await entity._async_generate_data(task, chat_log)

        assert isinstance(result.data, str)
        assert "provider exploded" not in result.data
        assert "stack details" not in result.data

    @pytest.mark.asyncio
    async def test_async_generate_data_handles_empty_instructions(self):
        entity = self._create_task_entity()
        entity._process_with_tools = AsyncMock()

        task = MagicMock()
        task.task_name = "test"
        task.instructions = None
        task.structure = None
        chat_log = MagicMock()
        chat_log.conversation_id = "conv1"

        result = await entity._async_generate_data(task, chat_log)

        assert isinstance(result.data, str)
        assert "instructions are empty" in result.data.lower()
        entity._process_with_tools.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_async_generate_data_handles_missing_task_name_attr(self):
        entity = self._create_task_entity()
        entity._process_with_tools = AsyncMock(return_value="OK")

        task = MagicMock(spec=["instructions", "structure"])
        task.instructions = "turn on cellar light"
        task.structure = None
        chat_log = MagicMock()
        chat_log.conversation_id = "conv1"

        result = await entity._async_generate_data(task, chat_log)

        assert isinstance(result.data, str)
        assert result.data == "OK"
        entity._process_with_tools.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_generate_data_writes_request_history_entry(self):
        entity = self._create_task_entity()
        entity._process_with_tools = AsyncMock(return_value="OK")

        history_store = MagicMock()
        history_store.prune_older_than_days = MagicMock()
        history_store.add_entry = MagicMock()
        history_store.async_save = AsyncMock()
        entity.hass.data["smart_assist"]["test_entry"]["request_history"] = history_store

        task = MagicMock()
        task.task_name = "test"
        task.instructions = "turn on cellar light"
        task.structure = None
        chat_log = MagicMock()
        chat_log.conversation_id = "conv1"

        result = await entity._async_generate_data(task, chat_log)

        assert isinstance(result.data, str)
        assert result.data == "OK"
        history_store.add_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_generate_data_records_failed_history_entry_on_exception(self):
        entity = self._create_task_entity()
        entity._process_with_tools = AsyncMock(side_effect=RuntimeError("provider failed"))

        history_store = MagicMock()
        history_store.prune_older_than_days = MagicMock()
        history_store.add_entry = MagicMock()
        history_store.async_save = AsyncMock()
        entity.hass.data["smart_assist"]["test_entry"]["request_history"] = history_store

        task = MagicMock()
        task.task_name = "test"
        task.instructions = "run task"
        task.structure = None
        chat_log = MagicMock()
        chat_log.conversation_id = "conv1"

        result = await entity._async_generate_data(task, chat_log)

        assert isinstance(result.data, str)
        history_store.add_entry.assert_called_once()
        added_entry = history_store.add_entry.call_args.args[0]
        assert added_entry.success is False
        assert isinstance(added_entry.error, str)
        assert added_entry.error

    @pytest.mark.asyncio
    async def test_async_generate_data_records_success_history_entry_on_success(self):
        entity = self._create_task_entity()
        entity._process_with_tools = AsyncMock(return_value="done")

        history_store = MagicMock()
        history_store.prune_older_than_days = MagicMock()
        history_store.add_entry = MagicMock()
        history_store.async_save = AsyncMock()
        entity.hass.data["smart_assist"]["test_entry"]["request_history"] = history_store

        task = MagicMock()
        task.task_name = "test"
        task.instructions = "run task"
        task.structure = None
        chat_log = MagicMock()
        chat_log.conversation_id = "conv1"

        await entity._async_generate_data(task, chat_log)

        added_entry = history_store.add_entry.call_args.args[0]
        assert added_entry.success is True
        assert added_entry.error is None

    @pytest.mark.asyncio
    async def test_process_with_tools_records_execution_time_metadata(self):
        entity = self._create_task_entity()
        entity._subentry.data["task_allow_control"] = True

        tool_call = ToolCall(
            id="tc1",
            name="control",
            arguments={"entity_id": "light.kitchen", "action": "turn_on"},
        )
        entity._llm_client.chat = AsyncMock(
            side_effect=[
                ChatResponse(content="", tool_calls=[tool_call]),
                ChatResponse(content="done", tool_calls=[]),
            ]
        )
        entity._tool_registry.execute = AsyncMock(
            return_value=ToolResult(
                success=True,
                message="OK",
                data={"execution_time_ms": 12.5, "timed_out": False, "retries_used": 0},
            )
        )

        result = await entity._process_with_tools(
            [
                ChatMessage(role=MessageRole.SYSTEM, content="System"),
                ChatMessage(role=MessageRole.USER, content="Turn on kitchen light"),
            ],
            [],
        )

        assert result == "done"
        assert len(entity._last_tool_call_records) == 1
        assert entity._last_tool_call_records[0].execution_time_ms > 0


class TestStructuredGenerateData:
    """Structured output behavior for AI Task generate-data."""

    def _create_task_entity(self, language: str = "en"):
        from custom_components.smart_assist.ai_task import SmartAssistAITask

        hass = MagicMock()
        hass.config.language = "de-DE" if language == "de" else "en-US"
        hass.data = {"smart_assist": {"test_entry": {"tasks": {}}}}
        hass.async_create_task = lambda coro: coro.close()

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.data = {"api_key": "test_key"}
        config_entry.options = {}

        subentry = MagicMock()
        subentry.subentry_id = "test_sub"
        subentry.title = "Test Task"
        subentry.data = {
            "model": "openai/gpt-4o-mini",
            "temperature": 0.5,
            "max_tokens": 500,
            "llm_provider": "openrouter",
        }

        with patch(
            "custom_components.smart_assist.ai_task.create_llm_client"
        ) as mock_create, patch(
            "custom_components.smart_assist.ai_task.EntityManager"
        ) as mock_em, patch(
            "custom_components.smart_assist.ai_task.create_tool_registry"
        ) as mock_tr:
            mock_create.return_value = MagicMock()
            mock_em.return_value = MagicMock()
            mock_em.return_value.get_entity_index.return_value = ("entities", "hash")
            mock_registry = MagicMock()
            mock_registry.get_schemas.return_value = []
            mock_tr.return_value = mock_registry

            return SmartAssistAITask(hass, config_entry, subentry)

    @pytest.mark.asyncio
    async def test_generate_data_structured_success_returns_validated_object(self):
        entity = self._create_task_entity()
        entity._process_with_tools = AsyncMock(
            return_value='{"summary": "ok", "count": 2}'
        )

        task = MagicMock()
        task.task_name = "summary"
        task.instructions = "Summarize"
        task.structure = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["summary", "count"],
            "additionalProperties": False,
        }
        chat_log = MagicMock()
        chat_log.conversation_id = "conv1"

        result = await entity._async_generate_data(task, chat_log)

        assert isinstance(result.data, dict)
        assert result.data["summary"] == "ok"
        assert result.data["count"] == 2

    @pytest.mark.asyncio
    async def test_generate_data_structured_extracts_json_from_fenced_block(self):
        entity = self._create_task_entity()
        entity._process_with_tools = AsyncMock(
            return_value='```json\n{"state": "on", "confidence": 0.92}\n```'
        )

        task = MagicMock()
        task.task_name = "state"
        task.instructions = "Analyze"
        task.structure = {
            "type": "object",
            "properties": {
                "state": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["state", "confidence"],
        }
        chat_log = MagicMock()
        chat_log.conversation_id = "conv1"

        result = await entity._async_generate_data(task, chat_log)

        assert isinstance(result.data, dict)
        assert result.data["state"] == "on"

    @pytest.mark.asyncio
    async def test_generate_data_structured_invalid_json_returns_localized_error(self):
        entity = self._create_task_entity(language="de")
        entity._process_with_tools = AsyncMock(return_value="not json")

        task = MagicMock()
        task.task_name = "summary"
        task.instructions = "Summarize"
        task.structure = {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        }
        chat_log = MagicMock()
        chat_log.conversation_id = "conv1"

        result = await entity._async_generate_data(task, chat_log)

        assert isinstance(result.data, str)
        assert "strukturierte" in result.data.lower()

    @pytest.mark.asyncio
    async def test_generate_data_structured_schema_mismatch_returns_localized_error(self):
        entity = self._create_task_entity()
        entity._process_with_tools = AsyncMock(return_value='{"summary": 42}')

        task = MagicMock()
        task.task_name = "summary"
        task.instructions = "Summarize"
        task.structure = {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        }
        chat_log = MagicMock()
        chat_log.conversation_id = "conv1"

        result = await entity._async_generate_data(task, chat_log)

        assert isinstance(result.data, str)
        assert "required format" in result.data.lower()

    @pytest.mark.asyncio
    async def test_generate_data_unstructured_path_unchanged(self):
        entity = self._create_task_entity()
        entity._process_with_tools = AsyncMock(return_value="plain text result")

        task = MagicMock()
        task.task_name = "summary"
        task.instructions = "Summarize"
        task.structure = None
        chat_log = MagicMock()
        chat_log.conversation_id = "conv1"

        result = await entity._async_generate_data(task, chat_log)

        assert result.data == "plain text result"

    @pytest.mark.asyncio
    async def test_generate_data_structured_provider_native_failure_falls_back_and_succeeds(self):
        entity = self._create_task_entity()
        entity._llm_client.chat = AsyncMock(
            side_effect=[
                RuntimeError("native structured unsupported"),
                ChatResponse(content='{"ok": true}', tool_calls=[]),
            ]
        )

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content="System"),
            ChatMessage(role=MessageRole.USER, content="Do it"),
        ]

        result = await entity._process_with_tools(
            messages=messages,
            tools=[],
            response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            response_schema_name="native_retry",
            use_native_structured_output=True,
            allow_structured_native_fallback_retry=True,
        )

        assert result == '{"ok": true}'
        assert entity._llm_client.chat.call_count == 2
        first_kwargs = entity._llm_client.chat.call_args_list[0].kwargs
        second_kwargs = entity._llm_client.chat.call_args_list[1].kwargs
        assert first_kwargs["use_native_structured_output"] is True
        assert second_kwargs["use_native_structured_output"] is False
