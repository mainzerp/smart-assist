"""Conversation entity for Smart Assist - Home Assistant Assist Pipeline integration."""

from __future__ import annotations

import asyncio
import logging
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
    from homeassistant.helpers import intent, device_registry as dr
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError as e:
    _LOGGER.error("Smart Assist: Failed to import HA core modules: %s", e)
    raise

try:
    from .const import (
        CONF_API_KEY,
        CONF_ASK_FOLLOWUP,
        CONF_CACHE_TTL_EXTENDED,
        CONF_CALENDAR_CONTEXT,
        CONF_CLEAN_RESPONSES,
        CONF_CONFIRM_CRITICAL,
        CONF_ENABLE_MEMORY,
        CONF_ENABLE_PRESENCE_HEURISTIC,
        CONF_ENABLE_PROMPT_CACHING,
        CONF_ENABLE_QUICK_ACTIONS,
        CONF_EXPOSED_ONLY,
        CONF_GROQ_API_KEY,
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
        CONF_USER_SYSTEM_PROMPT,
        DEFAULT_ASK_FOLLOWUP,
        DEFAULT_CACHE_TTL_EXTENDED,
        DEFAULT_CALENDAR_CONTEXT,
        DEFAULT_CLEAN_RESPONSES,
        DEFAULT_ENABLE_MEMORY,
        DEFAULT_ENABLE_PRESENCE_HEURISTIC,
        DEFAULT_LLM_PROVIDER,
        DEFAULT_MAX_HISTORY,
        DEFAULT_MAX_TOKENS,
        DEFAULT_MODEL,
        DEFAULT_PROVIDER,
        DEFAULT_TEMPERATURE,
        DEFAULT_USER_SYSTEM_PROMPT,
        DOMAIN,
        LLM_PROVIDER_GROQ,
        LLM_PROVIDER_OLLAMA,
        LOCALE_TO_LANGUAGE,
        MAX_CONSECUTIVE_FOLLOWUPS,
        MAX_TOOL_ITERATIONS,
        OLLAMA_DEFAULT_KEEP_ALIVE,
        OLLAMA_DEFAULT_MODEL,
        OLLAMA_DEFAULT_NUM_CTX,
        OLLAMA_DEFAULT_TIMEOUT,
        OLLAMA_DEFAULT_URL,
        TTS_STREAM_MIN_CHARS,
    )
    from .context import EntityManager
    from .context.calendar_reminder import CalendarReminderTracker
    from .context.conversation import ConversationManager
    from .context.memory import MemoryManager
    from .context.user_resolver import UserResolver
    from .llm import ChatMessage, OpenRouterClient, GroqClient, create_llm_client
    from .llm.models import MessageRole, ToolCall
    from .tools import create_tool_registry, ToolRegistry
    from .utils import clean_for_tts, get_config_value
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
        
        # For OpenRouterClient, set additional caching options
        if hasattr(self._llm_client, 'enable_caching'):
            self._llm_client._enable_caching = get_config(CONF_ENABLE_PROMPT_CACHING, True)
        if hasattr(self._llm_client, '_cache_ttl_extended'):
            self._llm_client._cache_ttl_extended = get_config(CONF_CACHE_TTL_EXTENDED, DEFAULT_CACHE_TTL_EXTENDED)
        
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
        
        # Calendar reminder tracker for staged reminders
        self._calendar_reminder_tracker = CalendarReminderTracker()
        
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
                    self.hass, self._entry, subentry_data=self._subentry.data
                )
        return self._tool_registry

    def _get_config(self, key: str, default: Any = None) -> Any:
        """Get config value from subentry data."""
        return self._subentry.data.get(key, default)

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
            messages, cached_prefix_length = await self._build_messages_for_llm_async("ping", chat_log=None)
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
        
        # Resolve user for memory personalization
        context_user_id = None
        input_context = getattr(user_input, 'context', None)
        if input_context:
            context_user_id = getattr(input_context, 'user_id', None)
        
        session_user_id = self._conversation_manager.get_active_user(
            user_input.conversation_id or ""
        )
        
        user_id = self._user_resolver.resolve_user(
            satellite_id=satellite_id,
            device_id=device_id,
            session_user_id=session_user_id,
            context_user_id=context_user_id,
        )
        
        messages, cached_prefix_length = await self._build_messages_for_llm_async(
            user_input.text,
            chat_log,
            satellite_id=satellite_id,
            device_id=device_id,
            conversation_id=user_input.conversation_id,
            user_id=user_id,
        )
        tools = (await self._get_tool_registry()).get_schemas()
        
        # Set device_id on tools so timer intents know which device to use
        (await self._get_tool_registry()).set_device_id(device_id)
        
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
            final_content, await_response_called = await self._call_llm_streaming_with_tools(
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
            elif not continue_conversation and final_content.strip().endswith("?"):
                # Auto-detect: If response ends with question mark but await_response wasn't called,
                # still allow conversation to continue (LLM forgot to call the tool)
                _LOGGER.debug("[USER-REQUEST] Auto-detected question in response, enabling continue_conversation")
                continue_conversation = True

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

            return self._build_result(user_input, chat_log, final_response, continue_conversation)

        except Exception as err:
            _LOGGER.error("Error processing conversation: %s", err)
            error_msg = f"Sorry, I encountered an error: {err}"
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=self.entity_id or "",
                    content=error_msg,
                )
            )
            return self._build_result(user_input, chat_log, error_msg, continue_conversation=False)

    async def _call_llm_streaming_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        cached_prefix_length: int,
        chat_log: ChatLog,
        conversation_id: str | None = None,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ) -> tuple[str, bool]:
        """Call LLM with streaming and handle tool calls in-loop.
        
        Implements streaming with tool execution. Content deltas are sent
        to the ChatLog's delta_listener for real-time TTS streaming.
        Tool calls are executed between LLM iterations.
        
        Args:
            messages: Initial message list for LLM
            tools: Tool schemas for LLM
            cached_prefix_length: Number of messages to cache
            chat_log: Home Assistant ChatLog for streaming
            conversation_id: Optional conversation ID for entity tracking
            max_iterations: Maximum tool call iterations
        
        Returns:
            Tuple of (final_response_text, await_response_called)
            - final_response_text: The final response after all tool calls
            - await_response_called: True if await_response tool was called
        """
        iteration = 0
        working_messages = messages.copy()
        final_content = ""
        await_response_called = False
        
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
                        self.entity_id or "",
                        self._create_delta_stream(
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
                response = await self._llm_client.chat(
                    messages=working_messages,
                    tools=tools,
                )
                if response.content:
                    iteration_content = response.content
                if response.tool_calls:
                    for tc in response.tool_calls:
                        tool_calls.append(tc)
                
                # If this is the final iteration (has content, no tool calls),
                # we need to properly trigger TTS streaming for Companion App
                if iteration_content and not response.tool_calls:
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
            
            # If no tool calls, we're done
            if not tool_calls:
                _LOGGER.debug("[USER-REQUEST] Complete (iteration %d, no tool calls)", iteration)
                return final_content, await_response_called
            
            # Check if await_response is in the tool calls (signal, not executed with others)
            await_response_calls = [tc for tc in tool_calls if tc.name == "await_response"]
            other_tool_calls = [tc for tc in tool_calls if tc.name != "await_response"]
            
            if await_response_calls:
                await_response_called = True
                _LOGGER.debug("[USER-REQUEST] await_response tool called - conversation will continue")
                
                # Check consecutive followup limit to prevent infinite loops
                # (e.g., satellite triggered by TV audio causing repeated clarification requests)
                if conversation_id:
                    followup_count = self._conversation_manager.increment_followup(conversation_id)
                    if followup_count >= MAX_CONSECUTIVE_FOLLOWUPS:
                        _LOGGER.warning(
                            "[USER-REQUEST] Max consecutive followups (%d) reached - aborting to prevent loop",
                            MAX_CONSECUTIVE_FOLLOWUPS
                        )
                        # Return a polite abort message instead of continuing
                        return "I did not understand. Please try again.", False
                
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
                    return final_content, await_response_called
            
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
                    result = await (await self._get_tool_registry()).execute(
                        tool_call.name, tool_call.arguments
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
                        working_messages.append(
                            ChatMessage(
                                role=MessageRole.TOOL,
                                content=f"Error: {item}",
                                tool_call_id=failed_tc.id,
                                name=failed_tc.name,
                            )
                        )
                        continue
                    tool_call, result = item
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
                        self._track_entity_from_tool_call(
                            conversation_id, tool_call.name, tool_call.arguments
                        )
                
                # Reset consecutive followup counter after successful tool execution
                # This breaks the followup loop when user provides meaningful input
                if conversation_id:
                    self._conversation_manager.reset_followups(conversation_id)
                    _LOGGER.debug("[USER-REQUEST] Reset followup counter after tool execution")
            else:
                # Only await_response was called, no other tools to execute
                # This shouldn't happen normally since we return above, but handle it
                pass
        
        # Max iterations reached
        _LOGGER.warning("Max tool iterations (%d) reached", max_iterations)
        return final_content, await_response_called

    async def _create_delta_stream(
        self,
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
        
        async for delta in self._llm_client.chat_stream_full(
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
        if not entity_id:
            return
        
        # Get friendly name from state
        state = self.hass.states.get(entity_id)
        if state:
            friendly_name = state.attributes.get("friendly_name", entity_id)
        else:
            friendly_name = entity_id
        
        # Determine action type
        if tool_name.startswith("control"):
            action = "controlled"
        elif tool_name == "get_entity_history":
            action = "queried"
        else:
            action = "queried"
        
        # Track in conversation manager
        self._conversation_manager.add_recent_entity(
            conversation_id, entity_id, friendly_name, action
        )
        _LOGGER.debug(
            "[CONTEXT] Tracked entity for pronoun resolution: %s (%s) - %s",
            entity_id,
            friendly_name,
            action,
        )

    async def _build_system_prompt(self) -> str:
        """Build or return cached system prompt based on configuration.
        
        System prompt is always in English (best LLM performance).
        Only the response language instruction is configurable.
        
        The prompt is cached after first build since config rarely changes.
        If config is updated, the entity is reloaded anyway.
        """
        # Return cached prompt if available
        if self._cached_system_prompt is not None:
            return self._cached_system_prompt
        
        language = self._get_config(CONF_LANGUAGE, "")
        
        # Determine language instruction for response
        if not language or language == "auto":
            # Auto-detect: use Home Assistant's configured language
            ha_language = self.hass.config.language  # e.g., "de-DE", "en-US"
            locale_prefix = ha_language.split("-")[0].lower()  # "de", "en", etc.
            
            if locale_prefix in LOCALE_TO_LANGUAGE:
                english_name, native_name = LOCALE_TO_LANGUAGE[locale_prefix]
                language_instruction = f"Always respond in {english_name} ({native_name})."
            else:
                # Fallback: use the locale as-is
                language_instruction = f"Always respond in the language with code '{ha_language}'."
        else:
            # User-specified language - use directly
            language_instruction = f"Always respond in {language}."
        
        confirm_critical = self._get_config(CONF_CONFIRM_CRITICAL, True)
        exposed_only = self._get_config(CONF_EXPOSED_ONLY, True)
        caching_enabled = self._get_config(CONF_ENABLE_PROMPT_CACHING, True)
        ask_followup = self._get_config(CONF_ASK_FOLLOWUP, DEFAULT_ASK_FOLLOWUP)
        
        parts = []
        
        # Base prompt - minimal, role defined in user prompt
        # Language instruction is emphasized and placed prominently
        parts.append(f"""You are a smart home assistant.

## LANGUAGE REQUIREMENT [CRITICAL]
{language_instruction} This applies to ALL responses including follow-up questions, confirmations, and error messages. Never mix languages.""")
        
        # Response format guidelines
        parts.append("""
## Response Format
- Keep responses brief (1-2 sentences for actions, 2-3 for information)
- Confirm actions concisely: "Light is on." not "I have successfully turned on the light for you."
- ALWAYS use tools to check states - never guess or assume values
- Use plain text only - no markdown, no bullet points, no formatting
- Responses are spoken aloud (TTS) - avoid URLs, special characters, abbreviations""")
        
        # Response rules with conversation continuation marker
        if ask_followup:
            parts.append("""
## Follow-up Behavior
- Offer follow-up when useful (ambiguous request, multiple options)
- Do NOT offer follow-up for every simple action
- For simple completed actions, just confirm briefly without asking follow-up

## MANDATORY: Questions Require await_response Tool
If you need to ask the user something, you MUST use the await_response tool.
Without it, the user CANNOT respond to your question.

Example (note: always use the configured response language, not English):
await_response(message="[your question in user's language]", reason="follow_up")

If your response ends with a question mark (?), you MUST call await_response.""")
        else:
            parts.append("""
## Response Rules
- Do NOT ask follow-up questions
- Keep responses action-focused
- If uncertain about entity, ask for clarification""")
        
        # Entity lookup strategy
        if caching_enabled:
            parts.append("""
## Entity Lookup
1. Check ENTITY INDEX first to find entity_ids
2. Only use get_entities tool if not found in index
3. Use get_entity_state before actions to verify current state""")
        else:
            parts.append("""
## Entity Lookup
- Use get_entities with domain filter to find entities
- Use get_entity_state before actions to verify current state""")
        
        # Pronoun resolution hint
        parts.append("""
## Pronoun Resolution
When user says "it", "that", "the same one", check [Recent Entities] in context to identify the referenced entity.""")
        
        # Calendar reminders instruction (if enabled) - compact version
        calendar_enabled = self._get_config(CONF_CALENDAR_CONTEXT, DEFAULT_CALENDAR_CONTEXT)
        if calendar_enabled:
            parts.append("""
## Calendar Reminders [MANDATORY]
When CURRENT CONTEXT contains '## Calendar Reminders [ACTION REQUIRED]':
- ALWAYS mention the reminder in your response (even for small talk)
- Keep it brief: "Heads up: Meeting in 1 hour. [your response]" """)
        
        # Control instructions - compact
        parts.append("""
## Entity Control
Use 'control' tool for lights, switches, covers, fans, climate, locks, etc.
Domain auto-detected from entity_id.""")

        # Music/Radio instructions - only if music_assistant tool is registered
        if (await self._get_tool_registry()).has_tool("music_assistant"):
            parts.append("""
## Music/Radio Playback [IMPORTANT]
For ALL music, radio, or media playback requests, use the 'music_assistant' tool:
- action='play', query='[song/artist/radio station]', media_type='track/album/artist/playlist/radio'
- For player selection: Check [Current Assist Satellite] context and use your satellite-to-player mapping from your instructions
- Do NOT use 'control' tool for music/radio - it cannot search or stream content""")
        
        # Send/notification instructions - only if send tool is registered
        if (await self._get_tool_registry()).has_tool("send"):
            parts.append("""
## Sending Content
You can send content (links, text, messages) to devices using the 'send' tool.
- Offer when you have useful links or information to share
- User specifies target device (e.g., "Patrics Handy", "my phone", "Telegram")
- IMPORTANT: After sending, respond briefly: "Sent to [device]." or "I've sent it to your [device]."
- Do NOT repeat the content in your spoken response - the user will see it on the device""")
        
        # Critical actions confirmation
        if confirm_critical:
            parts.append("""
## Critical Actions
Ask for confirmation before: locking doors, arming alarms, disabling security.""")
        
        # Memory instructions (if enabled)
        if self._memory_enabled:
            parts.append("""
## User Memory [IMPORTANT]
Known user memories are injected as [USER MEMORY] in context. Use them to personalize responses.
- SAVE new preferences, names, patterns, and instructions via the 'memory' tool
- DO NOT re-save information already in [USER MEMORY]
- When user says "I am [Name]" or "This is [Name]", use memory(action='switch_user', content='[name]')
- Keep memory content concise (max 100 chars)
- Use appropriate categories: preference, named_entity, pattern, instruction, fact""")
        
        # Exposed only notice
        if exposed_only:
            parts.append("""
## Notice
Only exposed entities are available.""")
        
        # Error handling - compact
        parts.append("""
## Errors
If action fails or entity not found, explain briefly and suggest alternatives.""")
        
        # Cache the built prompt for subsequent calls
        self._cached_system_prompt = "\n".join(parts)
        _LOGGER.debug("System prompt cached (length: %d chars)", len(self._cached_system_prompt))
        
        return self._cached_system_prompt

    async def _get_calendar_context(self) -> str:
        """Get upcoming calendar events for context injection.
        
        Returns reminders for events in appropriate reminder windows.
        Only fetches if calendar_context is enabled in config.
        
        Returns:
            Formatted string with calendar reminders, or empty string if none.
        """
        calendar_enabled = self._get_config(CONF_CALENDAR_CONTEXT, DEFAULT_CALENDAR_CONTEXT)
        _LOGGER.debug("Calendar context enabled: %s", calendar_enabled)
        if not calendar_enabled:
            return ""
        
        try:
            from datetime import timedelta
            from homeassistant.util import dt as dt_util
            
            now = dt_util.now()
            # Get events for next 28 hours to cover day-before reminders
            end = now + timedelta(hours=28)
            
            # Get all calendar entities
            calendars = [
                state.entity_id
                for state in self.hass.states.async_all()
                if state.entity_id.startswith("calendar.")
            ]
            
            _LOGGER.debug("Found %d calendar entities: %s", len(calendars), calendars)
            
            if not calendars:
                return ""
            
            # Fetch events from all calendars
            all_events: list[dict] = []
            for cal_id in calendars:
                try:
                    result = await self.hass.services.async_call(
                        "calendar",
                        "get_events",
                        {
                            "entity_id": cal_id,
                            "start_date_time": now.isoformat(),
                            "end_date_time": end.isoformat(),
                        },
                        blocking=True,
                        return_response=True,
                    )
                    
                    _LOGGER.debug("Calendar %s result: %s", cal_id, result)
                    
                    if result and cal_id in result:
                        # Extract owner from calendar entity
                        state = self.hass.states.get(cal_id)
                        if state and state.attributes.get("friendly_name"):
                            owner = state.attributes["friendly_name"]
                        else:
                            name = cal_id.split(".", 1)[-1]
                            owner = name.replace("_", " ").title()
                        
                        for event in result[cal_id].get("events", []):
                            all_events.append({
                                "summary": event.get("summary", "Termin"),
                                "start": event.get("start"),
                                "owner": owner,
                            })
                except Exception as err:
                    _LOGGER.debug("Failed to fetch calendar events from %s: %s", cal_id, err)
            
            _LOGGER.debug("Found %d events total: %s", len(all_events), all_events)
            
            if not all_events:
                return ""
            
            # Get reminders that should be shown
            reminders = self._calendar_reminder_tracker.get_reminders(all_events, now)
            
            _LOGGER.debug("Reminders to show: %s", reminders)
            
            if not reminders:
                return ""
            
            # Format with emphasis markers for LLM attention
            reminder_text = "\n".join(f"- {r}" for r in reminders)
            return f"\n## Calendar Reminders [ACTION REQUIRED]\n{reminder_text}"
            
        except Exception as err:
            _LOGGER.warning("Failed to get calendar context: %s", err)
            return ""

    async def _build_messages_for_llm_async(
        self,
        user_text: str,
        chat_log: ChatLog | None = None,
        satellite_id: str | None = None,
        device_id: str | None = None,
        conversation_id: str | None = None,
        user_id: str = "default",
    ) -> tuple[list[ChatMessage], int]:
        """Build the message list for LLM request (async version with calendar context).
        
        Args:
            user_text: The current user message
            chat_log: Optional ChatLog containing conversation history
            satellite_id: Optional satellite entity_id that initiated the request
            device_id: Optional device_id that initiated the request
            conversation_id: Optional conversation ID for recent entity context
            user_id: Resolved user identifier for memory personalization
            
        Returns:
            Tuple of (messages, cached_prefix_length)
        """
        # Get calendar context asynchronously
        calendar_context = await self._get_calendar_context()
        _LOGGER.debug("Calendar context from _get_calendar_context: len=%d", len(calendar_context) if calendar_context else 0)
        
        # Get recent entities context for pronoun resolution
        recent_entities_context = ""
        if conversation_id:
            recent_entities_context = self._conversation_manager.get_recent_entities_context(
                conversation_id
            )
            if recent_entities_context:
                _LOGGER.debug("Recent entities context: %s", recent_entities_context)
        
        # Build base messages (now async due to tool registry access)
        return await self._build_messages_for_llm(
            user_text, chat_log, calendar_context, satellite_id, device_id,
            recent_entities_context, user_id=user_id,
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
        """Build the message list for LLM request.
        
        Message order optimized for prompt caching (static prefix first):
        1. System prompt (static/cached)
        2. User system prompt (static/cached)  
        3. Entity index (static/cached - changes only when entities change)
        4. User memory injection (semi-static - changes when memories change)
        5. Conversation history (dynamic)
        6. Current context + user message (dynamic - time, states, calendar, recent entities)
        
        Args:
            user_text: The current user message
            chat_log: Optional ChatLog containing conversation history
            calendar_context: Optional calendar reminder context
            satellite_id: Optional satellite entity_id
            device_id: Optional device_id
            recent_entities_context: Optional recent entities for pronoun resolution
            user_id: Resolved user identifier for memory personalization
            
        Returns:
            Tuple of (messages, cached_prefix_length) where cached_prefix_length
            is the number of static messages that should be cached.
        """
        messages: list[ChatMessage] = []
        cached_prefix_length = 0  # Track how many messages are static/cacheable

        # 1. Technical system prompt (cached)
        system_prompt = await self._build_system_prompt()
        messages.append(
            ChatMessage(role=MessageRole.SYSTEM, content=system_prompt)
        )
        cached_prefix_length += 1

        # 2. User system prompt (cached - optional)
        user_prompt = self._get_config(
            CONF_USER_SYSTEM_PROMPT, DEFAULT_USER_SYSTEM_PROMPT
        )
        if user_prompt:
            messages.append(
                ChatMessage(role=MessageRole.SYSTEM, content=user_prompt)
            )
            cached_prefix_length += 1

        # 3. Entity index (cached - only if caching is enabled)
        caching_enabled = self._get_config(CONF_ENABLE_PROMPT_CACHING, True)
        
        if caching_enabled:
            entity_index, index_hash = self._entity_manager.get_entity_index()

            # Only update cache if hash changed
            if index_hash != self._cached_index_hash:
                self._cached_entity_index = entity_index
                self._cached_index_hash = index_hash
                _LOGGER.debug("Entity index updated (hash: %s)", index_hash)

            messages.append(
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=f"[ENTITY INDEX]\nUse this index first to find entity IDs. Only use get_entities tool if entity not found here.\n{self._cached_entity_index}",
                )
            )
            cached_prefix_length += 1

        # 4. User memory injection (semi-static - changes when memories change)
        if self._memory_enabled and self._memory_manager:
            memory_text = self._memory_manager.get_injection_text(user_id)
            if memory_text:
                messages.append(
                    ChatMessage(role=MessageRole.SYSTEM, content=memory_text)
                )
                cached_prefix_length += 1
                _LOGGER.debug("Injected memory block for user '%s'", user_id)

        # 5. Conversation history from ChatLog (if available)
        # Placed BEFORE dynamic context to maximize cache prefix length
        # IMPORTANT: Also include tool calls and results for context continuity
        if chat_log is not None:
            try:
                max_history = int(self._get_config(CONF_MAX_HISTORY, DEFAULT_MAX_HISTORY))
                
                # Safely get content from chat_log
                content = getattr(chat_log, 'content', None)
                if content is None:
                    _LOGGER.debug("ChatLog has no content attribute")
                else:
                    try:
                        history_entries = list(content)
                    except (TypeError, AttributeError) as e:
                        _LOGGER.debug("Could not iterate chat_log.content: %s", e)
                        history_entries = []
                    
                    # Limit history to max_history entries (most recent)
                    if len(history_entries) > max_history:
                        history_entries = history_entries[-max_history:]
                    
                    # Debug: log history entry types
                    entry_types = [type(e).__name__ for e in history_entries]
                    _LOGGER.debug("ChatLog history types: %s", entry_types)
                    
                    for entry in history_entries:
                        entry_type = type(entry).__name__
                        
                        if entry_type == "UserContent":
                            if hasattr(entry, 'content') and entry.content:
                                messages.append(ChatMessage(role=MessageRole.USER, content=entry.content))
                        
                        elif entry_type == "AssistantContent":
                            # Process assistant content with potential tool calls
                            assistant_content = getattr(entry, 'content', '') or ''
                            tool_calls_list: list[ToolCall] = []
                            
                            # Extract tool calls from history for context
                            if hasattr(entry, 'tool_calls') and entry.tool_calls:
                                for tc in entry.tool_calls:
                                    tool_calls_list.append(ToolCall(
                                        id=getattr(tc, 'id', f"tc_{len(tool_calls_list)}"),
                                        name=getattr(tc, 'tool_name', 'unknown'),
                                        arguments=getattr(tc, 'tool_args', {}),
                                    ))
                            
                            if assistant_content or tool_calls_list:
                                messages.append(ChatMessage(
                                    role=MessageRole.ASSISTANT,
                                    content=assistant_content,
                                    tool_calls=tool_calls_list if tool_calls_list else None,
                                ))
                        
                        elif entry_type == "ToolResultContent":
                            # Include tool results so LLM knows what tools returned
                            tool_result = getattr(entry, 'tool_result', None)
                            tool_name = getattr(entry, 'tool_name', 'unknown')
                            tool_call_id = getattr(entry, 'id', 'unknown')
                            
                            # Format tool result as string
                            result_content = ""
                            if tool_result is not None:
                                if isinstance(tool_result, str):
                                    result_content = tool_result
                                elif isinstance(tool_result, dict):
                                    import json
                                    result_content = json.dumps(tool_result, ensure_ascii=False)
                                else:
                                    result_content = str(tool_result)
                            
                            if result_content:
                                messages.append(ChatMessage(
                                    role=MessageRole.TOOL,
                                    content=result_content,
                                    tool_call_id=tool_call_id,
                                    name=tool_name,
                                ))
                                
            except Exception as err:
                _LOGGER.warning("Failed to process chat history: %s", err)
                # Continue without history - don't fail the request

        # 6. Current context (dynamic - NOT cached) + user message
        # Combined into single user message to keep dynamic content at the end
        now = datetime.now()
        time_context = f"Current time: {now.strftime('%H:%M')}, Date: {now.strftime('%A, %B %d, %Y')}"
        
        relevant_states = self._entity_manager.get_relevant_entity_states(user_text)
        
        # Build context prefix for user message
        context_parts = [f"[Context: {time_context}]"]
        if relevant_states:
            context_parts.append(f"[States: {relevant_states}]")
        if calendar_context:
            _LOGGER.debug("Injecting calendar context (len=%d): %s", len(calendar_context), calendar_context.replace('\n', ' ')[:80])
            context_parts.append(calendar_context)
        
        # Add current assist satellite info if available
        # This allows the LLM to know which device initiated the request
        if satellite_id:
            context_parts.append(f"[Current Assist Satellite: {satellite_id}]")
        
        # Add recent entities for pronoun resolution (e.g., "it", "that", "the same one")
        if recent_entities_context:
            context_parts.append(recent_entities_context)
        
        # Add current user identity for personalization
        if self._memory_enabled and user_id != "default":
            display_name = user_id.capitalize()
            if self._memory_manager:
                stored_name = self._memory_manager.get_user_display_name(user_id)
                if stored_name:
                    display_name = stored_name
            context_parts.append(f"[Current User: {display_name}]")
        
        # Combine context with user message
        context_prefix = " ".join(context_parts)
        user_message_with_context = f"{context_prefix}\n\nUser: {user_text}"
        
        messages.append(ChatMessage(role=MessageRole.USER, content=user_message_with_context))

        return messages, cached_prefix_length

    async def _try_quick_action(self, text: str) -> str | None:
        """Try to handle simple commands without LLM.

        Returns response string if handled, None if LLM is needed.
        """
        import re
        
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

    def _build_result(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
        response_text: str,
        continue_conversation: bool = True,
    ) -> ConversationResult:
        """Build a ConversationResult from the chat log."""
        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(response_text)
        
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

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        if self._llm_client:
            await self._llm_client.close()
