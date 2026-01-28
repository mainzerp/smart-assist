"""Groq API client for Smart Assist - Direct Groq integration."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import aiohttp

from .models import ChatMessage, ChatResponse, LLMError, MessageRole, ToolCall
from ..const import (
    GROQ_API_URL,
    LLM_MAX_RETRIES,
    LLM_RETRY_BASE_DELAY,
    LLM_RETRY_MAX_DELAY,
    LLM_RETRIABLE_STATUS_CODES,
    LLM_STREAM_CHUNK_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class GroqError(LLMError):
    """Exception for Groq API errors."""
    pass


@dataclass
class GroqMetrics:
    """Metrics for Groq API calls."""
    
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_retries: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_response_time_ms: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    cached_tokens: int = 0
    
    @property
    def average_response_time_ms(self) -> float:
        """Calculate average response time."""
        if self.successful_requests == 0:
            return 0.0
        return self.total_response_time_ms / self.successful_requests
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.total_requests == 0:
            return 100.0
        return (self.successful_requests / self.total_requests) * 100
    
    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate percentage."""
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return (self.cache_hits / total) * 100
    
    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "total_retries": self.total_retries,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "average_response_time_ms": round(self.average_response_time_ms, 2),
            "success_rate": round(self.success_rate, 2),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cached_tokens": self.cached_tokens,
            "cache_hit_rate": round(self.cache_hit_rate, 2),
        }


