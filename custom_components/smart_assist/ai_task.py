"""AI Task entity for Smart Assist - enables LLM usage in automations."""

from __future__ import annotations

import json
import logging
import re
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
    TASK_STRUCTURED_OUTPUT_INVALID_JSON_DE,
    TASK_STRUCTURED_OUTPUT_INVALID_JSON_EN,
    TASK_STRUCTURED_OUTPUT_SCHEMA_MISMATCH_DE,
    TASK_STRUCTURED_OUTPUT_SCHEMA_MISMATCH_EN,
)
from .context.entity_manager import EntityManager
from .context.request_history import RequestHistoryEntry, RequestHistoryStore, ToolCallRecord
from .llm import OpenRouterClient, GroqClient, create_llm_client
from .llm.models import ChatMessage, MessageRole
from .tool_executor import execute_tool_calls
from .tools import create_tool_registry
from .utils import extract_target_domains, get_config_value, sanitize_user_facing_error

_LOGGER = logging.getLogger(__name__)

SATELLITE_ANNOUNCE_LATENCY_FLOOR_MS = 30_000


def _targets_lock_domain(arguments: dict[str, Any]) -> bool:
    """Return True if a control call targets lock domain."""
    return "lock" in extract_target_domains(arguments)


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
        self._last_history_prune_monotonic: float = 0.0
        self._history_prune_interval_seconds: float = 300.0

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

        structured_schema = self._normalize_task_structure(getattr(task, "structure", None))
        structured_requested = structured_schema is not None
        language_prefix = self._resolve_language_prefix()

        response_content = ""
        result_data: Any = ""
        request_success = True
        request_error: str | None = None

        try:
            # Build messages for LLM
            messages = self._build_messages(instructions)

            if structured_requested and structured_schema is not None:
                messages.insert(
                    1,
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=self._build_structured_output_instruction(structured_schema),
                    ),
                )

            # Get tool schemas
            tools = self._tool_registry.get_schemas()

            # Call LLM with tool support
            response_content = await self._process_with_tools(
                messages,
                tools,
                original_instructions=instructions,
                response_schema=structured_schema,
                response_schema_name=(
                    str(getattr(task, "task_name", "smart_assist_task") or "smart_assist_task")
                    if structured_requested
                    else None
                ),
                use_native_structured_output=structured_requested,
                allow_structured_native_fallback_retry=structured_requested,
            )

            if not structured_requested:
                max_retries = int(
                    self._get_config(CONF_TOOL_MAX_RETRIES, DEFAULT_TOOL_MAX_RETRIES)
                )
                latency_budget_ms = int(
                    self._get_config(
                        CONF_TOOL_LATENCY_BUDGET_MS,
                        DEFAULT_TOOL_LATENCY_BUDGET_MS,
                    )
                )
                response_content = await self._enforce_satellite_announce_if_requested(
                    instructions=instructions,
                    response_content=response_content,
                    task_name=str(getattr(task, "task_name", getattr(task, "name", "")) or ""),
                    max_retries=max_retries,
                    latency_budget_ms=latency_budget_ms,
                )

            if structured_requested and structured_schema is not None:
                try:
                    structured_data = self._extract_json_payload(response_content)
                except ValueError:
                    request_success = False
                    request_error = "structured_output_invalid_json"
                    result_data = self._structured_output_error_message(
                        language_prefix,
                        reason="invalid_json",
                    )
                else:
                    is_valid, _ = self._validate_structured_output(structured_data, structured_schema)
                    if is_valid:
                        result_data = structured_data
                    else:
                        request_success = False
                        request_error = "structured_output_schema_mismatch"
                        result_data = self._structured_output_error_message(
                            language_prefix,
                            reason="schema_mismatch",
                        )
            else:
                result_data = response_content
        except Exception as e:
            _LOGGER.error("AI Task LLM call failed: %s", e)
            request_success = False
            sanitized_error = sanitize_user_facing_error(
                e,
                fallback="Task processing failed.",
            )
            request_error = json.dumps(
                {
                    "type": type(e).__name__,
                    "message": sanitized_error,
                },
                ensure_ascii=False,
            )
            if structured_requested:
                result_data = self._structured_output_error_message(
                    language_prefix,
                    reason="invalid_json",
                )
            else:
                response_content = sanitize_user_facing_error(
                    e,
                    fallback="Sorry, I could not process this task right now.",
                )
                result_data = response_content

        response_content_for_history = (
            result_data
            if isinstance(result_data, str)
            else json.dumps(result_data, ensure_ascii=False)
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
                    response_content_for_history,
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

            now_mono = time.monotonic()
            if now_mono - self._last_history_prune_monotonic >= self._history_prune_interval_seconds:
                history_store.prune_older_than_days(retention_days)
                self._last_history_prune_monotonic = now_mono
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
                    success=request_success,
                    error=request_error,
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
        return GenDataTaskResult(
            conversation_id=chat_log.conversation_id,
            data=result_data,
        )

    @staticmethod
    def _normalize_task_structure(raw_structure: Any) -> dict[str, Any] | None:
        """Normalize task.structure into a JSON-schema dict when present."""
        if raw_structure is None:
            return None
        if isinstance(raw_structure, dict):
            nested_schema = raw_structure.get("schema")
            if isinstance(nested_schema, dict):
                return nested_schema
            return raw_structure
        return None

    def _resolve_language_prefix(self) -> str:
        """Resolve current language prefix for localized task error messages."""
        language = self._get_config(CONF_LANGUAGE, "")
        if isinstance(language, str) and language and language != "auto":
            return language.split("-")[0].lower()

        ha_language = getattr(self.hass.config, "language", "en-US")
        if isinstance(ha_language, str) and ha_language:
            return ha_language.split("-")[0].lower()

        return "en"

    @staticmethod
    def _build_structured_output_instruction(schema: dict[str, Any]) -> str:
        """Build strict JSON output instruction for structured AI task runs."""
        schema_json = json.dumps(schema, ensure_ascii=False)
        return (
            "Return ONLY valid JSON that matches this schema exactly. "
            "Do not include markdown, code fences, explanations, or extra keys. "
            f"Schema: {schema_json}"
        )

    @staticmethod
    def _extract_json_payload(text: str) -> Any:
        """Extract and parse JSON payload from model output text."""
        raw = (text or "").strip()
        if not raw:
            raise ValueError("empty response")

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        fenced_matches = re.findall(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
        for candidate in fenced_matches:
            candidate = candidate.strip()
            if not candidate:
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

        first_object = raw.find("{")
        first_array = raw.find("[")
        start_candidates = [idx for idx in (first_object, first_array) if idx >= 0]
        if not start_candidates:
            raise ValueError("no json payload found")

        start = min(start_candidates)
        for end in range(len(raw), start, -1):
            snippet = raw[start:end].strip()
            if not snippet:
                continue
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                continue

        raise ValueError("invalid json payload")

    @classmethod
    def _validate_structured_output(
        cls,
        data: Any,
        schema: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Validate JSON-compatible data against a constrained schema subset."""
        return cls._validate_schema_node(data, schema, path="$")

    @classmethod
    def _validate_schema_node(
        cls,
        value: Any,
        schema: dict[str, Any],
        path: str,
    ) -> tuple[bool, str | None]:
        schema_type = schema.get("type")
        if schema_type is not None and not cls._matches_type(value, schema_type):
            return False, f"type mismatch at {path}"

        if "enum" in schema and value not in schema.get("enum", []):
            return False, f"enum mismatch at {path}"

        if schema_type == "object" and isinstance(value, dict):
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            additional_properties = schema.get("additionalProperties", True)

            if isinstance(required, list):
                for key in required:
                    if key not in value:
                        return False, f"missing required field {path}.{key}"

            if isinstance(properties, dict):
                for key, nested_schema in properties.items():
                    if key in value and isinstance(nested_schema, dict):
                        is_valid, reason = cls._validate_schema_node(
                            value[key],
                            nested_schema,
                            f"{path}.{key}",
                        )
                        if not is_valid:
                            return False, reason

            if additional_properties is False and isinstance(properties, dict):
                unexpected = set(value.keys()) - set(properties.keys())
                if unexpected:
                    return False, f"unexpected fields at {path}"

        if schema_type == "array" and isinstance(value, list):
            items_schema = schema.get("items")
            if isinstance(items_schema, dict):
                for idx, item in enumerate(value):
                    is_valid, reason = cls._validate_schema_node(
                        item,
                        items_schema,
                        f"{path}[{idx}]",
                    )
                    if not is_valid:
                        return False, reason

        return True, None

    @staticmethod
    def _matches_type(value: Any, schema_type: str | list[str]) -> bool:
        """Return True when value matches one of the schema types."""
        allowed_types = schema_type if isinstance(schema_type, list) else [schema_type]
        for allowed in allowed_types:
            if allowed == "object" and isinstance(value, dict):
                return True
            if allowed == "array" and isinstance(value, list):
                return True
            if allowed == "string" and isinstance(value, str):
                return True
            if allowed == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
                return True
            if allowed == "integer" and isinstance(value, int) and not isinstance(value, bool):
                return True
            if allowed == "boolean" and isinstance(value, bool):
                return True
            if allowed == "null" and value is None:
                return True
        return False

    @staticmethod
    def _structured_output_error_message(language: str, reason: str = "invalid_json") -> str:
        """Return concise localized structured-output failure message."""
        is_german = language.startswith("de")
        if reason == "schema_mismatch":
            return (
                TASK_STRUCTURED_OUTPUT_SCHEMA_MISMATCH_DE
                if is_german
                else TASK_STRUCTURED_OUTPUT_SCHEMA_MISMATCH_EN
            )
        return (
            TASK_STRUCTURED_OUTPUT_INVALID_JSON_DE
            if is_german
            else TASK_STRUCTURED_OUTPUT_INVALID_JSON_EN
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

    def get_registered_tool_names(self) -> list[str]:
        """Return currently registered tool names for diagnostics/UI."""
        if not self._tool_registry:
            return []
        return [tool.name for tool in self._tool_registry.get_all()]

    async def _process_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        max_iterations: int = 5,
        original_instructions: str | None = None,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        use_native_structured_output: bool = False,
        allow_structured_native_fallback_retry: bool = False,
    ) -> str:
        """Process LLM request with tool execution support."""
        iteration = 0
        tool_call_records: list[ToolCallRecord] = []
        self._last_tool_call_records = []
        self._last_llm_iterations = 1
        # Always cache system + user message prefix
        cached_prefix_length = 2
        native_fallback_retry_used = False

        async def _chat_call(*, native_mode: bool) -> Any:
            chat_kwargs: dict[str, Any] = {
                "tools": tools,
                "cached_prefix_length": cached_prefix_length if iteration == 1 else 0,
                "response_schema": response_schema,
                "response_schema_name": response_schema_name,
                "use_native_structured_output": native_mode,
            }
            chat_method = self._llm_client.chat
            return await chat_method(messages=messages, **chat_kwargs)
        
        while iteration < max_iterations:
            iteration += 1
            
            try:
                response = await _chat_call(native_mode=use_native_structured_output)
            except Exception:
                if (
                    response_schema is not None
                    and use_native_structured_output
                    and allow_structured_native_fallback_retry
                    and not native_fallback_retry_used
                ):
                    native_fallback_retry_used = True
                    _LOGGER.debug(
                        "AI Task structured native mode failed, retrying once with non-native mode"
                    )
                    response = await _chat_call(native_mode=False)
                else:
                    raise
            
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

            subentry_data = self._subentry.data if isinstance(self._subentry.data, dict) else {}
            allow_control = bool(subentry_data.get(CONF_TASK_ALLOW_CONTROL, DEFAULT_TASK_ALLOW_CONTROL))
            allow_lock_control = bool(subentry_data.get(CONF_TASK_ALLOW_LOCK_CONTROL, DEFAULT_TASK_ALLOW_LOCK_CONTROL))

            allowed_tool_calls: list[Any] = []
            blocked_messages: dict[str, ChatMessage] = {}
            for tool_call in response.tool_calls:
                if (
                    tool_call.name == "send"
                    and self._tool_registry.has_tool("satellite_announce")
                    and self._instruction_requests_satellite_announce(original_instructions)
                ):
                    blocked_messages[tool_call.id] = ChatMessage(
                        role=MessageRole.TOOL,
                        content=(
                            "Do not use send for voice satellite announcements. "
                            "Use satellite_announce with all=true for all satellites, "
                            "or satellite_entity_id/satellite_entity_ids for specific satellites."
                        ),
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                    continue

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
                effective_latency_budget_ms = latency_budget_ms
                if any(tc.name == "satellite_announce" for tc in allowed_tool_calls):
                    effective_latency_budget_ms = max(
                        latency_budget_ms,
                        SATELLITE_ANNOUNCE_LATENCY_FLOOR_MS,
                    )
                exec_results = await execute_tool_calls(
                    tool_calls=allowed_tool_calls,
                    tool_registry=self._tool_registry,
                    max_retries=max_retries,
                    latency_budget_ms=effective_latency_budget_ms,
                    request_history_max_length=REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH,
                )
                for tool_call, result_or_err, record in exec_results:
                    tool_call_records.append(record)
                    if isinstance(result_or_err, Exception):
                        executed_messages[tool_call.id] = ChatMessage(
                            role=MessageRole.TOOL,
                            content=f"Error: {result_or_err}",
                            tool_call_id=tool_call.id,
                            name=tool_call.name,
                        )
                    else:
                        executed_messages[tool_call.id] = ChatMessage(
                            role=MessageRole.TOOL,
                            content=result_or_err.to_string(),
                            tool_call_id=tool_call.id,
                            name=tool_call.name,
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
                            timed_out=False,
                            retries_used=0,
                            latency_budget_ms=latency_budget_ms,
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

    @staticmethod
    def _instruction_requests_satellite_announce(instructions: str | None) -> bool:
        """Heuristic: True when user instructions explicitly request satellite voice announce."""
        if not instructions:
            return False
        normalized = str(instructions).lower()
        wants_announce = any(token in normalized for token in ("announce", "ansage", "durchsage"))
        wants_satellite = any(token in normalized for token in ("satellite", "satellit", "satllite", "satllites"))
        return wants_announce and wants_satellite

    async def _enforce_satellite_announce_if_requested(
        self,
        *,
        instructions: str,
        response_content: str,
        task_name: str,
        max_retries: int,
        latency_budget_ms: int,
    ) -> str:
        """Fallback: run satellite_announce when request clearly demands it but tool call was missing/failed."""
        if not self._instruction_requests_satellite_announce(instructions):
            return response_content

        if not self._tool_registry.has_tool("satellite_announce"):
            return response_content

        if any(
            record.name == "satellite_announce" and record.success
            for record in self._last_tool_call_records
        ):
            return response_content

        announce_message = (response_content or "").strip() or (task_name or "").strip()
        if not announce_message:
            announce_message = "Es gibt eine neue Benachrichtigung."

        effective_latency_budget_ms = max(
            latency_budget_ms,
            SATELLITE_ANNOUNCE_LATENCY_FLOOR_MS,
        )

        started = time.monotonic()
        try:
            result = await self._tool_registry.execute(
                "satellite_announce",
                {
                    "message": announce_message,
                    "all": True,
                },
                max_retries=max_retries,
                latency_budget_ms=effective_latency_budget_ms,
            )
            result_data = result.data if isinstance(result.data, dict) else {}
            self._last_tool_call_records.append(
                ToolCallRecord(
                    name="satellite_announce",
                    success=bool(result.success),
                    execution_time_ms=float(
                        result_data.get(
                            "execution_time_ms",
                            (time.monotonic() - started) * 1000,
                        )
                    ),
                    arguments_summary=str({"message": announce_message, "all": True}),
                    timed_out=bool(result_data.get("timed_out", False)),
                    retries_used=int(result_data.get("retries_used", 0)),
                    latency_budget_ms=int(result_data.get("latency_budget_ms", effective_latency_budget_ms)),
                )
            )
            if result.success and not (response_content or "").strip():
                return announce_message
        except Exception as err:
            self._last_tool_call_records.append(
                ToolCallRecord(
                    name="satellite_announce",
                    success=False,
                    execution_time_ms=(time.monotonic() - started) * 1000,
                    arguments_summary=str({"message": announce_message, "all": True}),
                    timed_out=False,
                    retries_used=0,
                    latency_budget_ms=effective_latency_budget_ms,
                )
            )
            _LOGGER.warning("AI Task fallback satellite_announce failed: %s", err)

        return response_content

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        if self._llm_client:
            await self._llm_client.close()
