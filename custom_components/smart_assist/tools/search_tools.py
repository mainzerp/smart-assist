"""Web search tools for Smart Assist."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """Tool for web search using DuckDuckGo."""

    name = "web_search"
    description = "Search the web via DuckDuckGo for non-smart-home questions."
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="The search query",
            required=True,
        ),
        ToolParameter(
            name="max_results",
            type="number",
            description="Max results (1-5)",
            required=False,
            minimum=1,
            maximum=5,
        ),
    ]

    async def execute(
        self,
        query: str,
        max_results: int = 3,
    ) -> ToolResult:
        """Execute the web_search tool."""
        try:
            from ddgs import DDGS
        except ImportError:
            return ToolResult(
                success=False,
                message="Web search is not available. DDGS library not installed.",
            )

        max_results = min(max(1, max_results), 5)

        try:
            # Run in executor to avoid blocking
            def search() -> list[dict[str, Any]]:
                # New ddgs API: DDGS().text() returns list directly
                return DDGS().text(query, max_results=max_results)

            results = await self._hass.async_add_executor_job(search)

            if not results:
                return ToolResult(
                    success=True,
                    message=f"No results found for: {query}",
                )

            # Format results
            formatted = []
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "")
                href = r.get("href", "")
                formatted.append(f"- {title}\n  {body}\n  URL: {href}")

            return ToolResult(
                success=True,
                message=f"Search results for '{query}':\n\n" + "\n\n".join(formatted),
                data={"results": results},
            )

        except Exception as err:
            _LOGGER.error("Web search error: %s", err)
            return ToolResult(
                success=False,
                message=f"Search failed: {err}",
            )


class GetWeatherTool(BaseTool):
    """Tool to get weather information (faster than web search)."""

    name = "get_weather"
    description = "Get current weather from HA weather entity."
    parameters = [
        ToolParameter(
            name="entity_id",
            type="string",
            description="Weather entity ID (default: first available)",
            required=False,
        ),
    ]

    async def execute(self, entity_id: str | None = None) -> ToolResult:
        """Execute the get_weather tool."""
        # Find weather entity
        if entity_id is None:
            weather_entities = [
                state.entity_id
                for state in self._hass.states.async_all()
                if state.entity_id.startswith("weather.")
            ]
            if not weather_entities:
                return ToolResult(
                    success=False,
                    message="No weather entity found.",
                )
            entity_id = weather_entities[0]

        state = self._hass.states.get(entity_id)
        if not state:
            return ToolResult(
                success=False,
                message=f"Weather entity {entity_id} not found.",
            )

        attrs = state.attributes
        weather_info = [
            f"Weather: {state.state}",
            f"Temperature: {attrs.get('temperature')}°{attrs.get('temperature_unit', 'C')}",
        ]

        if humidity := attrs.get("humidity"):
            weather_info.append(f"Humidity: {humidity}%")

        if wind_speed := attrs.get("wind_speed"):
            weather_info.append(f"Wind: {wind_speed} {attrs.get('wind_speed_unit', 'km/h')}")

        if pressure := attrs.get("pressure"):
            weather_info.append(f"Pressure: {pressure} {attrs.get('pressure_unit', 'hPa')}")

        return ToolResult(
            success=True,
            message="\n".join(weather_info),
            data={"state": state.state, "attributes": dict(attrs)},
        )
