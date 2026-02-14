"""Conversation entity for Smart Assist - Home Assistant Assist Pipeline integration."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any, Literal, TYPE_CHECKING

_LOGGER = logging.getLogger(__name__)
_LOGGER.debug("Smart Assist: Loading conversation.py module")

try:
    from homeassistant.components import conversation
    from homeassistant.components.conversation import (
        ConversationEntity,
        ConversationEntityFeature,
        ConversationInput,
        ConversationResult,
    )
    _LOGGER.debug("Smart Assist: Successfully imported conversation components")
except ImportError as e:
    _LOGGER.error("Smart Assist: Failed to import conversation components: %s", e, exc_info=True)
    raise

# These imports may not exist in older HA versions
try:
    from homeassistant.components.conversation import (
        AssistantContent,
        AssistantContentDeltaDict,
        ChatLog,
        ToolResultContent,
        UserContent,
    )
    HAS_CHAT_LOG = True
    _LOGGER.debug("Smart Assist: ChatLog API available")
except ImportError:
    HAS_CHAT_LOG = False
    AssistantContent = None
    AssistantContentDeltaDict = dict
    ChatLog = None
    ToolResultContent = None
    UserContent = None
    _LOGGER.debug("Smart Assist: ChatLog API not available, using fallback")

try:
    from homeassistant.config_entries import ConfigEntry, ConfigSubentry
    from homeassistant.const import MATCH_ALL
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import intent, device_registry as dr, entity_registry as er
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    from homeassistant.util import dt as dt_util
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError as e:
    _LOGGER.error("Smart Assist: Failed to import HA core modules: %s", e)
    raise

try:
    from .const import (
        CONF_API_KEY,
        CONF_ASK_FOLLOWUP,
        CONF_CLEAN_RESPONSES,
        CONF_ENABLE_REQUEST_HISTORY_CONTENT,
        CONF_ENABLE_MEMORY,
        CONF_ENABLE_PRESENCE_HEURISTIC,
        CONF_ENABLE_QUICK_ACTIONS,
        CONF_EXPOSED_ONLY,
        CONF_GROQ_API_KEY,
        CONF_HISTORY_REDACT_PATTERNS,
        CONF_HISTORY_RETENTION_DAYS,
        CONF_LANGUAGE,
        CONF_LLM_PROVIDER,
        CONF_MAX_HISTORY,
        CONF_MAX_TOKENS,
        CONF_MODEL,
        CONF_OLLAMA_KEEP_ALIVE,
        CONF_OLLAMA_MODEL,
        CONF_OLLAMA_NUM_CTX,
        CONF_OLLAMA_TIMEOUT,
        CONF_OLLAMA_URL,
        CONF_PROVIDER,
        CONF_TEMPERATURE,
        CONF_USER_MAPPINGS,
        DEFAULT_ASK_FOLLOWUP,
        DEFAULT_CLEAN_RESPONSES,
        DEFAULT_ENABLE_REQUEST_HISTORY_CONTENT,
        DEFAULT_ENABLE_MEMORY,
        DEFAULT_ENABLE_PRESENCE_HEURISTIC,
        DEFAULT_HISTORY_REDACT_PATTERNS,
        DEFAULT_HISTORY_RETENTION_DAYS,
        DEFAULT_LLM_PROVIDER,
        DEFAULT_MAX_HISTORY,
        DEFAULT_MAX_TOKENS,
        DEFAULT_MODEL,
        DEFAULT_PROVIDER,
        DEFAULT_TEMPERATURE,
        DOMAIN,
        LLM_PROVIDER_GROQ,
        LLM_PROVIDER_OLLAMA,
        MAX_TOOL_ITERATIONS,
        OLLAMA_DEFAULT_KEEP_ALIVE,
        OLLAMA_DEFAULT_MODEL,
        OLLAMA_DEFAULT_NUM_CTX,
        OLLAMA_DEFAULT_TIMEOUT,
        OLLAMA_DEFAULT_URL,
        REQUEST_HISTORY_INPUT_MAX_LENGTH,
        REQUEST_HISTORY_RESPONSE_MAX_LENGTH,
        REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH,
    )
    from .context import EntityManager
    from .context.calendar_reminder import CalendarReminderTracker
    from .context.conversation import ConversationManager
    from .context.memory import MemoryManager
    from .context.request_history import RequestHistoryStore, RequestHistoryEntry, ToolCallRecord
    from .context.user_resolver import UserResolver
    from .llm import ChatMessage, OpenRouterClient, GroqClient, create_llm_client
    from .llm.models import ToolCall
    from .tools import create_tool_registry, ToolRegistry
    from .utils import clean_for_tts, get_config_value
    from .prompt_builder import (
        build_system_prompt as _build_system_prompt_impl,
        get_calendar_context as _get_calendar_context_impl,
        build_messages_for_llm_async as _build_messages_for_llm_async_impl,
        build_messages_for_llm as _build_messages_for_llm_impl,
    )
    from .streaming import (
        call_llm_streaming_with_tools as _call_llm_streaming_with_tools_impl,
        create_delta_stream as _create_delta_stream_impl,
        wrap_response_as_delta_stream as _wrap_response_as_delta_stream_impl,
    )
except ImportError as e:
    _LOGGER.error("Smart Assist: Failed to import local modules: %s", e, exc_info=True)
    raise

_LOGGER.info("Smart Assist: conversation.py module loaded successfully")


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Smart Assist conversation entities from config entry subentries."""
    _LOGGER.debug("Smart Assist: Setting up conversation entities from subentries")
    
    for subentry_id, subentry in config_entry.subentries.items():
        if subentry.subentry_type != "conversation":
            continue
        
        _LOGGER.debug("Smart Assist: Creating conversation entity for subentry %s", subentry_id)
        async_add_entities(
            [SmartAssistConversationEntity(hass, config_entry, subentry)],
            config_subentry_id=subentry_id,
        )


