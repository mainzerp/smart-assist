"""Groq API client for Smart Assist - Direct Groq integration."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator

import aiohttp

from .base_client import BaseLLMClient, LLMMetrics, LLMClientError
from .models import ChatMessage, ChatResponse, LLMError, MessageRole, ToolCall
from ..utils import sanitize_user_facing_error
from ..const import (
    GROQ_API_URL,
)

_LOGGER = logging.getLogger(__name__)


class GroqError(LLMError):
    """Exception for Groq API errors."""
    pass


class GroqClient(BaseLLMClient):
    """Client for Groq API - Direct integration."""

    # Session max age in seconds (renew to prevent stale HTTP connections)
    SESSION_MAX_AGE_SECONDS = 240  # 4 minutes

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 500,
    ) -> None:
        """Initialize the Groq client.
        
        Args:
            api_key: Groq API key
            model: Model ID (e.g., 'openai/gpt-oss-120b', 'llama-3.3-70b-versatile')
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum completion tokens
        """
        super().__init__(api_key=api_key, model=model, temperature=temperature, max_tokens=int(max_tokens))
    
    def _get_api_url(self) -> str:
        """Return the Groq API endpoint URL."""
        return GROQ_API_URL
    
    def _get_session_headers(self) -> dict[str, str]:
        """Return headers for the Groq API session."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
    
    def _get_session_timeout(self) -> aiohttp.ClientTimeout:
        """Return Groq-specific timeout configuration."""
        return aiohttp.ClientTimeout(
            total=60,
            connect=10,
            sock_connect=10,
            sock_read=30,
        )

    def _build_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """Build messages list for API request.
        
        Groq uses automatic caching - no cache_control needed.
        Just send plain messages in OpenAI format.
        """
        return [msg.to_dict() for msg in messages]

    async def _stream_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Shared streaming implementation that yields full delta events.

        Handles payload building, SSE parsing, usage tracking, tool call
        accumulation, and error handling.

        Yields:
            dict with keys:
            - {"content": str} for content chunks
            - {"tool_calls": list[ToolCall]} when tool calls are complete
            - {"finish_reason": str} when stream is done
        """
        session = await self._get_session()

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._build_messages(messages),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        _LOGGER.debug("Sending streaming request to Groq: %s", self._model)

        self._metrics.total_requests += 1
        start_time = time.monotonic()
        usage_processed = False  # Flag to prevent double-counting usage
        pending_tool_calls: dict[int, dict[str, Any]] = {}

        try:
            async with await self._execute_with_retry(session, payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    _LOGGER.error("Groq API error: %s", error_text)
                    self._metrics.failed_requests += 1
                    raise GroqError(
                        sanitize_user_facing_error(
                            f"API error: {response.status} - {error_text}",
                            fallback=f"API error: {response.status}",
                        )
                    )

                async for line in response.content:
                    line = line.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str == "[DONE]":
                        elapsed_ms = (time.monotonic() - start_time) * 1000
                        self._metrics.successful_requests += 1
                        self._metrics.total_response_time_ms += elapsed_ms

                        # Emit completed tool calls if any
                        if pending_tool_calls:
                            yield {"tool_calls": self._build_tool_calls(pending_tool_calls)}

                        yield {"finish_reason": "stop"}
                        break

                    try:
                        data = json.loads(data_str)

                        # Extract usage info (only once per request)
                        if not usage_processed and (usage := data.get("usage")):
                            usage_processed = True
                            _LOGGER.debug("Got usage in stream: %s", usage)
                            self._metrics.total_prompt_tokens += usage.get("prompt_tokens", 0)
                            self._metrics.total_completion_tokens += usage.get("completion_tokens", 0)
                            # Per-request tracking
                            self._metrics._last_prompt_tokens = usage.get("prompt_tokens", 0)
                            self._metrics._last_completion_tokens = usage.get("completion_tokens", 0)

                            # Check for cached tokens
                            prompt_details = usage.get("prompt_tokens_details", {})
                            cached = prompt_details.get("cached_tokens", 0)
                            self._metrics._last_cached_tokens = cached or 0
                            prompt_tokens = usage.get("prompt_tokens", 0)
                            _LOGGER.debug(
                                "Groq cache stats: cached_tokens=%d, prompt_tokens=%d, cache_hit=%s",
                                cached, prompt_tokens, cached > 0
                            )
                            if cached > 0:
                                self._metrics.cache_hits += 1
                                self._metrics.cached_tokens += cached
                            else:
                                self._metrics.cache_misses += 1

                        if choices := data.get("choices"):
                            choice = choices[0]
                            delta = choice.get("delta", {})
                            finish_reason = choice.get("finish_reason")

                            # Content chunk
                            if content := delta.get("content"):
                                yield {"content": content}

                            # Tool call chunks
                            if tool_call_deltas := delta.get("tool_calls"):
                                for tc in tool_call_deltas:
                                    idx = tc.get("index", 0)
                                    if idx not in pending_tool_calls:
                                        pending_tool_calls[idx] = {
                                            "id": tc.get("id", ""),
                                            "name": "",
                                            "arguments": "",
                                        }
                                    if tc.get("id"):
                                        pending_tool_calls[idx]["id"] = tc["id"]
                                    if func := tc.get("function"):
                                        if name := func.get("name"):
                                            pending_tool_calls[idx]["name"] = name
                                        if args := func.get("arguments"):
                                            pending_tool_calls[idx]["arguments"] += args

                            # Finish reason
                            if finish_reason and finish_reason != "null":
                                if finish_reason == "tool_calls" and pending_tool_calls:
                                    yield {"tool_calls": self._build_tool_calls(pending_tool_calls)}
                                    pending_tool_calls.clear()
                                yield {"finish_reason": finish_reason}

                    except json.JSONDecodeError:
                        continue

        except Exception as err:
            if not isinstance(err, LLMClientError):
                self._metrics.failed_requests += 1
            _LOGGER.error("Groq streaming error: %s", err)
            raise GroqError(
                sanitize_user_facing_error(err, fallback="Streaming error")
            ) from err

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,  # Unused for Groq but kept for API compatibility
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        use_native_structured_output: bool = False,
    ) -> AsyncGenerator[str, None]:
        """Send a streaming chat request to Groq API.

        Delegates to _stream_request() and filters to content-only chunks.
        """
        async for chunk in self._stream_request(messages, tools):
            if "content" in chunk:
                yield chunk["content"]

    async def chat_stream_full(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Send a streaming chat request and yield full delta events.

        Yields content chunks, tool calls, and finish reasons.

        Yields:
            dict with keys:
            - {"content": str} for content chunks
            - {"tool_calls": list} when tool calls are complete
            - {"finish_reason": str} when stream is done
        """
        async for chunk in self._stream_request(messages, tools):
            yield chunk

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        use_native_structured_output: bool = False,
    ) -> ChatResponse:
        """Send a non-streaming chat request to Groq API."""
        session = await self._get_session()

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._build_messages(messages),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        _LOGGER.debug("Sending request to Groq: %s", self._model)
        
        self._metrics.total_requests += 1
        start_time = time.monotonic()

        try:
            async with await self._execute_with_retry(session, payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self._metrics.failed_requests += 1
                    raise GroqError(
                        sanitize_user_facing_error(
                            f"API error: {response.status} - {error_text}",
                            fallback=f"API error: {response.status}",
                        )
                    )

                data = await response.json()
                
                elapsed_ms = (time.monotonic() - start_time) * 1000
                self._metrics.successful_requests += 1
                self._metrics.total_response_time_ms += elapsed_ms
                
                # Extract usage
                if usage := data.get("usage"):
                    self._metrics.total_prompt_tokens += usage.get("prompt_tokens", 0)
                    self._metrics.total_completion_tokens += usage.get("completion_tokens", 0)
                    # Per-request tracking
                    self._metrics._last_prompt_tokens = usage.get("prompt_tokens", 0)
                    self._metrics._last_completion_tokens = usage.get("completion_tokens", 0)
                    
                    prompt_details = usage.get("prompt_tokens_details", {})
                    cached = prompt_details.get("cached_tokens", 0)
                    self._metrics._last_cached_tokens = cached or 0
                    prompt_tokens = usage.get("prompt_tokens", 0)
                    _LOGGER.debug(
                        "Groq cache stats: cached_tokens=%d, prompt_tokens=%d, cache_hit=%s",
                        cached, prompt_tokens, cached > 0
                    )
                    if cached > 0:
                        self._metrics.cache_hits += 1
                        self._metrics.cached_tokens += cached
                    else:
                        self._metrics.cache_misses += 1
                
                # Parse response
                choices = data.get("choices", [])
                if not choices:
                    return ChatResponse(content="", finish_reason="stop")
                
                message = choices[0].get("message", {})
                content = message.get("content", "") or ""
                finish_reason = choices[0].get("finish_reason", "stop")
                
                # Parse tool calls
                tool_calls = []
                if raw_tools := message.get("tool_calls"):
                    for tc in raw_tools:
                        func = tc.get("function", {})
                        try:
                            args = json.loads(func.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append(ToolCall(
                            id=tc.get("id", ""),
                            name=func.get("name", ""),
                            arguments=args,
                        ))
                
                return ChatResponse(
                    content=content,
                    tool_calls=tool_calls,
                    finish_reason=finish_reason,
                    usage=data.get("usage", {}),
                )

        except Exception as err:
            if not isinstance(err, LLMClientError):
                self._metrics.failed_requests += 1
            _LOGGER.error("Groq chat error: %s", err)
            raise GroqError(
                sanitize_user_facing_error(err, fallback="Provider request failed")
            ) from err
