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
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_API_KEY,
    CONF_EXPOSED_ONLY,
    CONF_LANGUAGE,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_PROVIDER,
    CONF_TASK_ENABLE_PROMPT_CACHING,
    CONF_TASK_SYSTEM_PROMPT,
    CONF_TEMPERATURE,
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TASK_ENABLE_PROMPT_CACHING,
    DEFAULT_TASK_SYSTEM_PROMPT,
    DEFAULT_TEMPERATURE,
    DOMAIN,
)
from .context.entity_manager import EntityManager
from .llm import OpenRouterClient
from .llm.models import ChatMessage, MessageRole
from .tools import create_tool_registry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AI Task entity from config entry."""
    async_add_entities([SmartAssistAITask(hass, config_entry)])


class SmartAssistAITask(AITaskEntity):
    """AI Task entity for Smart Assist."""

    _attr_has_entity_name = True
    _attr_name = "Smart Assist Task"
    _attr_supported_features = AITaskEntityFeature.GENERATE_DATA

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the AI Task entity."""
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_ai_task"
        
        # Helper to get config values
        def get_config(key: str, default: Any = None) -> Any:
            if key in config_entry.options:
                return config_entry.options[key]
            return config_entry.data.get(key, default)
        
        self._get_config = get_config
        
        # Initialize LLM client
        self._llm_client = OpenRouterClient(
            api_key=get_config(CONF_API_KEY),
            model=get_config(CONF_MODEL, DEFAULT_MODEL),
            provider=get_config(CONF_PROVIDER, DEFAULT_PROVIDER),
            temperature=get_config(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
            max_tokens=get_config(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
            enable_caching=get_config(CONF_TASK_ENABLE_PROMPT_CACHING, DEFAULT_TASK_ENABLE_PROMPT_CACHING),
        )
        
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
        
        # Get language preference
        language = self._get_config(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        language_instruction = ""
        if language != "auto":
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
