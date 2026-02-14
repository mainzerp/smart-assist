"""AI Task entity for Smart Assist - enables LLM usage in automations."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, TYPE_CHECKING

from homeassistant.components.ai_task import (
    AITaskEntity,
    AITaskEntityFeature,
    GenDataTask,
    GenDataTaskResult,
)
from homeassistant.components.conversation import ChatLog
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_API_KEY,
    CONF_EXPOSED_ONLY,
    CONF_ENABLE_REQUEST_HISTORY_CONTENT,
    CONF_GROQ_API_KEY,
    CONF_HISTORY_RETENTION_DAYS,
    CONF_LANGUAGE,
    CONF_LLM_PROVIDER,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_PROVIDER,
    CONF_TASK_ALLOW_CONTROL,
    CONF_TASK_ALLOW_LOCK_CONTROL,
    CONF_TASK_SYSTEM_PROMPT,
    CONF_TEMPERATURE,
    CONF_TOOL_LATENCY_BUDGET_MS,
    CONF_TOOL_MAX_RETRIES,
    DEFAULT_TASK_ALLOW_CONTROL,
    DEFAULT_TASK_ALLOW_LOCK_CONTROL,
    DEFAULT_ENABLE_REQUEST_HISTORY_CONTENT,
    DEFAULT_HISTORY_RETENTION_DAYS,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TASK_SYSTEM_PROMPT,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOOL_LATENCY_BUDGET_MS,
    DEFAULT_TOOL_MAX_RETRIES,
    DOMAIN,
    LLM_PROVIDER_GROQ,
    LOCALE_TO_LANGUAGE,
    REQUEST_HISTORY_INPUT_MAX_LENGTH,
    REQUEST_HISTORY_RESPONSE_MAX_LENGTH,
    REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH,
)
from .context.entity_manager import EntityManager
from .context.request_history import RequestHistoryEntry, RequestHistoryStore, ToolCallRecord
from .llm import OpenRouterClient, GroqClient, create_llm_client
from .llm.models import ChatMessage, MessageRole
from .tools import create_tool_registry
from .utils import get_config_value, sanitize_user_facing_error

_LOGGER = logging.getLogger(__name__)


def _extract_target_domains(arguments: dict[str, Any]) -> set[str]:
    """Extract target domains from control-tool arguments."""
    domains: set[str] = set()

    def _collect_entity_like(value: Any) -> None:
        if isinstance(value, str):
            if "." in value:
                domains.add(value.split(".", 1)[0])
            return

        if isinstance(value, list):
            for item in value:
                _collect_entity_like(item)
            return

        if isinstance(value, dict):
            for key in ("entity_id", "entity_ids", "target", "targets", "entity"):
                if key in value:
                    _collect_entity_like(value[key])

    for key in ("entity_id", "entity_ids", "target", "targets", "entity"):
        if key in arguments:
            _collect_entity_like(arguments[key])

    explicit_domain = arguments.get("domain")
    if isinstance(explicit_domain, str) and explicit_domain:
        domains.add(explicit_domain)

    return domains


def _targets_lock_domain(arguments: dict[str, Any]) -> bool:
    """Return True if a control call targets lock domain."""
    return "lock" in _extract_target_domains(arguments)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entities from config entry subentries."""
    _LOGGER.debug("Smart Assist: Setting up AI Task entities from subentries")
    
    for subentry_id, subentry in config_entry.subentries.items():
        if subentry.subentry_type != "ai_task":
            continue
        
        _LOGGER.debug("Smart Assist: Creating AI Task entity for subentry %s", subentry_id)
        async_add_entities(
            [SmartAssistAITask(hass, config_entry, subentry)],
            config_subentry_id=subentry_id,
        )


