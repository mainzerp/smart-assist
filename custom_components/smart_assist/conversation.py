"""Conversation entity for Smart Assist - Home Assistant Assist Pipeline integration."""

from __future__ import annotations

import logging
import traceback
from collections.abc import AsyncGenerator
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
    _LOGGER.error("Smart Assist: Failed to import conversation components: %s", e)
    _LOGGER.error("Traceback: %s", traceback.format_exc())
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
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import MATCH_ALL
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import intent
    from homeassistant.helpers.dispatcher import async_dispatcher_send
except ImportError as e:
    _LOGGER.error("Smart Assist: Failed to import HA core modules: %s", e)
    raise

# AddEntitiesCallback is the standard platform callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

try:
    from .const import (
        CONF_API_KEY,
        CONF_ASK_FOLLOWUP,
        CONF_CACHE_TTL_EXTENDED,
        CONF_CLEAN_RESPONSES,
        CONF_CONFIRM_CRITICAL,
        CONF_ENABLE_PROMPT_CACHING,
        CONF_ENABLE_QUICK_ACTIONS,
        CONF_EXPOSED_ONLY,
        CONF_LANGUAGE,
        CONF_MAX_HISTORY,
        CONF_MAX_TOKENS,
        CONF_MODEL,
        CONF_PROVIDER,
        CONF_TEMPERATURE,
        CONF_USER_SYSTEM_PROMPT,
        DEFAULT_ASK_FOLLOWUP,
        DEFAULT_CACHE_TTL_EXTENDED,
        DEFAULT_CLEAN_RESPONSES,
        DEFAULT_LANGUAGE,
        DEFAULT_MAX_HISTORY,
        DEFAULT_MAX_TOKENS,
        DEFAULT_PROVIDER,
        DEFAULT_TEMPERATURE,
        DEFAULT_USER_SYSTEM_PROMPT,
        DOMAIN,
    )
    from .context import EntityManager
    from .llm import ChatMessage, OpenRouterClient
    from .llm.models import MessageRole, ToolCall
    from .tools import create_tool_registry
    from .utils import clean_for_tts
except ImportError as e:
    _LOGGER.error("Smart Assist: Failed to import local modules: %s", e)
    _LOGGER.error("Traceback: %s", traceback.format_exc())
    raise

