"""OpenRouter API client for Smart Assist."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import aiohttp

from ..const import OPENROUTER_API_URL, PROVIDER_CACHING_SUPPORT, supports_prompt_caching
from .models import ChatMessage, ChatResponse, MessageRole, ToolCall

_LOGGER = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds
RETRY_MAX_DELAY = 10.0  # seconds
RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}
STREAM_CHUNK_TIMEOUT = 30.0  # seconds - max time to wait for next chunk


@dataclass
class LLMMetrics:
    """Metrics for LLM API calls."""
    
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_retries: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_response_time_ms: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    empty_responses: int = 0  # Streams that returned no content
    stream_timeouts: int = 0  # Streams that timed out waiting for chunks
    
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
            "empty_responses": self.empty_responses,
            "stream_timeouts": self.stream_timeouts,
        }


class OpenRouterClient:
    """Client for OpenRouter API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        provider: str = "auto",
        temperature: float = 0.5,
        max_tokens: int = 500,
        enable_caching: bool = True,
        cache_ttl_extended: bool = False,
    ) -> None:
        """Initialize the OpenRouter client."""
        self._api_key = api_key
        self._model = model
        self._provider = provider
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._cache_ttl_extended = cache_ttl_extended
        
        # Determine if caching is available based on model and provider
        self._enable_caching = self._check_caching_support(model, provider, enable_caching)
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()  # Lock for thread-safe session creation
        
        # Initialize metrics tracking
        self._metrics = LLMMetrics()
    
    def _check_caching_support(self, model: str, provider: str, user_enabled: bool) -> bool:
        """Check if prompt caching is supported for this model/provider combination."""
        if not user_enabled:
            return False
        
        if not supports_prompt_caching(model):
            return False
        
        if provider == "auto":
            # With auto routing, caching MAY work but is not guaranteed
            _LOGGER.info(
                "Prompt caching enabled but provider is 'auto'. "
                "Caching may not work with all providers. "
                "Select a specific provider for guaranteed caching."
            )
            return True
        
        # Check provider-specific support
        for model_prefix, providers in PROVIDER_CACHING_SUPPORT.items():
            if model.startswith(model_prefix):
                return providers.get(provider, False)
        
        return False

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session (thread-safe)."""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/smart-assist",
                        "X-Title": "Smart Assist for Home Assistant",
                    },
                    timeout=aiohttp.ClientTimeout(total=60),
                )
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    @property
    def metrics(self) -> LLMMetrics:
        """Get current metrics."""
        return self._metrics
    
    def reset_metrics(self) -> None:
        """Reset all metrics to zero."""
        self._metrics = LLMMetrics()
    
    async def _execute_with_retry(
        self,
        session: aiohttp.ClientSession,
        payload: dict[str, Any],
        stream: bool = False,
    ) -> aiohttp.ClientResponse:
        """Execute API request with exponential backoff retry.
        
        Args:
            session: aiohttp session
            payload: Request payload
            stream: Whether this is a streaming request
            
        Returns:
            aiohttp.ClientResponse
            
        Raises:
            OpenRouterError: If all retries fail
        """
        last_error: Exception | None = None
        
        for attempt in range(MAX_RETRIES):
            try:
                response = await session.post(OPENROUTER_API_URL, json=payload)
                
                # Success or non-retriable error
                if response.status == 200 or response.status not in RETRIABLE_STATUS_CODES:
                    return response
                
                # Retriable error - close response and retry
                error_text = await response.text()
                response.close()
                last_error = OpenRouterError(f"API error: {response.status} - {error_text}")
                
                if attempt < MAX_RETRIES - 1:
                    delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                    _LOGGER.warning(
                        "OpenRouter API error (attempt %d/%d): %s. Retrying in %.1fs",
                        attempt + 1, MAX_RETRIES, response.status, delay
                    )
                    self._metrics.total_retries += 1
                    await asyncio.sleep(delay)
                    
            except aiohttp.ClientError as err:
                last_error = OpenRouterError(f"Network error: {err}")
                if attempt < MAX_RETRIES - 1:
                    delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                    _LOGGER.warning(
                        "Network error (attempt %d/%d): %s. Retrying in %.1fs",
                        attempt + 1, MAX_RETRIES, err, delay
                    )
                    self._metrics.total_retries += 1
                    await asyncio.sleep(delay)
        
        # All retries exhausted
        self._metrics.failed_requests += 1
        raise last_error or OpenRouterError("Unknown error after retries")

    def _build_messages(
        self,
        messages: list[ChatMessage],
        cached_prefix_length: int = 0,
    ) -> list[dict[str, Any]]:
        """Build messages list for API request.
        
        For Anthropic/Gemini prompt caching, cache_control must be in the text content part.
        For Groq and other providers, caching is automatic and no cache_control is needed.
        Adding cache_control to non-supporting providers may break caching.
        See: https://openrouter.ai/docs/prompt-caching
        """
        result = []
        
        # Only add cache_control for providers that require explicit caching
        # Groq, OpenAI, DeepSeek use automatic caching - no cache_control needed
        requires_explicit_caching = (
            self._model.startswith("anthropic/") or 
            self._model.startswith("google/")
        )
        
        for i, msg in enumerate(messages):
            # Check if this message should have caching enabled (only for Anthropic/Gemini)
            should_cache = (
                self._enable_caching and 
                requires_explicit_caching and 
                i < cached_prefix_length
            )
            
            if should_cache and msg.role.value in ("system", "user"):
                # Build cache_control object
                # For Anthropic: default 5min TTL, optionally 1 hour
                cache_control: dict[str, Any] = {"type": "ephemeral"}
                if self._cache_ttl_extended and self._model.startswith("anthropic/"):
                    cache_control["ttl"] = "1h"
                
                # For cacheable messages, use multipart content format with cache_control
                # This is required for Anthropic Claude models
                result.append({
                    "role": msg.role.value,
                    "content": [
                        {
                            "type": "text",
                            "text": msg.content,
                            "cache_control": cache_control
                        }
                    ]
                })
            else:
                result.append(msg.to_dict())
        return result

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,
    ) -> ChatResponse:
        """Send a chat request to the API."""
        session = await self._get_session()

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._build_messages(messages, cached_prefix_length),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        # Add provider routing if a specific provider is selected
        if self._provider and self._provider != "auto":
            payload["provider"] = {
                "only": [self._provider],  # Strictly use only this provider
            }

        _LOGGER.debug("Sending request to OpenRouter: %s (provider: %s)", self._model, self._provider)
        
        self._metrics.total_requests += 1
        start_time = time.monotonic()

        try:
            async with await self._execute_with_retry(session, payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    _LOGGER.error("OpenRouter API error: %s", error_text)
                    self._metrics.failed_requests += 1
                    raise OpenRouterError(f"API error: {response.status} - {error_text}")

                data = await response.json()
                result = self._parse_response(data)
                
                # Update metrics
                elapsed_ms = (time.monotonic() - start_time) * 1000
                self._metrics.successful_requests += 1
                self._metrics.total_response_time_ms += elapsed_ms
                self._metrics.total_prompt_tokens += result.prompt_tokens
                self._metrics.total_completion_tokens += result.completion_tokens
                
                # Track cache hits from usage data
                if "cache_read_input_tokens" in result.usage:
                    self._metrics.cache_hits += 1
                elif self._enable_caching:
                    self._metrics.cache_misses += 1
                
                return result

        except OpenRouterError:
            raise
        except Exception as err:
            _LOGGER.error("Unexpected error: %s", err)
            self._metrics.failed_requests += 1
            raise OpenRouterError(f"Unexpected error: {err}") from err

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,
    ) -> AsyncGenerator[str, None]:
        """Send a streaming chat request to the API.
        
        Includes retry logic for empty responses.
        """
        session = await self._get_session()

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._build_messages(messages, cached_prefix_length),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},  # Request usage info in streaming
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        # Add provider routing if a specific provider is selected
        if self._provider and self._provider != "auto":
            payload["provider"] = {
                "only": [self._provider],  # Strictly use only this provider
            }

        # Debug: Log message structure for cache analysis
        import hashlib
        msg_summary = []
        prefix_content = []
        for i, msg in enumerate(payload["messages"]):
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, str):
                content_len = len(content)
                content_text = content
            elif isinstance(content, list):
                content_len = sum(len(c.get("text", "")) for c in content if isinstance(c, dict))
                content_text = "".join(c.get("text", "") for c in content if isinstance(c, dict))
            else:
                content_len = 0
                content_text = ""
            msg_summary.append(f"{i}:{role}:{content_len}chars")
            # Collect first 3 messages for prefix hash
            if i < 3:
                prefix_content.append(f"{role}:{content_text}")
        
        # Hash the prefix (messages + tools) to detect changes
        prefix_hash = hashlib.md5("|||".join(prefix_content).encode()).hexdigest()[:8]
        tools_hash = hashlib.md5(json.dumps(tools, sort_keys=True).encode()).hexdigest()[:8] if tools else "no_tools"
        
        _LOGGER.debug("Sending streaming request to OpenRouter: %s (provider: %s)", self._model, self._provider)
        _LOGGER.debug("Message structure: %s (prefix_hash: %s, tools_hash: %s)", ", ".join(msg_summary), prefix_hash, tools_hash)
        
        self._metrics.total_requests += 1
        start_time = time.monotonic()
        last_error: Exception | None = None

        # Retry loop for empty responses
        for attempt in range(MAX_RETRIES):
            received_content = False
            stream_completed = False

            try:
                async with await self._execute_with_retry(session, payload, stream=True) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        _LOGGER.error("OpenRouter API error: %s", error_text)
                        self._metrics.failed_requests += 1
                        raise OpenRouterError(f"API error: {response.status} - {error_text}")

                    async for line in response.content:
                        line = line.decode("utf-8").strip()
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                stream_completed = True
                                # Update metrics on completion
                                elapsed_ms = (time.monotonic() - start_time) * 1000
                                self._metrics.successful_requests += 1
                                self._metrics.total_response_time_ms += elapsed_ms
                                _LOGGER.debug("Stream completed. Metrics: tokens=%d+%d, cache_hits=%d",
                                             self._metrics.total_prompt_tokens,
                                             self._metrics.total_completion_tokens,
                                             self._metrics.cache_hits)
                                break
                            try:
                                data = json.loads(data_str)
                                # Extract usage info from streaming response
                                if usage := data.get("usage"):
                                    _LOGGER.debug("Got usage in stream: %s", usage)
                                    self._metrics.total_prompt_tokens += usage.get("prompt_tokens", 0)
                                    self._metrics.total_completion_tokens += usage.get("completion_tokens", 0)
                                    # Track cache hits
                                    if "cache_read_input_tokens" in usage or usage.get("prompt_tokens_details", {}).get("cached_tokens", 0) > 0:
                                        self._metrics.cache_hits += 1
                                    elif self._enable_caching:
                                        self._metrics.cache_misses += 1
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                if content := delta.get("content"):
                                    received_content = True
                                    yield content
                            except json.JSONDecodeError:
                                continue

                # Check for empty response
                if stream_completed and not received_content:
                    self._metrics.empty_responses += 1
                    last_error = OpenRouterError("Empty response: stream completed without content")
                    
                    if attempt < MAX_RETRIES - 1:
                        delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                        _LOGGER.warning(
                            "Empty stream response (attempt %d/%d). Retrying in %.1fs",
                            attempt + 1, MAX_RETRIES, delay
                        )
                        self._metrics.total_retries += 1
                        await asyncio.sleep(delay)
                        continue
                    else:
                        self._metrics.failed_requests += 1
                        raise last_error
                
                # Success
                return

            except asyncio.TimeoutError:
                self._metrics.stream_timeouts += 1
                last_error = OpenRouterError("Stream timeout")
                
                if attempt < MAX_RETRIES - 1:
                    delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                    _LOGGER.warning(
                        "Stream timeout (attempt %d/%d). Retrying in %.1fs",
                        attempt + 1, MAX_RETRIES, delay
                    )
                    self._metrics.total_retries += 1
                    await asyncio.sleep(delay)
                    continue
                else:
                    self._metrics.failed_requests += 1
                    raise last_error

            except OpenRouterError:
                raise
            except Exception as err:
                _LOGGER.error("Streaming error: %s", err)
                self._metrics.failed_requests += 1
                raise OpenRouterError(f"Streaming error: {err}") from err
        
        # All retries exhausted
        self._metrics.failed_requests += 1
        raise last_error or OpenRouterError("Unknown error after stream retries")

    async def chat_stream_full(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Send a streaming chat request and yield full delta events.
        
        This is the advanced streaming method that yields both content and tool calls.
        Used for HA's ConversationEntity streaming interface.
        
        Includes retry logic for empty responses and stream timeouts.
        
        Yields:
            dict with keys:
            - {"content": str} for content chunks
            - {"tool_calls": list} when tool calls are complete
            - {"finish_reason": str} when stream is done
        """
        session = await self._get_session()

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._build_messages(messages, cached_prefix_length),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},  # Request usage info in streaming
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        if self._provider and self._provider != "auto":
            payload["provider"] = {
                "only": [self._provider],  # Strictly use only this provider
            }

        # Debug: Log message structure for cache analysis
        import hashlib
        msg_summary = []
        prefix_content = []
        for i, msg in enumerate(payload["messages"]):
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, str):
                content_len = len(content)
                content_text = content
            elif isinstance(content, list):
                content_len = sum(len(c.get("text", "")) for c in content if isinstance(c, dict))
                content_text = "".join(c.get("text", "") for c in content if isinstance(c, dict))
            else:
                content_len = 0
                content_text = ""
            msg_summary.append(f"{i}:{role}:{content_len}chars")
            # Collect first 3 messages for prefix hash
            if i < 3:
                prefix_content.append(f"{role}:{content_text}")
        
        # Hash the prefix (messages + tools) to detect changes
        prefix_hash = hashlib.md5("|||".join(prefix_content).encode()).hexdigest()[:8]
        tools_hash = hashlib.md5(json.dumps(tools, sort_keys=True).encode()).hexdigest()[:8] if tools else "no_tools"
        
        _LOGGER.debug("Sending full streaming request to OpenRouter: %s (provider: %s)", self._model, self._provider)
        _LOGGER.debug("Message structure: %s (prefix_hash: %s, tools_hash: %s)", ", ".join(msg_summary), prefix_hash, tools_hash)

        self._metrics.total_requests += 1
        start_time = time.monotonic()
        last_error: Exception | None = None

        # Retry loop for empty responses and stream failures
        for attempt in range(MAX_RETRIES):
            # Track tool calls being built
            pending_tool_calls: dict[int, dict[str, Any]] = {}
            received_content = False
            received_tool_calls = False
            stream_completed = False

            try:
                async with await self._execute_with_retry(session, payload, stream=True) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        _LOGGER.error("OpenRouter API error: %s", error_text)
                        self._metrics.failed_requests += 1
                        raise OpenRouterError(f"API error: {response.status} - {error_text}")

                    async for line in response.content:
                        line = line.decode("utf-8").strip()
                        if not line.startswith("data: "):
                            continue
                        
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            stream_completed = True
                            # Emit any completed tool calls
                            if pending_tool_calls:
                                received_tool_calls = True
                                completed_tools = []
                                for idx in sorted(pending_tool_calls.keys()):
                                    tc = pending_tool_calls[idx]
                                    # Parse arguments
                                    args = tc.get("arguments", "{}")
                                    try:
                                        args = json.loads(args) if isinstance(args, str) else args
                                    except json.JSONDecodeError:
                                        args = {}
                                    completed_tools.append(
                                        ToolCall(
                                            id=tc.get("id", f"tool_{idx}"),
                                            name=tc.get("name", ""),
                                            arguments=args,
                                        )
                                    )
                                yield {"tool_calls": completed_tools}
                            # Update metrics on stream completion
                            elapsed_ms = (time.monotonic() - start_time) * 1000
                            self._metrics.successful_requests += 1
                            self._metrics.total_response_time_ms += elapsed_ms
                            yield {"finish_reason": "stop"}
                            break
                        
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        
                        # Extract usage info from streaming response (sent with last chunk)
                        if usage := data.get("usage"):
                            _LOGGER.debug("Got usage in full stream: %s", usage)
                            self._metrics.total_prompt_tokens += usage.get("prompt_tokens", 0)
                            self._metrics.total_completion_tokens += usage.get("completion_tokens", 0)
                            # Track cache hits from usage data
                            if "cache_read_input_tokens" in usage or usage.get("prompt_tokens_details", {}).get("cached_tokens", 0) > 0:
                                self._metrics.cache_hits += 1
                            elif self._enable_caching:
                                self._metrics.cache_misses += 1
                        
                        choice = data.get("choices", [{}])[0]
                        delta = choice.get("delta", {})
                        
                        # Yield content chunks
                        if content := delta.get("content"):
                            received_content = True
                            yield {"content": content}
                        
                        # Accumulate tool calls
                        if tool_calls := delta.get("tool_calls"):
                            for tc in tool_calls:
                                idx = tc.get("index", 0)
                                if idx not in pending_tool_calls:
                                    pending_tool_calls[idx] = {
                                        "id": tc.get("id", ""),
                                        "name": "",
                                        "arguments": "",
                                    }
                                
                                # Update tool call info
                                if tc.get("id"):
                                    pending_tool_calls[idx]["id"] = tc["id"]
                                if func := tc.get("function"):
                                    if name := func.get("name"):
                                        pending_tool_calls[idx]["name"] = name
                                    if args := func.get("arguments"):
                                        pending_tool_calls[idx]["arguments"] += args
                        
                        # Check for finish reason (tool_calls means we're done building)
                        if finish_reason := choice.get("finish_reason"):
                            stream_completed = True
                            if finish_reason == "tool_calls" and pending_tool_calls:
                                received_tool_calls = True
                                completed_tools = []
                                for idx in sorted(pending_tool_calls.keys()):
                                    tc = pending_tool_calls[idx]
                                    args = tc.get("arguments", "{}")
                                    try:
                                        args = json.loads(args) if isinstance(args, str) else args
                                    except json.JSONDecodeError:
                                        args = {}
                                    completed_tools.append(
                                        ToolCall(
                                            id=tc.get("id", f"tool_{idx}"),
                                            name=tc.get("name", ""),
                                            arguments=args,
                                        )
                                    )
                                yield {"tool_calls": completed_tools}
                                pending_tool_calls.clear()
                            yield {"finish_reason": finish_reason}

                # Check if we got an empty response (stream completed but no content/tools)
                if stream_completed and not received_content and not received_tool_calls:
                    self._metrics.empty_responses += 1
                    last_error = OpenRouterError("Empty response: stream completed without content or tool calls")
                    
                    if attempt < MAX_RETRIES - 1:
                        delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                        _LOGGER.warning(
                            "Empty stream response (attempt %d/%d). Retrying in %.1fs",
                            attempt + 1, MAX_RETRIES, delay
                        )
                        self._metrics.total_retries += 1
                        await asyncio.sleep(delay)
                        continue
                    else:
                        self._metrics.failed_requests += 1
                        raise last_error
                
                # Stream completed successfully with content
                return

            except asyncio.TimeoutError:
                self._metrics.stream_timeouts += 1
                last_error = OpenRouterError("Stream timeout: no data received within timeout period")
                
                if attempt < MAX_RETRIES - 1:
                    delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                    _LOGGER.warning(
                        "Stream timeout (attempt %d/%d). Retrying in %.1fs",
                        attempt + 1, MAX_RETRIES, delay
                    )
                    self._metrics.total_retries += 1
                    await asyncio.sleep(delay)
                    continue
                else:
                    self._metrics.failed_requests += 1
                    raise last_error

            except OpenRouterError:
                raise
            except Exception as err:
                _LOGGER.error("Full streaming error: %s", err)
                self._metrics.failed_requests += 1
                raise OpenRouterError(f"Full streaming error: {err}") from err
        
        # All retries exhausted
        self._metrics.failed_requests += 1
        raise last_error or OpenRouterError("Unknown error after stream retries")

    def _parse_response(self, data: dict[str, Any]) -> ChatResponse:
        """Parse API response into ChatResponse."""
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = data.get("usage", {})

        # Parse tool calls if present
        tool_calls: list[ToolCall] = []
        if raw_tool_calls := message.get("tool_calls"):
            for tc in raw_tool_calls:
                func = tc.get("function", {})
                args = func.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", ""),
                        name=func.get("name", ""),
                        arguments=args,
                    )
                )

        return ChatResponse(
            content=message.get("content", ""),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage=usage,
        )

    def update_settings(
        self,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_caching: bool | None = None,
    ) -> None:
        """Update client settings."""
        if model is not None:
            self._model = model
            if enable_caching is None:
                self._enable_caching = supports_prompt_caching(model)
        if temperature is not None:
            self._temperature = temperature
        if max_tokens is not None:
            self._max_tokens = max_tokens
        if enable_caching is not None:
            self._enable_caching = enable_caching and supports_prompt_caching(self._model)


class OpenRouterError(Exception):
    """Exception for OpenRouter API errors."""

    pass
