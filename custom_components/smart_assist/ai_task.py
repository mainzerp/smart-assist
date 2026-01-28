"""AI Task entity for Smart Assist - enables LLM usage in automations."""

from __future__ import annotations

import asyncio
import logging
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
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_API_KEY,
    CONF_EXPOSED_ONLY,
    CONF_GROQ_API_KEY,
    CONF_LANGUAGE,
    CONF_LLM_PROVIDER,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_PROVIDER,
    CONF_TASK_ENABLE_PROMPT_CACHING,
    CONF_TASK_SYSTEM_PROMPT,
    CONF_TEMPERATURE,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TASK_ENABLE_PROMPT_CACHING,
    DEFAULT_TASK_SYSTEM_PROMPT,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    LLM_PROVIDER_GROQ,
    LOCALE_TO_LANGUAGE,
)
from .context.entity_manager import EntityManager
from .llm import OpenRouterClient, GroqClient, create_llm_client
from .llm.models import ChatMessage, MessageRole
from .tools import create_tool_registry
from .utils import get_config_value

_LOGGER = logging.getLogger(__name__)


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
        
        # For OpenRouterClient, set additional caching options
        if hasattr(self._llm_client, '_enable_caching'):
            self._llm_client._enable_caching = get_config(CONF_TASK_ENABLE_PROMPT_CACHING, DEFAULT_TASK_ENABLE_PROMPT_CACHING)
        
        # Initialize entity manager for context
        self._entity_manager = EntityManager(
            hass,
            exposed_only=get_config(CONF_EXPOSED_ONLY, True),
        )
        
        # Initialize tool registry
        self._tool_registry = create_tool_registry(
            hass=hass,
            entry=config_entry,
        )

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
            task.task_name,
            task.instructions[:100] if task.instructions else "None",
        )
        
        # Build messages for LLM
        messages = self._build_messages(task.instructions)
        
        # Get tool schemas
        tools = self._tool_registry.get_schemas()
        
        # Call LLM with tool support
        try:
            response_content = await self._process_with_tools(messages, tools)
        except Exception as e:
            _LOGGER.error("AI Task LLM call failed: %s", e)
            response_content = f"Error processing task: {e}"
        
        # Return result
        if task.structure:
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
        
        # Get entity index for context
        entity_index = self._entity_manager.get_entity_index()
        
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
        # Cache system + user message on first iteration (disabled by default for tasks)
        cached_prefix_length = 2 if self._get_config(CONF_TASK_ENABLE_PROMPT_CACHING, DEFAULT_TASK_ENABLE_PROMPT_CACHING) else 0
        
        while iteration < max_iterations:
            iteration += 1
            
            response = await self._llm_client.chat(
                messages=messages,
                tools=tools,
                # Only apply caching on first iteration
                cached_prefix_length=cached_prefix_length if iteration == 1 else 0,
            )
            
            if not response.has_tool_calls:
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
            
            # Execute tools in parallel
            async def execute_tool(tool_call):
                _LOGGER.debug("Executing tool: %s", tool_call.name)
                result = await self._tool_registry.execute(
                    tool_call.name, tool_call.arguments
                )
                return (tool_call, result)
            
            tool_results = await asyncio.gather(
                *[execute_tool(tc) for tc in response.tool_calls],
                return_exceptions=True
            )
            
            # Add tool results to messages
            for item in tool_results:
                if isinstance(item, Exception):
                    _LOGGER.error("Tool execution failed: %s", item)
                    continue
                tool_call, result = item
                messages.append(
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content=result.to_string(),
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                )
        
        _LOGGER.warning("AI Task max iterations reached")
        return response.content or ""

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        if self._llm_client:
            await self._llm_client.close()