_LOGGER.info("Smart Assist: conversation.py module loaded successfully")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Smart Assist conversation entity from config entry."""
    _LOGGER.debug("Smart Assist: Setting up conversation entity")
    entity = SmartAssistConversationEntity(hass, entry)
    async_add_entities([entity])
    
    # Store entity reference for cache warming
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id]["agent"] = entity


class SmartAssistConversationEntity(ConversationEntity):
    """Smart Assist conversation entity for Home Assistant Assist Pipeline.
    
    This entity provides LLM-powered conversation with streaming support.
    """

    # Entity attributes
    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_supports_streaming = True
    _attr_supported_features = ConversationEntityFeature.CONTROL

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the conversation entity."""
        self.hass = hass
        self._entry = entry
        
        # Unique ID based on config entry
        self._attr_unique_id = f"{entry.entry_id}_conversation"
        
        # Device info for proper UI display
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Smart Assist",
            "manufacturer": "Smart Assist",
            "model": "Conversation Agent",
            "entry_type": "service",
        }

        # Helper to get config values (options override data)
        def get_config(key: str, default: Any = None) -> Any:
            """Get config value from options first, then data, then default."""
            if key in entry.options:
                return entry.options[key]
            return entry.data.get(key, default)

        # Initialize LLM client
        self._llm_client = OpenRouterClient(
            api_key=entry.data[CONF_API_KEY],  # API key only in data
            model=get_config(CONF_MODEL, "anthropic/claude-3-haiku"),
            provider=get_config(CONF_PROVIDER, DEFAULT_PROVIDER),
            temperature=get_config(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
            max_tokens=get_config(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
            enable_caching=get_config(CONF_ENABLE_PROMPT_CACHING, True),
            cache_ttl_extended=get_config(CONF_CACHE_TTL_EXTENDED, DEFAULT_CACHE_TTL_EXTENDED),
        )
        
        # Store LLM client reference for sensors to access metrics
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN].setdefault(entry.entry_id, {})
        hass.data[DOMAIN][entry.entry_id]["llm_client"] = self._llm_client

        # Entity manager for entity discovery
        self._entity_manager = EntityManager(
            hass=hass,
            exposed_only=get_config(CONF_EXPOSED_ONLY, True),
        )

        # Dynamic tool loading based on available domains
        self._tool_registry = create_tool_registry(hass, entry)

        # Cache for entity index
        self._cached_entity_index: str | None = None
        self._cached_index_hash: str | None = None
        
        # Cache for system prompt (built once, reused for all requests)
        self._cached_system_prompt: str | None = None

    def _get_config(self, key: str, default: Any = None) -> Any:
        """Get config value from options first, then data, then default.
        
        This is needed because OptionsFlow saves to entry.options,
        while initial config goes to entry.data.
        """
        if key in self._entry.options:
            return self._entry.options[key]
        return self._entry.data.get(key, default)

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return supported languages."""
        return MATCH_ALL  # Support all languages

    async def warm_cache(self) -> None:
        """Warm the prompt cache by sending a minimal request.
        
        This pre-populates the LLM provider's cache with the system prompt
        and entity index, reducing latency and cost for subsequent requests.
        """
        _LOGGER.debug("Warming prompt cache...")
        
        try:
            # Build messages (this populates entity index)
            messages = self._build_messages_for_llm("ping")
            tools = self._tool_registry.get_schemas()
            cached_prefix_length = 3  # system + user prompt + entity index
            
            async for _ in self._llm_client.chat_stream(
                messages=messages,
                tools=tools,
                cached_prefix_length=cached_prefix_length,
            ):
                pass  # Discard the response
            
            _LOGGER.info("Prompt cache warmed successfully")
            
        except Exception as err:
            _LOGGER.warning("Failed to warm prompt cache: %s", err)

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
            "Processing message: user_id=%s, text_length=%d, language=%s",
            user_input.conversation_id,
            len(user_input.text),
            user_input.language,
        )
        
        # Quick action bypass (if enabled)
        if self._get_config(CONF_ENABLE_QUICK_ACTIONS, True):
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
        messages = self._build_messages_for_llm(user_input.text, chat_log)
        tools = self._tool_registry.get_schemas()
        cached_prefix_length = 3 if self._get_config(CONF_ENABLE_PROMPT_CACHING, True) else 0
        
        _LOGGER.debug(
            "LLM request: messages=%d, tools=%d, cache_prefix=%d",
            len(messages),
            len(tools),
            cached_prefix_length,
        )

        try:
            # Use streaming with tool loop
            final_content = await self._call_llm_streaming_with_tools(
                messages=messages,
                tools=tools,
                cached_prefix_length=cached_prefix_length,
                chat_log=chat_log,
            )

            # Parse response for continuation marker
            cleaned_content, continue_conversation = self._parse_response_marker(final_content)
            
            # Override: If ask_followup is disabled, never continue
            ask_followup = self._get_config(CONF_ASK_FOLLOWUP, DEFAULT_ASK_FOLLOWUP)
            if not ask_followup:
                continue_conversation = False

            # Clean response for TTS if enabled
            final_response = cleaned_content
            if self._get_config(CONF_CLEAN_RESPONSES, DEFAULT_CLEAN_RESPONSES):
                language = self._get_config(CONF_LANGUAGE, DEFAULT_LANGUAGE)
                final_response = clean_for_tts(final_response, language)

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
        max_iterations: int = 5,
    ) -> str:
        """Call LLM with streaming and handle tool calls in-loop.
        
        Implements full streaming with tool execution - content is streamed
        to the pipeline while tools are executed between LLM calls.
        
        Returns the final response text after all tool calls are complete.
        """
        iteration = 0
        working_messages = messages.copy()
        
        while iteration < max_iterations:
            iteration += 1
            _LOGGER.debug("Streaming iteration %d", iteration)
            
            # Collect streaming response
            final_content = ""
            tool_calls: list[ToolCall] = []
            
            async for delta in self._llm_client.chat_stream_full(
                messages=working_messages,
                tools=tools,
                cached_prefix_length=cached_prefix_length if iteration == 1 else 0,
            ):
                if "content" in delta and delta["content"]:
                    content_chunk = delta["content"]
                    final_content += content_chunk
                    # Note: We collect content here but add to ChatLog once at the end
                    # Adding chunks individually causes issues with HA's ChatLog API
                
                if "tool_calls" in delta and delta["tool_calls"]:
                    tool_calls = delta["tool_calls"]
            
            # If no tool calls, we're done - add final content to ChatLog
            if not tool_calls:
                _LOGGER.debug("No tool calls, streaming complete")
                # Add the complete response to ChatLog once
                if final_content:
                    chat_log.async_add_assistant_content_without_tools(
                        conversation.AssistantContent(
                            agent_id=self.entity_id or "",
                            content=final_content,
                        )
                    )
                return final_content
            
            # Execute tool calls and add results to messages
            _LOGGER.debug("Executing %d tool calls in streaming loop", len(tool_calls))
            
            # Add assistant message with tool calls
            working_messages.append(
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=final_content,
                    tool_calls=tool_calls,
                )
            )
            
            # Execute each tool
            for tool_call in tool_calls:
                _LOGGER.debug(
                    "Executing tool: %s with args: %s",
                    tool_call.name,
                    tool_call.arguments,
                )
                
                result = await self._tool_registry.execute(
                    tool_call.name, tool_call.arguments
                )
                
                # Add tool result to messages
                working_messages.append(
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content=result.to_string(),
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                )
        
        # Max iterations reached, return last content
        _LOGGER.warning("Max tool iterations (%d) reached", max_iterations)
        return final_content

    async def _call_llm_fallback(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        cached_prefix_length: int,
        chat_log: ChatLog,
        max_iterations: int = 5,
    ) -> str:
        """Fallback non-streaming LLM call with tool handling.
        
        Used when streaming tool handling is not available or fails.
        """
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            response = await self._llm_client.chat(
                messages=messages,
                tools=tools,
                cached_prefix_length=cached_prefix_length,
            )

            if not response.has_tool_calls:
                # Add final response to chat log
                chat_log.async_add_assistant_content_without_tools(
                    conversation.AssistantContent(
                        agent_id=self.entity_id or "",
                        content=response.content,
                    )
                )
                return response.content or ""

            _LOGGER.debug("Handling tool calls (fallback iteration %d)", iteration)

            # Add assistant message with tool calls to our message list
            messages.append(
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                )
            )

            # Execute each tool call
            for tool_call in response.tool_calls:
                _LOGGER.debug(
                    "Executing tool: %s with args: %s",
                    tool_call.name,
                    tool_call.arguments,
                )

                result = await self._tool_registry.execute(
                    tool_call.name, tool_call.arguments
                )

                messages.append(
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content=result.to_string(),
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                )

        return response.content or ""

    async def _transform_stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        cached_prefix_length: int,
    ) -> AsyncGenerator[AssistantContentDeltaDict, None]:
        """Transform LLM stream into HA's expected delta format.
        
        This generator yields AssistantContentDeltaDict objects that HA's
        ChatLog can consume for real-time streaming.
        """
        from homeassistant.helpers import llm
        
        # Start with role indicator
        yield {"role": "assistant"}
        
        # Stream from LLM
        async for delta in self._llm_client.chat_stream_full(
            messages=messages,
            tools=tools,
            cached_prefix_length=cached_prefix_length,
        ):
            if "content" in delta and delta["content"]:
                yield {"content": delta["content"]}
            
            if "tool_calls" in delta and delta["tool_calls"]:
                # Convert to HA's llm.ToolInput format
                tool_inputs = []
                for tc in delta["tool_calls"]:
                    tool_inputs.append(
                        llm.ToolInput(
                            id=tc.id,
                            tool_name=tc.name,
                            tool_args=tc.arguments,
                        )
                    )
                yield {"tool_calls": tool_inputs}

    def _build_system_prompt(self) -> str:
        """Build or return cached system prompt based on configuration.
        
        System prompt is always in English (best LLM performance).
        Only the response language instruction is configurable.
        
        The prompt is cached after first build since config rarely changes.
        If config is updated, the entity is reloaded anyway.
        """
        # Return cached prompt if available
        if self._cached_system_prompt is not None:
            return self._cached_system_prompt
        
        language = self._get_config(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        
        # Auto-detect: use Home Assistant's configured language
        if language == "auto":
            ha_language = self.hass.config.language
            # Map HA language codes to our supported languages
            if ha_language.startswith("de"):
                language = "de"
            else:
                language = "en"  # Default to English for unsupported languages
        
        confirm_critical = self._get_config(CONF_CONFIRM_CRITICAL, True)
        exposed_only = self._get_config(CONF_EXPOSED_ONLY, True)
        caching_enabled = self._get_config(CONF_ENABLE_PROMPT_CACHING, True)
        ask_followup = self._get_config(CONF_ASK_FOLLOWUP, DEFAULT_ASK_FOLLOWUP)
        
        parts = []
        
        # Base prompt with language instruction
        if language == "de":
            parts.append("You are a Home Assistant smart home controller. Always respond in German (Deutsch). Be concise and helpful.")
        else:
            parts.append("You are a Home Assistant smart home controller. Always respond in English. Be concise and helpful.")
        
        # Response rules with conversation continuation marker
        if ask_followup:
            parts.append("""
## Response Rules
- Confirm actions taken briefly
- Offer follow-up assistance intelligently:
  - YES: If the task is ambiguous, could have follow-ups, or user might need more help
  - NO: If the action is complete and self-contained (e.g., "light is on")
- Vary the phrasing naturally when offering help
- If uncertain about entity, ask for clarification
- Never assume entity states - use tools to check

## Conversation Continuation Signal
Add [AWAIT_RESPONSE] at the END of your message when you are asking a question or expecting a user response.
Do NOT add this marker for simple confirmations where no response is expected.
Examples:
- "The living room light is now on." (no marker - complete action)
- "I found 3 lights. Which one should I control? [AWAIT_RESPONSE]" (marker - expecting choice)
- "The temperature is 22C. Would you like me to adjust it? [AWAIT_RESPONSE]" (marker - expecting yes/no)""")
        else:
            parts.append("""
## Response Rules
- Confirm actions taken briefly and concisely
- Do NOT ask follow-up questions or offer further assistance
- Keep responses short and action-focused
- If uncertain about entity, ask for clarification
- Never assume entity states - use tools to check""")
        
        # Entity lookup strategy
        if caching_enabled:
            parts.append("""
## Entity Lookup Strategy
1. FIRST: Check the ENTITY INDEX (if provided) to find entity_ids
2. ONLY if entity not found in index: Use get_entities tool with domain filter
3. Use get_entity_state to check current state before taking action""")
        else:
            parts.append("""
## Entity Lookup
- Use get_entities tool with domain filter to find entities
- Use get_entity_state to check current state before taking action""")
        
        # Control instructions
        parts.append("""
## Entity Control
- Use the 'control' tool for all entity types (lights, climate, covers, media, scripts)
- Domain is auto-detected from entity_id (e.g., light.living_room -> light domain)
- Use action appropriate to domain (turn_on/off for all, brightness for lights, etc.)""")
        
        # Critical actions confirmation
        if confirm_critical:
            parts.append("""
## Critical Actions
IMPORTANT: Before locking doors, arming alarms, or disabling security devices, ALWAYS ask for user confirmation first!""")
        
        # Exposed only notice
        if exposed_only:
            parts.append("""
## Notice
Only exposed entities are available. Entities not listed in the index cannot be controlled.""")
        
        # Error handling
        parts.append("""
## Error Handling
- If an action fails, explain why and suggest alternatives
- If entity not found, suggest similar entities from the index""")
        
        # Cache the built prompt for subsequent calls
        self._cached_system_prompt = "\n".join(parts)
        _LOGGER.debug("System prompt cached (length: %d chars)", len(self._cached_system_prompt))
        
        return self._cached_system_prompt

    def _parse_response_marker(self, response: str) -> tuple[str, bool]:
        """Parse response for [AWAIT_RESPONSE] marker and determine continuation.
        
        Args:
            response: The raw LLM response text
            
        Returns:
            Tuple of (cleaned_response, continue_conversation)
        """
        MARKER = "[AWAIT_RESPONSE]"
        
        # Check if marker is present
        if MARKER in response:
            # Remove marker and clean up
            cleaned = response.replace(MARKER, "").strip()
            return cleaned, True
        
        # No marker - don't continue conversation
        return response, False

    def _build_messages_for_llm(self, user_text: str, chat_log: ChatLog | None = None) -> list[ChatMessage]:
        """Build the message list for LLM request.
        
        Args:
            user_text: The current user message
            chat_log: Optional ChatLog containing conversation history
        """
        messages: list[ChatMessage] = []

        # 1. Technical system prompt (cached)
        system_prompt = self._build_system_prompt()
        messages.append(
            ChatMessage(role=MessageRole.SYSTEM, content=system_prompt)
        )

        # 2. User system prompt (cached)
        user_prompt = self._get_config(
            CONF_USER_SYSTEM_PROMPT, DEFAULT_USER_SYSTEM_PROMPT
        )
        if user_prompt:
            messages.append(
                ChatMessage(role=MessageRole.SYSTEM, content=user_prompt)
            )

        # 3. Entity index (only if caching is enabled)
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

        # 4. Current context (dynamic) - includes time and relevant states
        from datetime import datetime
        now = datetime.now()
        time_context = f"Current time: {now.strftime('%H:%M')}, Date: {now.strftime('%A, %B %d, %Y')}"
        
        relevant_states = self._entity_manager.get_relevant_entity_states(user_text)
        messages.append(
            ChatMessage(
                role=MessageRole.SYSTEM,
                content=f"[CURRENT CONTEXT]\n{time_context}\n\n{relevant_states}",
            )
        )

        # 5. Conversation history from ChatLog (if available)
        if chat_log is not None:
            try:
                max_history = self._get_config(CONF_MAX_HISTORY, DEFAULT_MAX_HISTORY)
                
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
                    
                    for entry in history_entries:
                        if hasattr(entry, 'content') and entry.content:
                            # Check type by class name (safer than isinstance with potentially None types)
                            entry_type = type(entry).__name__
                            if entry_type == "UserContent":
                                messages.append(ChatMessage(role=MessageRole.USER, content=entry.content))
                            elif entry_type == "AssistantContent":
                                messages.append(ChatMessage(role=MessageRole.ASSISTANT, content=entry.content))
            except Exception as err:
                _LOGGER.warning("Failed to process chat history: %s", err)
                # Continue without history - don't fail the request

        # 6. Current user message
        messages.append(ChatMessage(role=MessageRole.USER, content=user_text))

        return messages

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
                result = await self._tool_registry.execute(
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
        
        # Signal sensors to update their state
        async_dispatcher_send(
            self.hass,
            f"smart_assist_metrics_updated_{self._entry.entry_id}",
        )
        
        return ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id,
            continue_conversation=continue_conversation,
        )