class SmartAssistConversationEntity(ConversationEntity):
    """Smart Assist conversation entity for Home Assistant Assist Pipeline.
    
    This entity provides LLM-powered conversation with streaming support.
    Each entity is created from a subentry configuration.
    """

    # Entity attributes
    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_supports_streaming = True
    _attr_supported_features = ConversationEntityFeature.CONTROL

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the conversation entity."""
        self.hass = hass
        self._entry = entry
        self._subentry = subentry
        
        # Unique ID based on subentry
        self._attr_unique_id = subentry.subentry_id
        
        # Device info for proper UI display
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Smart Assist",
            model="Conversation Agent",
            entry_type=dr.DeviceEntryType.SERVICE,
        )

        # Helper to get config values from subentry using centralized utility
        def get_config(key: str, default: Any = None) -> Any:
            """Get config value from subentry data."""
            return get_config_value(subentry, key, default)

        # Determine LLM provider and API key
        llm_provider = get_config(CONF_LLM_PROVIDER, DEFAULT_LLM_PROVIDER)
        
        if llm_provider == LLM_PROVIDER_GROQ:
            # Use Groq API key from subentry or main entry
            api_key = get_config(CONF_GROQ_API_KEY) or get_config_value(entry, CONF_GROQ_API_KEY, "")
        elif llm_provider == LLM_PROVIDER_OLLAMA:
            # Ollama doesn't need an API key
            api_key = ""
        else:
            # Use OpenRouter API key from main entry
            api_key = get_config_value(entry, CONF_API_KEY, "")
        
        # Get Ollama-specific configuration from main entry
        ollama_url = get_config_value(entry, CONF_OLLAMA_URL, OLLAMA_DEFAULT_URL)
        ollama_keep_alive = get_config_value(entry, CONF_OLLAMA_KEEP_ALIVE, OLLAMA_DEFAULT_KEEP_ALIVE)
        ollama_num_ctx = get_config_value(entry, CONF_OLLAMA_NUM_CTX, OLLAMA_DEFAULT_NUM_CTX)
        ollama_timeout = get_config_value(entry, CONF_OLLAMA_TIMEOUT, OLLAMA_DEFAULT_TIMEOUT)
        
        # Initialize LLM client using factory
        self._llm_client = create_llm_client(
            provider=llm_provider,
            api_key=api_key,
            model=get_config(CONF_MODEL, DEFAULT_MODEL),
            temperature=get_config(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
            max_tokens=get_config(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
            openrouter_provider=get_config(CONF_PROVIDER, DEFAULT_PROVIDER),
            ollama_url=ollama_url,
            ollama_keep_alive=ollama_keep_alive,
            ollama_num_ctx=ollama_num_ctx,
            ollama_timeout=ollama_timeout,
        )
        
        # For OpenRouterClient, caching is always enabled (auto-detected by model)
        if hasattr(self._llm_client, 'enable_caching'):
            self._llm_client._enable_caching = True
        if hasattr(self._llm_client, '_cache_ttl_extended'):
            # Auto-enable extended TTL for Anthropic models
            model = get_config(CONF_MODEL, DEFAULT_MODEL)
            self._llm_client._cache_ttl_extended = model.startswith("anthropic/")
        
        # Store LLM client reference for sensors to access metrics
        domain_data = hass.data.setdefault(DOMAIN, {})
        entry_data = domain_data.setdefault(entry.entry_id, {"agents": {}})
        entry_data.setdefault("agents", {})
        entry_data["agents"][subentry.subentry_id] = {
            "llm_client": self._llm_client,
            "entity": self,
        }

        # Entity manager for entity discovery
        self._entity_manager = EntityManager(
            hass=hass,
            exposed_only=get_config(CONF_EXPOSED_ONLY, True),
        )

        # Tool registry - lazy loaded to ensure all domains are available
        # Created on first access (after HA startup delay)
        self._tool_registry: ToolRegistry | None = None
        self._tool_registry_lock = asyncio.Lock()  # Thread-safe initialization
        self._entry = entry  # Store for lazy loading

        # Cache for entity index
        self._cached_entity_index: str | None = None
        self._cached_index_hash: str | None = None
        
        # Cache for system prompt (built once, reused for all requests)
        self._cached_system_prompt: str | None = None
        
        # Calendar reminder tracker for staged reminders (persisted)
        self._calendar_reminder_tracker = CalendarReminderTracker(hass)
        
        # Conversation manager for multi-turn context tracking
        self._conversation_manager = ConversationManager(
            max_history=get_config(CONF_MAX_HISTORY, DEFAULT_MAX_HISTORY)
        )

        # Memory manager (loaded from hass.data, initialized in __init__.py)
        self._memory_manager: MemoryManager | None = entry_data.get("memory_manager")
        self._memory_enabled = get_config(CONF_ENABLE_MEMORY, DEFAULT_ENABLE_MEMORY)

        # User resolver for multi-user support
        user_mappings = entry.options.get(
            CONF_USER_MAPPINGS, entry.data.get(CONF_USER_MAPPINGS, {})
        )
        enable_presence = get_config(
            CONF_ENABLE_PRESENCE_HEURISTIC, DEFAULT_ENABLE_PRESENCE_HEURISTIC
        )
        self._user_resolver = UserResolver(
            hass, user_mappings, enable_presence_heuristic=enable_presence
        )

    async def _get_tool_registry(self) -> ToolRegistry:
        """Get tool registry, creating it lazily if needed (thread-safe).
        
        This ensures the registry is created after HA startup when all
        domains (scene, automation, etc.) are fully loaded.
        Uses asyncio.Lock to prevent race conditions on parallel requests.
        """
        async with self._tool_registry_lock:
            if self._tool_registry is None:
                self._tool_registry = create_tool_registry(
                    self.hass, self._entry, subentry_data=self._subentry.data,
                    entity_manager=self._entity_manager,
                )
        return self._tool_registry

    def get_registered_tool_names(self) -> list[str]:
        """Return currently registered tool names for diagnostics/UI."""
        if not self._tool_registry:
            return []
        return [tool.name for tool in self._tool_registry.get_all()]

    def get_calendar_reminder_tracker(self) -> CalendarReminderTracker:
        """Return calendar reminder tracker instance."""
        return self._calendar_reminder_tracker

    def _get_config(self, key: str, default: Any = None) -> Any:
        """Get config value from subentry data."""
        return self._subentry.data.get(key, default)

    def _get_global_config(self, key: str, default: Any = None) -> Any:
        """Get config value from main entry options/data."""
        if key in self._entry.options:
            return self._entry.options[key]
        return self._entry.data.get(key, default)

    def _parse_history_redact_patterns(self) -> list[str]:
        """Parse configured history redaction patterns."""
        raw = self._get_config(
            CONF_HISTORY_REDACT_PATTERNS,
            DEFAULT_HISTORY_REDACT_PATTERNS,
        )
        if not raw:
            return []

        if isinstance(raw, list):
            patterns = [str(item).strip() for item in raw]
        else:
            patterns = [
                item.strip()
                for item in str(raw).replace("\n", ",").split(",")
            ]
        return [pattern for pattern in patterns if pattern]

    def _apply_history_redaction(self, text: str, patterns: list[str]) -> str:
        """Redact configured patterns from text for request history persistence."""
        if not text or not patterns:
            return text

        redacted = text
        for pattern in patterns:
            try:
                redacted = re.sub(pattern, "[REDACTED]", redacted, flags=re.IGNORECASE)
            except re.error:
                redacted = redacted.replace(pattern, "[REDACTED]")
        return redacted

    def _sanitize_tool_call_records(
        self,
        tool_call_records: list[ToolCallRecord] | None,
        include_content: bool,
        patterns: list[str],
    ) -> list[ToolCallRecord]:
        """Sanitize tool-call records for safe request history storage."""
        sanitized: list[ToolCallRecord] = []
        for record in tool_call_records or []:
            args_summary = record.arguments_summary if include_content else ""
            args_summary = RequestHistoryStore.truncate(
                args_summary,
                REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH,
            )
            args_summary = self._apply_history_redaction(args_summary, patterns)
            sanitized.append(
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
        return sanitized

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return supported languages."""
        return MATCH_ALL  # Support all languages

    async def warm_cache(self) -> None:
        """Warm the prompt cache by sending a minimal request.
        
        This pre-populates the LLM provider's cache with the system prompt
        and entity index, reducing latency and cost for subsequent requests.
        
        Uses the same code path as real requests to ensure identical prefix.
        """
        _LOGGER.debug("[CACHE-WARMING] Starting prompt cache warm-up...")
        
        try:
            # Build messages using async version (same path as real requests)
            # This ensures calendar context loading is included in the code path
            messages, cached_prefix_length = await self._build_messages_for_llm_async("ping", chat_log=None, dry_run=True)
            tools = (await self._get_tool_registry()).get_schemas()
            
            # Log registered tools for debugging cache issues
            tool_names = [t.get("function", {}).get("name", "unknown") for t in tools]
            _LOGGER.debug("[CACHE-WARMING] Tools (%d): %s", len(tools), tool_names)
            
            async for _ in self._llm_client.chat_stream(
                messages=messages,
                tools=tools,
                cached_prefix_length=cached_prefix_length,
            ):
                pass  # Discard the response
            
            _LOGGER.info("[CACHE-WARMING] Completed successfully (prefix=%d tokens)", cached_prefix_length)
            
            # Send dispatcher signal to update sensors with new metrics
            async_dispatcher_send(
                self.hass,
                f"{DOMAIN}_metrics_updated_{self._subentry.subentry_id}",
            )
            
        except Exception as err:
            _LOGGER.warning("[CACHE-WARMING] Failed: %s", err)

    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
    ) -> ConversationResult:
        """Process a user message and generate a response with streaming.
        
        This method uses real token-by-token streaming for faster TTS responses.
        The assistant pipeline can start TTS synthesis before the full response is ready.
        """
        request_start_time = time.monotonic()
        
        _LOGGER.debug(
            "[USER-REQUEST] New message: user_id=%s, text_length=%d, language=%s, satellite=%s, device=%s",
            user_input.conversation_id,
            len(user_input.text),
            user_input.language,
            getattr(user_input, 'satellite_id', None),
            getattr(user_input, 'device_id', None),
        )
        
        # Quick action bypass (if enabled - disabled by default)
        if self._get_config(CONF_ENABLE_QUICK_ACTIONS, False):
            quick_result = await self._try_quick_action(user_input.text)
            if quick_result:
                _LOGGER.debug("Quick action matched: %s", quick_result[:50])
                # Add response to chat log
                chat_log.async_add_assistant_content_without_tools(
                    conversation.AssistantContent(
                        agent_id=self.entity_id or "",
                        content=quick_result,
                    )
                )
                return self._build_result(user_input, chat_log, quick_result)

        # Build messages for LLM (using our own message format with history)
        # Use async version to include calendar context if enabled
        # Pass satellite_id so LLM knows which device initiated the request
        satellite_id = getattr(user_input, 'satellite_id', None)
        device_id = getattr(user_input, 'device_id', None)

        # Detect programmatic/timer callbacks (no voice pipeline listening).
        # Computed once here and reused later for announcement logic.
        is_silent_call = (
            user_input.conversation_id is None
            and not satellite_id
            and device_id is not None
            and not getattr(chat_log, 'delta_listener', None)
        )

        # For timer callbacks, wrap the message with context so the LLM
        # knows to deliver a friendly reminder instead of processing it
        # as a regular user request.
        effective_text = user_input.text
        if is_silent_call:
            effective_text = (
                "[TIMER CALLBACK] The following text is a timer/reminder that just expired. "
                "Deliver it as a friendly, natural reminder to the user. "
                "Do NOT treat it as a new user request. Just announce the reminder warmly.\n\n"
                f"{user_input.text}"
            )
            _LOGGER.debug(
                "[TIMER-CALLBACK] Detected timer callback, wrapping message with context"
            )

        # Resolve user for memory personalization
        context_user_id = None
        input_context = getattr(user_input, 'context', None)
        if input_context:
            context_user_id = getattr(input_context, 'user_id', None)
        
        session_user_id = self._conversation_manager.get_active_user(
            user_input.conversation_id or ""
        )
        
        user_id = await self._user_resolver.resolve_user(
            satellite_id=satellite_id,
            device_id=device_id,
            session_user_id=session_user_id,
            context_user_id=context_user_id,
        )
        
        messages, cached_prefix_length = await self._build_messages_for_llm_async(
            effective_text,
            chat_log,
            satellite_id=satellite_id,
            device_id=device_id,
            conversation_id=user_input.conversation_id,
            user_id=user_id,
        )
        tools = (await self._get_tool_registry()).get_schemas()
        
        # Set device_id on tools so timer intents know which device to use
        (await self._get_tool_registry()).set_device_id(device_id)
        # Set satellite_id on tools for satellite-aware player resolution
        (await self._get_tool_registry()).set_satellite_id(satellite_id)
        # Set conversation_agent_id so timer commands route back to this agent
        (await self._get_tool_registry()).set_conversation_agent_id(self.entity_id)
        
        # Set user context on memory tool
        tool_registry = await self._get_tool_registry()
        memory_tool = tool_registry.get("memory")
        if memory_tool:
            memory_tool._current_user_id = user_id
            # Set callback for switch_user action
            conv_id = user_input.conversation_id or ""
            memory_tool._switch_user_callback = lambda uid: self._conversation_manager.set_active_user(conv_id, uid)
        
        # Log registered tools for debugging cache issues
        tool_names = [t.get("function", {}).get("name", "unknown") for t in tools]
        _LOGGER.debug("[USER-REQUEST] Tools (%d): %s", len(tools), tool_names)
        
        _LOGGER.debug(
            "[USER-REQUEST] Sending to LLM: messages=%d, tools=%d, cache_prefix=%d",
            len(messages),
            len(tools),
            cached_prefix_length,
        )

        try:
            # Use streaming with tool loop
            final_content, await_response_called, llm_iterations, tool_call_records = await self._call_llm_streaming_with_tools(
                messages=messages,
                tools=tools,
                cached_prefix_length=cached_prefix_length,
                chat_log=chat_log,
                conversation_id=user_input.conversation_id,
            )

            # Determine if conversation should continue based on await_response tool
            continue_conversation = await_response_called
            
            # Override: If ask_followup is disabled, never continue
            ask_followup = self._get_config(CONF_ASK_FOLLOWUP, DEFAULT_ASK_FOLLOWUP)
            if not ask_followup:
                continue_conversation = False

            # Detect cancel/nevermind via tool call (LLM calls nevermind tool)
            is_nevermind = self._detect_nevermind_from_tool_calls(tool_call_records)
            if is_nevermind:
                _LOGGER.debug("[USER-REQUEST] nevermind tool detected cancel/nevermind")

            # Clean response for TTS if enabled
            final_response = final_content
            if self._get_config(CONF_CLEAN_RESPONSES, DEFAULT_CLEAN_RESPONSES):
                language = self._get_config(CONF_LANGUAGE, "")
                final_response = clean_for_tts(final_response, language)
            else:
                # Always remove URLs from TTS output even if full cleaning is disabled
                # URLs are never useful when spoken aloud
                from .utils import remove_urls_for_tts
                final_response = remove_urls_for_tts(final_response)

            _LOGGER.debug("Streaming response complete. continue=%s", continue_conversation)

            # For silent/timer calls, proactively announce the response on the originating satellite.
            if is_silent_call and final_response.strip():
                sat_entity_id = await self._find_satellite_entity_id(device_id)
                if sat_entity_id:
                    _LOGGER.info(
                        "[TIMER-ANNOUNCE] Announcing on %s (device=%s)",
                        sat_entity_id, device_id,
                    )
                    try:
                        await self.hass.services.async_call(
                            "assist_satellite",
                            "announce",
                            {"entity_id": sat_entity_id, "message": final_response},
                            blocking=False,
                        )
                    except Exception as announce_err:
                        _LOGGER.warning(
                            "[TIMER-ANNOUNCE] Failed to announce on %s: %s",
                            sat_entity_id, announce_err,
                        )

            return self._build_result(
                user_input, chat_log, final_response, continue_conversation,
                user_id=user_id,
                request_start_time=request_start_time,
                llm_iterations=llm_iterations,
                tool_call_records=tool_call_records,
                is_nevermind=is_nevermind,
                is_system_call=is_silent_call,
            )

        except Exception as err:
            _LOGGER.error("Error processing conversation: %s", err)
            language_hint = (getattr(user_input, "language", "") or "").lower()
            if "de" in language_hint:
                error_msg = "Entschuldigung, es ist ein Fehler aufgetreten. Bitte versuche es erneut."
            else:
                error_msg = "Sorry, something went wrong. Please try again."
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=self.entity_id or "",
                    content=error_msg,
                )
            )
            return self._build_result(
                user_input, chat_log, error_msg, continue_conversation=False,
                user_id=user_id,
                request_start_time=request_start_time,
                llm_iterations=0,
                tool_call_records=[],
                request_success=False,
                request_error=str(err),
                is_system_call=is_silent_call,
            )

    async def _call_llm_streaming_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        cached_prefix_length: int,
        chat_log: ChatLog,
        conversation_id: str | None = None,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ) -> tuple[str, bool, int, list[ToolCallRecord]]:
        """Call LLM with streaming and tool execution loop."""
        return await _call_llm_streaming_with_tools_impl(
            self, messages, tools, cached_prefix_length, chat_log,
            conversation_id=conversation_id, max_iterations=max_iterations,
        )

    async def _create_delta_stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        cached_prefix_length: int,
    ) -> AsyncGenerator[AssistantContentDeltaDict, None]:
        """Create a delta stream from LLM response for HA's ChatLog."""
        async for delta in _create_delta_stream_impl(self, messages, tools, cached_prefix_length):
            yield delta

    async def _wrap_response_as_delta_stream(
        self,
        content: str,
        tool_calls: list[ToolCall],
    ) -> AsyncGenerator[AssistantContentDeltaDict, None]:
        """Wrap a non-streaming LLM response as a delta stream for ChatLog."""
        async for delta in _wrap_response_as_delta_stream_impl(self, content, tool_calls):
            yield delta

    def _track_entity_from_tool_call(
        self,
        conversation_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        """Track entity from a successful tool call for pronoun resolution.
        
        Extracts entity_id from control tool calls and tracks them in the
        conversation session so the LLM can resolve pronouns like "it", "that".
        """
        # Tools that operate on entities
        entity_tools = {
            "control",
            "control_entity",
            "control_light",
            "control_climate",
            "control_media",
            "control_cover",
            "get_entity_state",
            "get_entity_history",
        }
        
        if tool_name not in entity_tools:
            return
        
        entity_id = arguments.get("entity_id")
        entity_ids = arguments.get("entity_ids")

        # Collect all entity IDs to track
        ids_to_track: list[str] = []
        if entity_ids and isinstance(entity_ids, list):
            ids_to_track.extend(entity_ids)
        elif entity_id:
            ids_to_track.append(entity_id)

        if not ids_to_track:
            return

        # Determine action type
        if tool_name.startswith("control"):
            action = "controlled"
        elif tool_name == "get_entity_history":
            action = "queried"
        else:
            action = "queried"

        for eid in ids_to_track:
            state = self.hass.states.get(eid)
            friendly_name = state.attributes.get("friendly_name", eid) if state else eid
            self._conversation_manager.add_recent_entity(
                conversation_id, eid, friendly_name, action
            )
            _LOGGER.debug(
                "[CONTEXT] Tracked entity for pronoun resolution: %s (%s) - %s",
                eid,
                friendly_name,
                action,
            )

    async def _build_system_prompt(self) -> str:
        """Build or return cached system prompt based on configuration."""
        return await _build_system_prompt_impl(self)

    async def _get_calendar_context(self, dry_run: bool = False) -> str:
        """Get upcoming calendar events for context injection."""
        return await _get_calendar_context_impl(self, dry_run=dry_run)

    async def _build_messages_for_llm_async(
        self,
        user_text: str,
        chat_log: ChatLog | None = None,
        satellite_id: str | None = None,
        device_id: str | None = None,
        conversation_id: str | None = None,
        user_id: str = "default",
        dry_run: bool = False,
    ) -> tuple[list[ChatMessage], int]:
        """Build the message list for LLM request (async version with calendar context)."""
        return await _build_messages_for_llm_async_impl(
            self, user_text, chat_log, satellite_id=satellite_id,
            device_id=device_id, conversation_id=conversation_id,
            user_id=user_id, dry_run=dry_run,
        )

    async def _build_messages_for_llm(
        self,
        user_text: str,
        chat_log: ChatLog | None = None,
        calendar_context: str = "",
        satellite_id: str | None = None,
        device_id: str | None = None,
        recent_entities_context: str = "",
        user_id: str = "default",
    ) -> tuple[list[ChatMessage], int]:
        """Build the message list for LLM request."""
        return await _build_messages_for_llm_impl(
            self, user_text, chat_log, calendar_context=calendar_context,
            satellite_id=satellite_id, device_id=device_id,
            recent_entities_context=recent_entities_context, user_id=user_id,
        )

    @staticmethod
    def _detect_nevermind_from_tool_calls(tool_call_records: list) -> bool:
        """Check if the nevermind tool was called during this interaction.

        Returns True if the LLM called the nevermind tool, indicating
        the user wanted to cancel/abort.
        """
        if not tool_call_records:
            return False
        return any(
            getattr(r, "tool_name", None) == "nevermind" or getattr(r, "name", None) == "nevermind"
            for r in tool_call_records
        )

    async def _try_quick_action(self, text: str) -> str | None:
        """Try to handle simple commands without LLM.

        Returns response string if handled, None if LLM is needed.
        """
        text_lower = text.lower().strip()

        # "turn on/off the [entity]" pattern
        on_match = re.match(
            r"(?:turn on|switch on|enable|activate)\s+(?:the\s+)?(.+)",
            text_lower,
        )
        off_match = re.match(
            r"(?:turn off|switch off|disable|deactivate)\s+(?:the\s+)?(.+)",
            text_lower,
        )

        if on_match or off_match:
            action = "turn_on" if on_match else "turn_off"
            match = on_match if on_match else off_match
            entity_name = match.group(1).strip() if match else ""

            # Find matching entity
            entities = self._entity_manager.get_all_entities()
            matches = [
                e for e in entities
                if entity_name in e.friendly_name.lower()
                or entity_name in e.entity_id.lower()
            ]

            if len(matches) == 1:
                entity = matches[0]
                result = await (await self._get_tool_registry()).execute(
                    "control",
                    {"entity_id": entity.entity_id, "action": action},
                )
                if result.success:
                    action_text = "on" if action == "turn_on" else "off"
                    return f"Turned {action_text} {entity.friendly_name}."

        return None

    async def _find_satellite_entity_id(self, device_id: str) -> str | None:
        """Find the assist_satellite entity ID for a device.

        Used to announce timer command responses on the originating satellite
        when the response would otherwise be silently discarded by HA Core.
        """
        try:
            entity_registry = er.async_get(self.hass)
            for entry in entity_registry.entities.values():
                if (
                    entry.device_id == device_id
                    and entry.domain == "assist_satellite"
                    and not entry.disabled
                ):
                    return entry.entity_id
        except Exception as err:
            _LOGGER.debug("[TIMER-ANNOUNCE] Error finding satellite: %s", err)
        return None

    def _build_result(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
        response_text: str,
        continue_conversation: bool = True,
        user_id: str = "default",
        request_start_time: float | None = None,
        llm_iterations: int = 1,
        tool_call_records: list | None = None,
        request_success: bool = True,
        request_error: str | None = None,
        is_nevermind: bool = False,
        is_system_call: bool = False,
    ) -> ConversationResult:
        """Build a ConversationResult from the chat log."""
        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(response_text)
        
        # Record conversation stats for user
        if self._memory_enabled and self._memory_manager and user_id != "default":
            per_request_tokens = 0
            if self._llm_client and hasattr(self._llm_client, "metrics"):
                m = self._llm_client.metrics
                per_request_tokens = getattr(m, "_last_prompt_tokens", 0) + getattr(m, "_last_completion_tokens", 0)
            self._memory_manager.record_conversation(user_id, tokens_used=per_request_tokens)
        
        # Record request history
        if request_start_time is not None:
            elapsed_ms = (time.monotonic() - request_start_time) * 1000
            
            # Get per-request token counts
            prompt_tokens = 0
            completion_tokens = 0
            cached_tokens = 0
            if self._llm_client and hasattr(self._llm_client, "metrics"):
                m = self._llm_client.metrics
                prompt_tokens = getattr(m, "_last_prompt_tokens", 0)
                completion_tokens = getattr(m, "_last_completion_tokens", 0)
                cached_tokens = getattr(m, "_last_cached_tokens", 0)
            
            history_store = self.hass.data.get(DOMAIN, {}).get(
                self._entry.entry_id, {}
            ).get("request_history")
            
            if history_store:
                include_history_content = bool(
                    self._get_config(
                        CONF_ENABLE_REQUEST_HISTORY_CONTENT,
                        DEFAULT_ENABLE_REQUEST_HISTORY_CONTENT,
                    )
                )
                retention_days = int(
                    self._get_config(
                        CONF_HISTORY_RETENTION_DAYS,
                        DEFAULT_HISTORY_RETENTION_DAYS,
                    )
                )
                retention_days = max(retention_days, 1)
                redact_patterns = self._parse_history_redact_patterns()

                input_text = ""
                response_history_text = ""
                if include_history_content:
                    input_text = RequestHistoryStore.truncate(
                        user_input.text,
                        REQUEST_HISTORY_INPUT_MAX_LENGTH,
                    )
                    response_history_text = RequestHistoryStore.truncate(
                        response_text,
                        REQUEST_HISTORY_RESPONSE_MAX_LENGTH,
                    )

                input_text = self._apply_history_redaction(input_text, redact_patterns)
                response_history_text = self._apply_history_redaction(
                    response_history_text,
                    redact_patterns,
                )
                sanitized_tool_calls = self._sanitize_tool_call_records(
                    tool_call_records,
                    include_history_content,
                    redact_patterns,
                )

                history_store.prune_older_than_days(retention_days)

                entry = RequestHistoryEntry(
                    id=RequestHistoryStore.generate_id(),
                    timestamp=dt_util.now().isoformat(),
                    agent_id=self._subentry.subentry_id,
                    agent_name=self._subentry.title,
                    conversation_id=user_input.conversation_id,
                    user_id=user_id,
                    input_text=input_text,
                    response_text=response_history_text,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cached_tokens=cached_tokens,
                    response_time_ms=elapsed_ms,
                    llm_provider=self._get_config(CONF_LLM_PROVIDER, DEFAULT_LLM_PROVIDER),
                    model=self._get_config(CONF_MODEL, DEFAULT_MODEL),
                    llm_iterations=llm_iterations,
                    tools_used=sanitized_tool_calls,
                    success=request_success,
                    error=request_error,
                    is_nevermind=is_nevermind,
                    is_system_call=is_system_call,
                )
                history_store.add_entry(entry)
                self.hass.async_create_task(history_store.async_save())
        
        # Signal sensors to update their state (per subentry)
        async_dispatcher_send(
            self.hass,
            f"{DOMAIN}_metrics_updated_{self._subentry.subentry_id}",
        )
        
        return ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id,
            continue_conversation=continue_conversation,
        )

    async def async_added_to_hass(self) -> None:
        """Load persisted state when entity is added."""
        await super().async_added_to_hass()
        await self._calendar_reminder_tracker.async_load()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        await self._calendar_reminder_tracker.async_save()
        if self._llm_client:
            await self._llm_client.close()