class SmartAssistAITask(AITaskEntity):
    """AI Task entity for Smart Assist.
    
    Each entity is created from a subentry configuration, allowing
    multiple AI Tasks with different settings.
    """

    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_supported_features = AITaskEntityFeature.GENERATE_DATA

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the AI Task entity."""
        self.hass = hass
        self._config_entry = config_entry
        self._subentry = subentry
        
        # Unique ID based on subentry
        self._attr_unique_id = subentry.subentry_id
        
        # Device info for proper UI display
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Smart Assist",
            model="AI Task",
            entry_type=dr.DeviceEntryType.SERVICE,
        )
        
        # Helper to get config values from subentry using centralized utility
        def get_config(key: str, default: Any = None) -> Any:
            """Get config value from subentry data."""
            return get_config_value(subentry, key, default)
        
        self._get_config = get_config
        
        # Determine LLM provider and API key
        llm_provider = get_config(CONF_LLM_PROVIDER, DEFAULT_LLM_PROVIDER)
        
        if llm_provider == LLM_PROVIDER_GROQ:
            # Use Groq API key from subentry or main entry
            api_key = get_config(CONF_GROQ_API_KEY) or get_config_value(config_entry, CONF_GROQ_API_KEY, "")
        else:
            # Use OpenRouter API key from main entry
            api_key = get_config_value(config_entry, CONF_API_KEY, "")
        
        # Initialize LLM client using factory
        self._llm_client = create_llm_client(
            provider=llm_provider,
            api_key=api_key,
            model=get_config(CONF_MODEL, DEFAULT_MODEL),
            temperature=get_config(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
            max_tokens=get_config(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
            openrouter_provider=get_config(CONF_PROVIDER, DEFAULT_PROVIDER),
        )
        
        # For OpenRouterClient, caching is always enabled (auto-detected by model)
        if hasattr(self._llm_client, '_enable_caching'):
            self._llm_client._enable_caching = True
            # Auto-enable extended TTL for Anthropic models
            if hasattr(self._llm_client, '_cache_ttl_extended'):
                model = get_config(CONF_MODEL, DEFAULT_MODEL)
                self._llm_client._cache_ttl_extended = model.startswith("anthropic/")
        
        # Initialize entity manager for context
        self._entity_manager = EntityManager(
            hass,
            exposed_only=get_config(CONF_EXPOSED_ONLY, True),
        )
        
        # Initialize tool registry
        self._tool_registry = create_tool_registry(
            hass=hass,
            entry=config_entry,
            subentry_data=subentry.data,
        )
        
        # Store LLM client reference for sensors to access metrics
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN].setdefault(config_entry.entry_id, {})
        hass.data[DOMAIN][config_entry.entry_id].setdefault("tasks", {})
        hass.data[DOMAIN][config_entry.entry_id]["tasks"][subentry.subentry_id] = {
            "llm_client": self._llm_client,
            "entity": self,
        }

        self._last_tool_call_records: list[ToolCallRecord] = []
        self._last_llm_iterations: int = 1

    async def async_added_to_hass(self) -> None:
        """Set a deterministic initial state when the entity is first added."""
        await super().async_added_to_hass()

        if self.state is None:
            setattr(self, "_AITaskEntity__last_activity", "ready")
            self.async_write_ha_state()

    async def _async_generate_data(
        self,
        task: GenDataTask,
        chat_log: ChatLog,
    ) -> GenDataTaskResult:
        """Handle a generate data task.
        
        This method processes natural language instructions and generates
        appropriate data/responses using the LLM.
        """
        _LOGGER.debug(
            "AI Task received: name=%s, instructions=%s",
            getattr(task, "task_name", getattr(task, "name", "unknown")),
            (
                str(getattr(task, "instructions", ""))[:100]
                if getattr(task, "instructions", None)
                else "None"
            ),
        )
        request_start_time = time.monotonic()

        # Normalize instructions to avoid provider-side unknown errors
        raw_instructions = getattr(task, "instructions", "")
        if not isinstance(raw_instructions, str):
            raw_instructions = ""
        instructions = raw_instructions.strip()
        if not instructions:
            return GenDataTaskResult(
                conversation_id=chat_log.conversation_id,
                data="Task instructions are empty. Please provide instructions.",
            )

        try:
            # Build messages for LLM
            messages = self._build_messages(instructions)

            # Get tool schemas
            tools = self._tool_registry.get_schemas()

            # Call LLM with tool support
            response_content = await self._process_with_tools(messages, tools)
        except Exception as e:
            _LOGGER.error("AI Task LLM call failed: %s", e)
            response_content = sanitize_user_facing_error(
                e,
                fallback="Sorry, I could not process this task right now.",
            )

        history_store = self.hass.data.get(DOMAIN, {}).get(
            self._config_entry.entry_id, {}
        ).get("request_history")
        if history_store:
            include_history_content = bool(
                get_config_value(
                    self._config_entry,
                    CONF_ENABLE_REQUEST_HISTORY_CONTENT,
                    DEFAULT_ENABLE_REQUEST_HISTORY_CONTENT,
                )
            )
            retention_days = max(
                1,
                int(
                    get_config_value(
                        self._config_entry,
                        CONF_HISTORY_RETENTION_DAYS,
                        DEFAULT_HISTORY_RETENTION_DAYS,
                    )
                ),
            )
            input_text = (
                RequestHistoryStore.truncate(
                    instructions,
                    REQUEST_HISTORY_INPUT_MAX_LENGTH,
                )
                if include_history_content
                else ""
            )
            response_history_text = (
                RequestHistoryStore.truncate(
                    response_content,
                    REQUEST_HISTORY_RESPONSE_MAX_LENGTH,
                )
                if include_history_content
                else ""
            )

            sanitized_tool_calls: list[ToolCallRecord] = []
            for record in self._last_tool_call_records:
                args_summary = (
                    RequestHistoryStore.truncate(
                        record.arguments_summary,
                        REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH,
                    )
                    if include_history_content
                    else ""
                )
                sanitized_tool_calls.append(
                    ToolCallRecord(
                        name=record.name,
                        success=record.success,
                        execution_time_ms=record.execution_time_ms,
                        arguments_summary=args_summary,
                        timed_out=record.timed_out,
                        retries_used=record.retries_used,
                        latency_budget_ms=record.latency_budget_ms,
                    )
                )

            prompt_tokens = 0
            completion_tokens = 0
            cached_tokens = 0
            if self._llm_client and hasattr(self._llm_client, "metrics"):
                metrics = self._llm_client.metrics
                prompt_tokens = getattr(metrics, "_last_prompt_tokens", 0)
                completion_tokens = getattr(metrics, "_last_completion_tokens", 0)
                cached_tokens = getattr(metrics, "_last_cached_tokens", 0)

            history_store.prune_older_than_days(retention_days)
            history_store.add_entry(
                RequestHistoryEntry(
                    id=RequestHistoryStore.generate_id(),
                    timestamp=dt_util.now().isoformat(),
                    agent_id=self._subentry.subentry_id,
                    agent_name=self._subentry.title,
                    conversation_id=chat_log.conversation_id,
                    user_id="system",
                    input_text=input_text,
                    response_text=response_history_text,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cached_tokens=cached_tokens,
                    response_time_ms=(time.monotonic() - request_start_time) * 1000,
                    llm_provider=self._get_config(CONF_LLM_PROVIDER, DEFAULT_LLM_PROVIDER),
                    model=self._get_config(CONF_MODEL, DEFAULT_MODEL),
                    llm_iterations=self._last_llm_iterations,
                    tools_used=sanitized_tool_calls,
                    success=True,
                    error=None,
                    is_nevermind=False,
                    is_system_call=True,
                )
            )
            self.hass.async_create_task(history_store.async_save())
        
        # Signal sensors to update their state (per subentry)
        async_dispatcher_send(
            self.hass,
            f"{DOMAIN}_metrics_updated_{self._subentry.subentry_id}",
        )
        
        # Return result
        if getattr(task, "structure", None):
            # If structured output requested, try to parse response
            # For now, return as plain text - structured output parsing can be added later
            return GenDataTaskResult(
                conversation_id=chat_log.conversation_id,
                data={"result": response_content},
            )
        
        return GenDataTaskResult(
            conversation_id=chat_log.conversation_id,
            data=response_content,
        )

    def _build_messages(self, instructions: str) -> list[ChatMessage]:
        """Build message list for LLM."""
        # Get task-specific system prompt
        system_prompt = self._get_config(
            CONF_TASK_SYSTEM_PROMPT, 
            DEFAULT_TASK_SYSTEM_PROMPT
        )
        
        # Get entity index for context (returns tuple: text, hash)
        entity_index, _ = self._entity_manager.get_entity_index()
        
        # Determine language instruction for response
        language = self._get_config(CONF_LANGUAGE, "")
        language_instruction = ""
        
        if not language or language == "auto":
            # Auto-detect: use Home Assistant's configured language
            ha_language = self.hass.config.language  # e.g., "de-DE", "en-US"
            locale_prefix = ha_language.split("-")[0].lower()  # "de", "en", etc.
            
            if locale_prefix in LOCALE_TO_LANGUAGE:
                english_name, native_name = LOCALE_TO_LANGUAGE[locale_prefix]
                language_instruction = f"\n\nRespond in {english_name} ({native_name})."
            # If locale not in mapping, don't add instruction (LLM will use context)
        else:
            # User-specified language - use directly
            language_instruction = f"\n\nRespond in {language}."
        
        # Build full system prompt
        full_system_prompt = f"""{system_prompt}

