"""Base tool interface for Smart Assist."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

from ..utils import sanitize_user_facing_error

_LOGGER = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""

    name: str
    type: str  # "string", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: Any = None
    items: dict[str, Any] | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    min_length: int | None = None
    max_length: int | None = None
    min_items: int | None = None
    max_items: int | None = None


@dataclass
class ToolResult:
    """Result from tool execution."""

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_string(self) -> str:
        """Convert result to string for LLM."""
        if self.success:
            return self.message
        return f"Error: {self.message}"


class BaseTool(ABC):
    """Base class for all tools."""

    name: str
    description: str
    parameters: list[ToolParameter]

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the tool."""
        self._hass = hass
        self._device_id: str | None = None
        self._conversation_agent_id: str | None = None
        self._satellite_id: str | None = None

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given parameters."""
        pass

    def get_schema(self) -> dict[str, Any]:
        """Get OpenAI-compatible tool schema."""
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in self.parameters:
            prop = self._build_parameter_schema(param)
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        }

    def _build_parameter_schema(self, param: ToolParameter) -> dict[str, Any]:
        """Build JSON schema for a single tool parameter."""
        value_schema: dict[str, Any] = {
            "type": param.type,
        }
        if param.enum:
            value_schema["enum"] = param.enum
        if param.items:
            value_schema["items"] = param.items
        if param.default is not None:
            value_schema["default"] = param.default
        if param.minimum is not None:
            value_schema["minimum"] = param.minimum
        if param.maximum is not None:
            value_schema["maximum"] = param.maximum
        if param.min_length is not None:
            value_schema["minLength"] = param.min_length
        if param.max_length is not None:
            value_schema["maxLength"] = param.max_length
        if param.min_items is not None:
            value_schema["minItems"] = param.min_items
        if param.max_items is not None:
            value_schema["maxItems"] = param.max_items

        if param.required:
            schema = dict(value_schema)
            schema["description"] = param.description
            return schema

        return {
            "description": param.description,
            "anyOf": [
                value_schema,
                {"type": "null"},
            ],
        }


class ToolRegistry:
    """Registry for all available tools."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the tool registry."""
        self._hass = hass
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        _LOGGER.debug("Registered tool: %s", tool.name)

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_all(self) -> list[BaseTool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all registered tools."""
        return [tool.get_schema() for tool in self._tools.values()]

    def set_device_id(self, device_id: str | None) -> None:
        """Set device_id on all registered tools for conversation context."""
        for tool in self._tools.values():
            tool._device_id = device_id

    def set_conversation_agent_id(self, agent_id: str | None) -> None:
        """Set conversation_agent_id on all tools so timer commands route back to this agent."""
        for tool in self._tools.values():
            tool._conversation_agent_id = agent_id

    def set_satellite_id(self, satellite_id: str | None) -> None:
        """Set satellite_id on all registered tools."""
        for tool in self._tools.values():
            tool._satellite_id = satellite_id

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        max_retries: int | None = None,
        latency_budget_ms: int | None = None,
    ) -> ToolResult:
        """Execute a tool by name."""
        tool = self._tools.get(name)
        if not tool:
            _LOGGER.warning("Tool not found: %s (available: %s)", name, list(self._tools.keys()))
            return ToolResult(
                success=False,
                message=f"Unknown tool: {name}",
                data={
                    "execution_time_ms": 0.0,
                    "timed_out": False,
                    "retries_used": 0,
                    "attempts": 0,
                    "latency_budget_ms": latency_budget_ms,
                },
            )

        retries = max(0, int(max_retries or 0))
        attempts_allowed = retries + 1
        last_error: Exception | None = None
        timed_out = False
        start = time.monotonic()
        normalized_arguments = self._normalize_arguments(arguments)

        for attempt in range(1, attempts_allowed + 1):
            try:
                _LOGGER.debug(
                    "Executing tool: %s attempt %d/%d with args: %s",
                    name,
                    attempt,
                    attempts_allowed,
                    normalized_arguments,
                )
                if latency_budget_ms and latency_budget_ms > 0:
                    async with asyncio.timeout(latency_budget_ms / 1000):
                        result = await tool.execute(**normalized_arguments)
                else:
                    result = await tool.execute(**normalized_arguments)

                elapsed_ms = (time.monotonic() - start) * 1000
                result.data["execution_time_ms"] = round(elapsed_ms, 2)
                result.data["timed_out"] = False
                result.data["retries_used"] = attempt - 1
                result.data["attempts"] = attempt
                result.data["latency_budget_ms"] = latency_budget_ms

                _LOGGER.debug(
                    "Tool %s result: success=%s, attempts=%d, time=%.1fms, message=%s",
                    name,
                    result.success,
                    attempt,
                    elapsed_ms,
                    result.message[:100] if result.message else "None",
                )
                if result.success or attempt >= attempts_allowed:
                    return result
            except asyncio.TimeoutError as err:
                last_error = err
                timed_out = True
                _LOGGER.warning(
                    "Tool %s timed out on attempt %d/%d (budget=%sms)",
                    name,
                    attempt,
                    attempts_allowed,
                    latency_budget_ms,
                )
            except Exception as err:
                last_error = err
                _LOGGER.error(
                    "Tool execution error for %s on attempt %d/%d: %s",
                    name,
                    attempt,
                    attempts_allowed,
                    err,
                    exc_info=True,
                )

        elapsed_ms = (time.monotonic() - start) * 1000
        if timed_out:
            safe_message = "Tool request timed out."
        else:
            safe_message = sanitize_user_facing_error(
                last_error or "Tool execution failed",
                fallback="Tool request failed.",
            )

        return ToolResult(
            success=False,
            message=safe_message,
            data={
                "execution_time_ms": round(elapsed_ms, 2),
                "timed_out": timed_out,
                "retries_used": retries,
                "attempts": attempts_allowed,
                "latency_budget_ms": latency_budget_ms,
            },
        )

    def _normalize_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Normalize tool argument keys from LLM output into safe kwargs names."""
        normalized: dict[str, Any] = {}
        for key, value in (arguments or {}).items():
            raw_key = str(key)
            normalized_key = "".join(raw_key.split())
            if normalized_key != raw_key:
                _LOGGER.debug(
                    "Normalized tool arg key: %s -> %s",
                    raw_key,
                    normalized_key,
                )
            normalized[normalized_key] = value
        return normalized
