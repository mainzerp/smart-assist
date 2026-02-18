"""OpenRouter API client for Smart Assist."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, AsyncGenerator

from ..const import (
    LLM_MAX_RETRIES,
    LLM_RETRY_BASE_DELAY,
    LLM_RETRY_MAX_DELAY,
    OPENROUTER_API_URL,
    PROVIDER_CACHING_SUPPORT,
    supports_prompt_caching,
)
from ..utils import sanitize_user_facing_error
from .base_client import BaseLLMClient, LLMMetrics
from .models import ChatMessage, ChatResponse, LLMError, MessageRole, ToolCall

_LOGGER = logging.getLogger(__name__)


class OpenRouterClient(BaseLLMClient):
    """Client for OpenRouter API."""

    @property
    def supports_native_structured_output(self) -> bool:
        """OpenRouter can support json_schema mode on compatible routes/models."""
        return True

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
        super().__init__(api_key=api_key, model=model, temperature=temperature, max_tokens=max_tokens)
        self._provider = provider
        self._cache_ttl_extended = cache_ttl_extended
        
        # Determine if caching is available based on model and provider
        self._enable_caching = self._check_caching_support(model, provider, enable_caching)
    
    def _get_api_url(self) -> str:
        """Return the OpenRouter API endpoint URL."""
        return OPENROUTER_API_URL
    
    def _get_session_headers(self) -> dict[str, str]:
        """Return headers for the OpenRouter API session."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/smart-assist",
            "X-Title": "Smart Assist for Home Assistant",
        }
    
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
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        use_native_structured_output: bool = False,
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

        if self._supports_native_schema_mode(
            use_native_structured_output=use_native_structured_output,
            response_schema=response_schema,
        ):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema_name or "smart_assist_task",
                    "strict": True,
                    "schema": response_schema,
                },
            }
        
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
                    raise OpenRouterError(
                        sanitize_user_facing_error(
                            f"API error: {response.status} - {error_text}",
                            fallback=f"API error: {response.status}",
                        )
                    )

                data = await response.json()
                result = self._parse_response(data)
                
                # Update metrics
                elapsed_ms = (time.monotonic() - start_time) * 1000
                self._metrics.successful_requests += 1
                self._metrics.total_response_time_ms += elapsed_ms
                self._metrics.total_prompt_tokens += result.prompt_tokens
                self._metrics.total_completion_tokens += result.completion_tokens
                # Per-request tracking
                self._metrics._last_prompt_tokens = result.prompt_tokens
                self._metrics._last_completion_tokens = result.completion_tokens
                cached_in_usage = result.usage.get("cache_read_input_tokens", 0) or result.usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
                self._metrics._last_cached_tokens = cached_in_usage or 0
                
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
            raise OpenRouterError(
                sanitize_user_facing_error(err, fallback="Unexpected provider error")
            ) from err

    def _supports_native_schema_mode(
        self,
        use_native_structured_output: bool,
        response_schema: dict[str, Any] | None,
    ) -> bool:
        """Return True when native OpenRouter json_schema mode should be used."""
        if not use_native_structured_output or not response_schema:
            return False

        if self._provider not in ("auto", "openai"):
            return False

        return self._model.startswith("openai/")

    async def _stream_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Shared streaming implementation that yields full delta events.

        Handles payload building, SSE parsing, usage tracking, tool call
        accumulation, retry logic for empty responses, and stream timeouts.

        Yields:
            dict with keys:
            - {"content": str} for content chunks
            - {"tool_calls": list[ToolCall]} when tool calls are complete
            - {"finish_reason": str} when stream is done
        """
        session = await self._get_session()

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._build_messages(messages, cached_prefix_length),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        if self._provider and self._provider != "auto":
            payload["provider"] = {
                "only": [self._provider],
            }

        # Debug: Log message structure for cache analysis
        if _LOGGER.isEnabledFor(logging.DEBUG):
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
                if i < 3:
                    prefix_content.append(f"{role}:{content_text}")

            prefix_hash = hashlib.sha256("|||".join(prefix_content).encode()).hexdigest()[:8]
            tools_hash = hashlib.sha256(json.dumps(tools, sort_keys=True).encode()).hexdigest()[:8] if tools else "no_tools"

            _LOGGER.debug("Sending streaming request to OpenRouter: %s (provider: %s)", self._model, self._provider)
            _LOGGER.debug("Message structure: %s (prefix_hash: %s, tools_hash: %s)", ", ".join(msg_summary), prefix_hash, tools_hash)

        self._metrics.total_requests += 1
        start_time = time.monotonic()
        last_error: Exception | None = None

        for attempt in range(LLM_MAX_RETRIES):
            pending_tool_calls: dict[int, dict[str, Any]] = {}
            received_content = False
            received_tool_calls = False
            stream_completed = False

            try:
                async with await self._execute_with_retry(session, payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        _LOGGER.error("OpenRouter API error: %s", error_text)
                        self._metrics.failed_requests += 1
                        raise OpenRouterError(
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
                            stream_completed = True
                            # Emit any pending tool calls
                            if pending_tool_calls:
                                received_tool_calls = True
                                completed_tools = self._build_tool_calls(pending_tool_calls)
                                yield {"tool_calls": completed_tools}
                            # Update metrics
                            elapsed_ms = (time.monotonic() - start_time) * 1000
                            self._metrics.successful_requests += 1
                            self._metrics.total_response_time_ms += elapsed_ms
                            yield {"finish_reason": "stop"}
                            break

                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # Extract usage info
                        if usage := data.get("usage"):
                            _LOGGER.debug("Got usage in stream: %s", usage)
                            self._metrics.total_prompt_tokens += usage.get("prompt_tokens", 0)
                            self._metrics.total_completion_tokens += usage.get("completion_tokens", 0)
                            self._metrics._last_prompt_tokens = usage.get("prompt_tokens", 0)
                            self._metrics._last_completion_tokens = usage.get("completion_tokens", 0)
                            cached = usage.get("cache_read_input_tokens", 0) or usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
                            self._metrics._last_cached_tokens = cached or 0
                            if cached > 0:
                                self._metrics.cache_hits += 1
                                self._metrics.cached_tokens += cached
                            elif self._enable_caching:
                                self._metrics.cache_misses += 1

                        choice = data.get("choices", [{}])[0]
                        delta = choice.get("delta", {})

                        # Yield content chunks
                        if content := delta.get("content"):
                            received_content = True
                            yield {"content": content}

                        # Accumulate tool calls
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

                        # Check for finish reason
                        if finish_reason := choice.get("finish_reason"):
                            stream_completed = True
                            if finish_reason == "tool_calls" and pending_tool_calls:
                                received_tool_calls = True
                                completed_tools = self._build_tool_calls(pending_tool_calls)
                                yield {"tool_calls": completed_tools}
                                pending_tool_calls.clear()
                            yield {"finish_reason": finish_reason}

                # Check for empty response
                if stream_completed and not received_content and not received_tool_calls:
                    self._metrics.empty_responses += 1
                    last_error = OpenRouterError("Empty response: stream completed without content or tool calls")

                    if attempt < LLM_MAX_RETRIES - 1:
                        delay = min(LLM_RETRY_BASE_DELAY * (2 ** attempt), LLM_RETRY_MAX_DELAY)
                        _LOGGER.warning(
                            "Empty stream response (attempt %d/%d). Retrying in %.1fs",
                            attempt + 1, LLM_MAX_RETRIES, delay
                        )
                        self._metrics.total_retries += 1
                        await asyncio.sleep(delay)
                        continue
                    else:
                        self._metrics.failed_requests += 1
                        raise last_error

                return

            except asyncio.TimeoutError:
                self._metrics.stream_timeouts += 1
                last_error = OpenRouterError("Stream timeout")

                if attempt < LLM_MAX_RETRIES - 1:
                    delay = min(LLM_RETRY_BASE_DELAY * (2 ** attempt), LLM_RETRY_MAX_DELAY)
                    _LOGGER.warning(
                        "Stream timeout (attempt %d/%d). Retrying in %.1fs",
                        attempt + 1, LLM_MAX_RETRIES, delay
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
                raise OpenRouterError(
                    sanitize_user_facing_error(err, fallback="Streaming error")
                ) from err

        self._metrics.failed_requests += 1
        raise last_error or OpenRouterError("Unknown error after stream retries")

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,
    ) -> AsyncGenerator[str, None]:
        """Send a streaming chat request, yielding content strings only.

        Delegates to _stream_request() and filters to content-only chunks.
        """
        async for chunk in self._stream_request(messages, tools, cached_prefix_length):
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
        Used for HA's ConversationEntity streaming interface.

        Yields:
            dict with keys:
            - {"content": str} for content chunks
            - {"tool_calls": list} when tool calls are complete
            - {"finish_reason": str} when stream is done
        """
        async for chunk in self._stream_request(messages, tools, cached_prefix_length):
            yield chunk

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


class OpenRouterError(LLMError):
    """Exception for OpenRouter API errors."""

    pass
