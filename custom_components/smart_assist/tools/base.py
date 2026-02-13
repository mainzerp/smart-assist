"""Base tool interface for Smart Assist."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

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
    items: dict[str, str] | None = None  # For array types: {"type": "string"}


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

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name."""
        tool = self._tools.get(name)
        if not tool:
            _LOGGER.warning("Tool not found: %s (available: %s)", name, list(self._tools.keys()))
            return ToolResult(
                success=False,
                message=f"Unknown tool: {name}",
                data={"execution_time_ms": 0.0},
            )

        try:
            import time as _time
            start = _time.monotonic()
            _LOGGER.debug("Executing tool: %s with args: %s", name, arguments)
            result = await tool.execute(**arguments)
            elapsed_ms = (_time.monotonic() - start) * 1000
            result.data["execution_time_ms"] = round(elapsed_ms, 2)
            _LOGGER.debug(
                "Tool %s result: success=%s, time=%.1fms, message=%s",
                name,
                result.success,
                elapsed_ms,
                result.message[:100] if result.message else "None",
            )
            return result
        except Exception as err:
            _LOGGER.error("Tool execution error for %s: %s", name, err, exc_info=True)
            return ToolResult(
                success=False,
                message=f"Tool error: {err}",
                data={"execution_time_ms": 0.0},
            )