class GroqClient:
    """Client for Groq API - Direct integration."""

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
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._max_tokens = int(max_tokens)  # Groq requires integer
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()
        self._session_created_at: float | None = None
        self._metrics = GroqMetrics()
    
    # Session max age in seconds (renew to prevent stale HTTP connections)
    SESSION_MAX_AGE_SECONDS = 240  # 4 minutes
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session (thread-safe).
        
        Sessions are renewed if:
        - None or closed
        - Older than SESSION_MAX_AGE_SECONDS to prevent stale connections
        """
        async with self._session_lock:
            now = time.monotonic()
            session_expired = (
                self._session_created_at is not None
                and (now - self._session_created_at) > self.SESSION_MAX_AGE_SECONDS
            )
            
            if self._session is None or self._session.closed or session_expired:
                # Close old session if exists
                if self._session and not self._session.closed:
                    try:
                        await self._session.close()
                    except Exception:
                        pass
                
                self._session = aiohttp.ClientSession(
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=aiohttp.ClientTimeout(
                        total=60,
                        connect=10,
                        sock_connect=10,
                        sock_read=30,
                    ),
                )
                self._session_created_at = now
                _LOGGER.debug("Created new aiohttp session (previous expired: %s)", session_expired)
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    @property
    def metrics(self) -> GroqMetrics:
        """Get current metrics."""
        return self._metrics
    
    def reset_metrics(self) -> None:
        """Reset all metrics to zero."""
        self._metrics = GroqMetrics()

    async def _execute_with_retry(
        self,
        session: aiohttp.ClientSession,
        payload: dict[str, Any],
    ) -> aiohttp.ClientResponse:
        """Execute API request with exponential backoff retry."""
        last_error: Exception | None = None
        
        for attempt in range(LLM_MAX_RETRIES):
            try:
                response = await session.post(GROQ_API_URL, json=payload)
                
                if response.status == 200 or response.status not in LLM_RETRIABLE_STATUS_CODES:
                    return response
                
                error_text = await response.text()
                response.close()
                last_error = GroqError(f"API error: {response.status} - {error_text}", response.status)
                
                if attempt < LLM_MAX_RETRIES - 1:
                    delay = min(LLM_RETRY_BASE_DELAY * (2 ** attempt), LLM_RETRY_MAX_DELAY)
                    _LOGGER.warning(
                        "Groq API error (attempt %d/%d): %s. Retrying in %.1fs",
                        attempt + 1, LLM_MAX_RETRIES, response.status, delay
                    )
                    self._metrics.total_retries += 1
                    await asyncio.sleep(delay)
                    
            except asyncio.TimeoutError as err:
                last_error = GroqError(f"Request timeout: {err}")
                _LOGGER.warning(
                    "Groq request timeout (attempt %d/%d): %s",
                    attempt + 1, LLM_MAX_RETRIES, err
                )
                if attempt < LLM_MAX_RETRIES - 1:
                    delay = min(LLM_RETRY_BASE_DELAY * (2 ** attempt), LLM_RETRY_MAX_DELAY)
                    _LOGGER.debug("Retrying in %.1fs...", delay)
                    self._metrics.total_retries += 1
                    await asyncio.sleep(delay)
                    
            except aiohttp.ClientError as err:
                last_error = GroqError(f"Network error: {err}")
                _LOGGER.warning(
                    "Groq network error (attempt %d/%d): %s",
                    attempt + 1, LLM_MAX_RETRIES, err
                )
                if attempt < LLM_MAX_RETRIES - 1:
                    delay = min(LLM_RETRY_BASE_DELAY * (2 ** attempt), LLM_RETRY_MAX_DELAY)
                    _LOGGER.debug("Retrying in %.1fs...", delay)
                    self._metrics.total_retries += 1
                    await asyncio.sleep(delay)
        
        # Log final failure with details
        _LOGGER.error(
            "Groq API request failed after %d attempts: %s",
            LLM_MAX_RETRIES, last_error
        )
        self._metrics.failed_requests += 1
        raise last_error or GroqError("Unknown error after retries")

    def _build_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """Build messages list for API request.
        
        Groq uses automatic caching - no cache_control needed.
        Just send plain messages in OpenAI format.
        """
        return [msg.to_dict() for msg in messages]

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,  # Unused for Groq but kept for API compatibility
    ) -> AsyncGenerator[str, None]:
        """Send a streaming chat request to Groq API.
        
        Yields content chunks as they arrive.
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

        try:
            async with await self._execute_with_retry(session, payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    _LOGGER.error("Groq API error: %s", error_text)
                    self._metrics.failed_requests += 1
                    raise GroqError(f"API error: {response.status} - {error_text}")

                async for line in response.content:
                    line = line.decode("utf-8").strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            elapsed_ms = (time.monotonic() - start_time) * 1000
                            self._metrics.successful_requests += 1
                            self._metrics.total_response_time_ms += elapsed_ms
                            break
                        try:
                            data = json.loads(data_str)
                            
                            # Extract usage info
                            if usage := data.get("usage"):
                                _LOGGER.debug("Got usage in stream: %s", usage)
                                self._metrics.total_prompt_tokens += usage.get("prompt_tokens", 0)
                                self._metrics.total_completion_tokens += usage.get("completion_tokens", 0)
                                
                                # Check for cached tokens
                                prompt_details = usage.get("prompt_tokens_details", {})
                                cached = prompt_details.get("cached_tokens", 0)
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
                            
                            # Extract content delta
                            if choices := data.get("choices"):
                                if delta := choices[0].get("delta"):
                                    if content := delta.get("content"):
                                        yield content
                                        
                        except json.JSONDecodeError:
                            continue

        except Exception as err:
            self._metrics.failed_requests += 1
            _LOGGER.error("Groq streaming error: %s", err)
            raise

    async def chat_stream_full(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Send a streaming chat request and yield full delta events.
        
        Yields:
            dict with keys:
            - {"content": str} for content chunks
            - {"tool_calls": list} when tool calls are complete
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

        _LOGGER.debug("Sending full streaming request to Groq: %s", self._model)

        self._metrics.total_requests += 1
        start_time = time.monotonic()

        # Track tool calls being built
        pending_tool_calls: dict[int, dict[str, Any]] = {}

        try:
            async with await self._execute_with_retry(session, payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    _LOGGER.error("Groq API error: %s", error_text)
                    self._metrics.failed_requests += 1
                    raise GroqError(f"API error: {response.status} - {error_text}")

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
                            completed_tools = []
                            for idx in sorted(pending_tool_calls.keys()):
                                tc = pending_tool_calls[idx]
                                try:
                                    args = json.loads(tc.get("arguments", "{}"))
                                except json.JSONDecodeError:
                                    args = {}
                                completed_tools.append(ToolCall(
                                    id=tc.get("id", ""),
                                    name=tc.get("name", ""),
                                    arguments=args,
                                ))
                            yield {"tool_calls": completed_tools}
                        
                        yield {"finish_reason": "stop"}
                        break
                        
                    try:
                        data = json.loads(data_str)
                        
                        # Extract usage info
                        if usage := data.get("usage"):
                            _LOGGER.debug("Got usage in full stream: %s", usage)
                            self._metrics.total_prompt_tokens += usage.get("prompt_tokens", 0)
                            self._metrics.total_completion_tokens += usage.get("completion_tokens", 0)
                            
                            prompt_details = usage.get("prompt_tokens_details", {})
                            cached = prompt_details.get("cached_tokens", 0)
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
                            if tool_calls := delta.get("tool_calls"):
                                for tc in tool_calls:
                                    idx = tc.get("index", 0)
                                    if idx not in pending_tool_calls:
                                        pending_tool_calls[idx] = {
                                            "id": tc.get("id", ""),
                                            "name": "",
                                            "arguments": "",
                                        }
                                    
                                    if func := tc.get("function"):
                                        if name := func.get("name"):
                                            pending_tool_calls[idx]["name"] = name
                                        if args := func.get("arguments"):
                                            pending_tool_calls[idx]["arguments"] += args
                                    
                                    if tc_id := tc.get("id"):
                                        pending_tool_calls[idx]["id"] = tc_id
                            
                            # Finish reason
                            if finish_reason and finish_reason != "null":
                                if finish_reason == "tool_calls" and pending_tool_calls:
                                    completed_tools = []
                                    for idx in sorted(pending_tool_calls.keys()):
                                        tc = pending_tool_calls[idx]
                                        try:
                                            args = json.loads(tc.get("arguments", "{}"))
                                        except json.JSONDecodeError:
                                            args = {}
                                        completed_tools.append(ToolCall(
                                            id=tc.get("id", ""),
                                            name=tc.get("name", ""),
                                            arguments=args,
                                        ))
                                    yield {"tool_calls": completed_tools}
                                
                                yield {"finish_reason": finish_reason}
                                    
                    except json.JSONDecodeError:
                        continue

        except Exception as err:
            self._metrics.failed_requests += 1
            _LOGGER.error("Groq full streaming error: %s", err)
            raise

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,
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
                    raise GroqError(f"API error: {response.status} - {error_text}")

                data = await response.json()
                
                elapsed_ms = (time.monotonic() - start_time) * 1000
                self._metrics.successful_requests += 1
                self._metrics.total_response_time_ms += elapsed_ms
                
                # Extract usage
                if usage := data.get("usage"):
                    self._metrics.total_prompt_tokens += usage.get("prompt_tokens", 0)
                    self._metrics.total_completion_tokens += usage.get("completion_tokens", 0)
                    
                    prompt_details = usage.get("prompt_tokens_details", {})
                    cached = prompt_details.get("cached_tokens", 0)
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
            self._metrics.failed_requests += 1
            _LOGGER.error("Groq chat error: %s", err)
            raise
