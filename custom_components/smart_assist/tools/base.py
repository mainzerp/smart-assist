"""Base tool interface for Smart Assist."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class ToolParameterType(str, Enum):
    """Valid types for tool parameters."""
    
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""

    name: str
    type: str  # "string", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: Any = None


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

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given parameters."""
        pass

    def get_schema(self) -> dict[str, Any]:
        """Get OpenAI-compatible tool schema."""
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
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

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name."""
        tool = self._tools.get(name)
        if not tool:
            _LOGGER.warning("Tool not found: %s (available: %s)", name, list(self._tools.keys()))
            return ToolResult(
                success=False,
                message=f"Unknown tool: {name}",
            )

        try:
            _LOGGER.debug("Executing tool: %s with args: %s", name, arguments)
            result = await tool.execute(**arguments)
            _LOGGER.debug(
                "Tool %s result: success=%s, message=%s",
                name,
                result.success,
                result.message[:100] if result.message else "None",
            )
            return result
        except Exception as err:
            _LOGGER.error("Tool execution error for %s: %s", name, err, exc_info=True)
            return ToolResult(
                success=False,
                message=f"Tool error: {err}",
            )