You are executing a background task in a Home Assistant smart home system.
Focus on completing the task efficiently and providing structured, useful output.
{language_instruction}

## Available Entities
{entity_index}
"""
        
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=full_system_prompt),
            ChatMessage(role=MessageRole.USER, content=instructions),
        ]
        
        return messages

    async def _process_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        max_iterations: int = 5,
    ) -> str:
        """Process LLM request with tool execution support."""
        iteration = 0
        tool_call_records: list[ToolCallRecord] = []
        self._last_tool_call_records = []
        self._last_llm_iterations = 1
        # Always cache system + user message prefix
        cached_prefix_length = 2
        
        while iteration < max_iterations:
            iteration += 1
            
            response = await self._llm_client.chat(
                messages=messages,
                tools=tools,
                # Only apply caching on first iteration
                cached_prefix_length=cached_prefix_length if iteration == 1 else 0,
            )
            
            if not response.has_tool_calls:
                self._last_tool_call_records = tool_call_records
                self._last_llm_iterations = iteration
                return response.content or ""
            
            _LOGGER.debug("AI Task executing %d tool calls", len(response.tool_calls))
            
            # Add assistant message with tool calls
            messages.append(
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                )
            )
            
            # Execute tools in parallel and add results
            max_retries = int(
                self._get_config(CONF_TOOL_MAX_RETRIES, DEFAULT_TOOL_MAX_RETRIES)
            )
            latency_budget_ms = int(
                self._get_config(
                    CONF_TOOL_LATENCY_BUDGET_MS,
                    DEFAULT_TOOL_LATENCY_BUDGET_MS,
                )
            )
            allow_control = bool(
                self._get_config(CONF_TASK_ALLOW_CONTROL, DEFAULT_TASK_ALLOW_CONTROL)
            )
            allow_lock_control = bool(
                self._get_config(
                    CONF_TASK_ALLOW_LOCK_CONTROL,
                    DEFAULT_TASK_ALLOW_LOCK_CONTROL,
                )
            )

            allowed_tool_calls: list[Any] = []
            blocked_messages: dict[str, ChatMessage] = {}
            for tool_call in response.tool_calls:
                if tool_call.name != "control":
                    allowed_tool_calls.append(tool_call)
                    continue

                if not allow_control:
                    blocked_messages[tool_call.id] = ChatMessage(
                        role=MessageRole.TOOL,
                        content="Control actions are disabled for this AI Task.",
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                    continue

                if not allow_lock_control and _targets_lock_domain(tool_call.arguments):
                    blocked_messages[tool_call.id] = ChatMessage(
                        role=MessageRole.TOOL,
                        content="Lock control is disabled for this AI Task.",
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                    continue

                allowed_tool_calls.append(tool_call)

            executed_messages: dict[str, ChatMessage] = {}
            if allowed_tool_calls:
                async def _exec(call: Any) -> tuple[Any, Any]:
                    result = await self._tool_registry.execute(
                        call.name,
                        call.arguments,
                        max_retries=max_retries,
                        latency_budget_ms=latency_budget_ms,
                    )
                    return call, result

                raw_results = await asyncio.gather(
                    *[_exec(call) for call in allowed_tool_calls],
                    return_exceptions=True,
                )
                for idx, item in enumerate(raw_results):
                    call = allowed_tool_calls[idx]
                    arguments_summary = str(call.arguments)
                    if isinstance(item, Exception):
                        executed_messages[call.id] = ChatMessage(
                            role=MessageRole.TOOL,
                            content=f"Error: {item}",
                            tool_call_id=call.id,
                            name=call.name,
                        )
                        tool_call_records.append(
                            ToolCallRecord(
                                name=call.name,
                                success=False,
                                execution_time_ms=0.0,
                                arguments_summary=arguments_summary,
                            )
                        )
                        continue

                    _, result = item
                    executed_messages[call.id] = ChatMessage(
                        role=MessageRole.TOOL,
                        content=result.to_string(),
                        tool_call_id=call.id,
                        name=call.name,
                    )
                    result_data = result.data if isinstance(result.data, dict) else {}
                    tool_call_records.append(
                        ToolCallRecord(
                            name=call.name,
                            success=bool(result.success),
                            execution_time_ms=float(result_data.get("execution_time_ms", 0.0)),
                            arguments_summary=arguments_summary,
                            timed_out=bool(result_data.get("timed_out", False)),
                            retries_used=int(result_data.get("retries_used", 0)),
                            latency_budget_ms=result_data.get("latency_budget_ms"),
                        )
                    )

            tool_messages: list[ChatMessage] = []
            for tool_call in response.tool_calls:
                blocked_message = blocked_messages.get(tool_call.id)
                if blocked_message is not None:
                    tool_messages.append(blocked_message)
                    tool_call_records.append(
                        ToolCallRecord(
                            name=tool_call.name,
                            success=False,
                            execution_time_ms=0.0,
                            arguments_summary=str(tool_call.arguments),
                        )
                    )
                    continue

                executed_message = executed_messages.get(tool_call.id)
                if executed_message is not None:
                    tool_messages.append(executed_message)

            messages.extend(tool_messages)
        
        self._last_tool_call_records = tool_call_records
        self._last_llm_iterations = iteration
        _LOGGER.warning("AI Task max iterations reached")
        return response.content or ""

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        if self._llm_client:
            await self._llm_client.close()
