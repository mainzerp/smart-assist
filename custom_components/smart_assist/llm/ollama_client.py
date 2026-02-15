"""Ollama API client for Smart Assist - Local LLM integration."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator

import aiohttp

from .base_client import BaseLLMClient, LLMMetrics
from .models import ChatMessage, ChatResponse, LLMError, MessageRole, ToolCall
from ..const import (
    OLLAMA_DEFAULT_URL,
    OLLAMA_DEFAULT_MODEL,
    OLLAMA_DEFAULT_KEEP_ALIVE,
    OLLAMA_DEFAULT_NUM_CTX,
    OLLAMA_DEFAULT_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class OllamaError(LLMError):
    """Exception for Ollama API errors."""
    pass


@dataclass
class OllamaMetrics(LLMMetrics):
    """Metrics for Ollama API calls.
    
    Extends LLMMetrics with Ollama-specific fields for model loading
    and local cache state.
    """
    
    model_load_time_ms: float = 0.0
    cache_warm: bool = False
    
    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        result = super().to_dict()
        result["model_load_time_ms"] = round(self.model_load_time_ms, 2)
        result["cache_warm"] = self.cache_warm
        return result


class OllamaClient(BaseLLMClient):
    """Client for Ollama API - Local LLM integration.
    
    Ollama provides local inference with the following caching benefits:
    - KV Cache: Attention key-value pairs are cached while model is loaded
    - keep_alive: Controls how long model stays in memory (default: 5m, -1 = forever)
    - Consistent prefix (system prompt + entity index) maximizes cache hits
    """

    # Models known to have good tool calling support (for debug logging only)
    # Tools are always sent to Ollama - this list is just for informational logging
    KNOWN_TOOL_MODELS = [
        "llama3.1", "llama3.2", "llama3.3",
        "mistral", "mistral-nemo",
        "qwen2.5", "qwen3",
        "command-r", "command-r-plus",
        "gpt-oss",  # OpenAI open-weight reasoning models
        "granite3",  # IBM Granite
        "phi4",  # Microsoft Phi-4
        "deepseek-r1",  # DeepSeek reasoning models
        "gemma3",  # Google Gemma 3
    ]

    def __init__(
        self,
        base_url: str = OLLAMA_DEFAULT_URL,
        model: str = OLLAMA_DEFAULT_MODEL,
        temperature: float = 0.5,
        max_tokens: int = 500,
        keep_alive: str = OLLAMA_DEFAULT_KEEP_ALIVE,
        num_ctx: int = OLLAMA_DEFAULT_NUM_CTX,
        timeout: int = OLLAMA_DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the Ollama client.
        
        Args:
            base_url: Ollama server URL (default: http://localhost:11434)
            model: Model name (e.g., 'llama3.1:8b', 'mistral:7b')
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum completion tokens
            keep_alive: How long to keep model loaded ("-1" = forever, "5m" = 5 minutes)
            num_ctx: Context window size (default: 8192)
            timeout: Request timeout in seconds
        """
        super().__init__(api_key="", model=model, temperature=temperature, max_tokens=max_tokens)
        self._base_url = base_url.rstrip("/")
        self._keep_alive = keep_alive
        self._num_ctx = num_ctx
        self._timeout = timeout
        self._metrics = OllamaMetrics()  # Override with Ollama-specific metrics
        self._model_loaded = False
    
    def _get_api_url(self) -> str:
        """Return the Ollama API chat endpoint URL."""
        return f"{self._base_url}/api/chat"
    
    def _get_session_headers(self) -> dict[str, str]:
        """Return headers for the Ollama API session."""
        return {"Content-Type": "application/json"}
    
    def _get_session_timeout(self) -> aiohttp.ClientTimeout:
        """Return Ollama-specific timeout configuration."""
        return aiohttp.ClientTimeout(
            total=self._timeout,
            connect=10,
            sock_connect=10,
            sock_read=self._timeout,
        )
    
    @property
    def metrics(self) -> OllamaMetrics:
        """Get current metrics."""
        return self._metrics
    
    @property
    def is_model_loaded(self) -> bool:
        """Check if model is loaded in memory."""
        return self._model_loaded
    
    def reset_metrics(self) -> None:
        """Reset all metrics to zero."""
        self._metrics = OllamaMetrics()
    
    def supports_tools(self) -> bool:
        """Check if current model is known to support tool calling.
        
        Note: This is used for debug logging only. Tools are always sent
        to Ollama regardless of this check - Ollama handles model capabilities.
        """
        model_base = self._model.split(":")[0].lower()
        return any(
            model_base.startswith(known.lower())
            for known in self.KNOWN_TOOL_MODELS
        )

    async def is_available(self) -> bool:
        """Check if Ollama server is reachable.
        
        Returns:
            True if server responds, False otherwise
        """
        try:
            session = await self._get_session()
            async with session.get(
                f"{self._base_url}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                return response.status == 200
        except Exception as e:
            _LOGGER.debug("Ollama server not available: %s", e)
            return False

    async def list_models(self) -> list[dict[str, Any]]:
        """List available local models.
        
        Returns:
            List of model info dicts with 'name', 'size', 'modified_at' etc.
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self._base_url}/api/tags") as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("models", [])
                return []
        except Exception as e:
            _LOGGER.error("Failed to list Ollama models: %s", e)
            return []

    async def get_model_names(self) -> list[str]:
        """Get list of available model names.
        
        Returns:
            List of model names (e.g., ['llama3.1:8b', 'mistral:7b'])
        """
        models = await self.list_models()
        return [m.get("name", "") for m in models if m.get("name")]

    async def warm_cache(self) -> bool:
        """Preload model into memory for faster response times.
        
        This sends an empty request to load the model into GPU/CPU memory.
        The KV cache is initialized and ready for subsequent requests.
        
        Returns:
            True if model was successfully loaded
        """
        try:
            start_time = time.perf_counter()
            session = await self._get_session()
            
            payload = {
                "model": self._model,
                "keep_alive": self._format_keep_alive(),
            }
            
            async with session.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)  # Model loading can take time
            ) as response:
                if response.status == 200:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    self._metrics.model_load_time_ms = elapsed_ms
                    self._metrics.cache_warm = True
                    self._model_loaded = True
                    _LOGGER.info(
                        "Ollama model '%s' loaded in %.0fms (keep_alive: %s)",
                        self._model, elapsed_ms, self._keep_alive
                    )
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error("Failed to warm Ollama cache: %s", error_text)
                    return False
        except Exception as e:
            _LOGGER.error("Failed to warm Ollama cache: %s", e)
            return False

    async def unload_model(self) -> bool:
        """Unload model from memory to free resources.
        
        Returns:
            True if model was successfully unloaded
        """
        try:
            session = await self._get_session()
            
            payload = {
                "model": self._model,
                "keep_alive": "0",  # Immediately unload
            }
            
            async with session.post(
                f"{self._base_url}/api/generate",
                json=payload
            ) as response:
                if response.status == 200:
                    self._model_loaded = False
                    self._metrics.cache_warm = False
                    _LOGGER.info("Ollama model '%s' unloaded", self._model)
                    return True
                return False
        except Exception as e:
            _LOGGER.error("Failed to unload Ollama model: %s", e)
            return False

    async def get_running_models(self) -> list[dict[str, Any]]:
        """Get list of currently loaded models.
        
        Returns:
            List of running model info with name, size, processor usage
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self._base_url}/api/ps") as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("models", [])
                return []
        except Exception as e:
            _LOGGER.debug("Failed to get running models: %s", e)
            return []

    def _convert_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """Convert ChatMessage objects to Ollama API format.
        
        Args:
            messages: List of ChatMessage objects
            
        Returns:
            List of message dicts in Ollama format
        """
        converted = []
        for msg in messages:
            message_dict: dict[str, Any] = {
                "role": msg.role.value,
                "content": msg.content or "",
            }
            
            # Handle tool calls in assistant messages
            if msg.tool_calls:
                message_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments if isinstance(tc.arguments, dict) else json.loads(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            
            # Handle tool response messages
            if msg.role == MessageRole.TOOL and msg.tool_call_id:
                message_dict["tool_call_id"] = msg.tool_call_id
            
            converted.append(message_dict)
        
        return converted

    def _convert_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """Convert tools to Ollama format (OpenAI-compatible).
        
        Args:
            tools: List of tool definitions
            
        Returns:
            Tools in Ollama format
        """
        if not tools:
            return None
        
        # Ollama uses OpenAI-compatible format
        return tools

    def _format_keep_alive(self) -> int | str:
        """Format keep_alive value for Ollama API.
        
        Ollama accepts:
        - Integer (seconds): 0 = unload immediately, -1 = keep forever
        - String with unit: "5m", "1h", "24h"
        
        The string "-1" causes a parse error, so we convert to int.
        
        Returns:
            Formatted keep_alive value
        """
        # Handle -1 specially - must be sent as integer, not string
        if self._keep_alive == "-1" or self._keep_alive == -1:
            return -1
        # Handle 0 as integer for immediate unload
        if self._keep_alive == "0" or self._keep_alive == 0:
            return 0
        # Otherwise return as-is (string like "5m", "1h")
        return self._keep_alive

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        use_native_structured_output: bool = False,
    ) -> ChatResponse:
        """Send a chat completion request.
        
        Args:
            messages: Conversation messages
            tools: Optional tool definitions for function calling
            
        Returns:
            ChatResponse with content and optional tool calls
        """
        self._metrics.total_requests += 1
        start_time = time.perf_counter()
        
        try:
            session = await self._get_session()
            
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": self._convert_messages(messages),
                "stream": False,  # Streaming not yet implemented
                "keep_alive": self._format_keep_alive(),
                "options": {
                    "temperature": self._temperature,
                    "num_predict": self._max_tokens,
                    "num_ctx": self._num_ctx,
                },
            }
            
            # Always send tools to Ollama - it will handle them appropriately
            # based on the model's capabilities
            if tools:
                payload["tools"] = self._convert_tools(tools)
                # Only log info for unknown models (not a warning - tools may still work)
                if not self.supports_tools():
                    _LOGGER.debug(
                        "Sending tools to model '%s' (not in known tool-capable list, "
                        "but Ollama will handle appropriately)",
                        self._model
                    )
            
            async with session.post(
                f"{self._base_url}/api/chat",
                json=payload,
            ) as response:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                
                if response.status != 200:
                    error_text = await response.text()
                    self._metrics.failed_requests += 1
                    raise OllamaError(
                        f"Ollama API error: {response.status} - {error_text}",
                        response.status
                    )
                
                data = await response.json()
                
                # Parse response
                message = data.get("message", {})
                content = message.get("content", "")
                
                # Parse tool calls if present
                tool_calls: list[ToolCall] = []
                if "tool_calls" in message:
                    for tc in message["tool_calls"]:
                        function = tc.get("function", {})
                        tool_calls.append(ToolCall(
                            id=tc.get("id", f"call_{len(tool_calls)}"),
                            name=function.get("name", ""),
                            arguments=function.get("arguments", {}),
                        ))
                
                # Extract usage stats
                usage = {
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                }
                
                # Update metrics
                self._metrics.successful_requests += 1
                self._metrics.total_response_time_ms += elapsed_ms
                self._metrics.total_prompt_tokens += usage["prompt_tokens"]
                self._metrics.total_completion_tokens += usage["completion_tokens"]
                # Per-request tracking
                self._metrics._last_prompt_tokens = usage["prompt_tokens"]
                self._metrics._last_completion_tokens = usage["completion_tokens"]
                self._metrics._last_cached_tokens = 0
                self._model_loaded = True
                
                _LOGGER.debug(
                    "Ollama response in %.0fms: %d prompt tokens, %d completion tokens",
                    elapsed_ms, usage["prompt_tokens"], usage["completion_tokens"]
                )
                
                return ChatResponse(
                    content=content,
                    tool_calls=tool_calls,
                    finish_reason=data.get("done_reason", "stop"),
                    usage=usage,
                )
                
        except OllamaError:
            raise
        except asyncio.TimeoutError:
            self._metrics.failed_requests += 1
            raise OllamaError(
                f"Ollama request timed out after {self._timeout}s. "
                "Consider increasing timeout or using a smaller model.",
                status_code=408
            )
        except aiohttp.ClientError as e:
            self._metrics.failed_requests += 1
            raise OllamaError(
                f"Network error connecting to Ollama at {self._base_url}: {e}",
                status_code=None
            )
        except Exception as e:
            self._metrics.failed_requests += 1
            _LOGGER.exception("Unexpected error in Ollama chat")
            raise OllamaError(f"Unexpected error: {e}")

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        use_native_structured_output: bool = False,
    ) -> AsyncGenerator[str, None]:
        """Stream a chat completion response.
        
        Args:
            messages: Conversation messages
            tools: Optional tool definitions
            cached_prefix_length: Ignored (Ollama handles caching internally via KV cache)
            
        Yields:
            Content chunks as they arrive
        """
        self._metrics.total_requests += 1
        start_time = time.perf_counter()
        
        try:
            session = await self._get_session()
            
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": self._convert_messages(messages),
                "stream": True,
                "keep_alive": self._format_keep_alive(),
                "options": {
                    "temperature": self._temperature,
                    "num_predict": self._max_tokens,
                    "num_ctx": self._num_ctx,
                },
            }
            
            # Always send tools - Ollama handles model capabilities
            if tools:
                payload["tools"] = self._convert_tools(tools)
            
            async with session.post(
                f"{self._base_url}/api/chat",
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self._metrics.failed_requests += 1
                    raise OllamaError(
                        f"Ollama API error: {response.status} - {error_text}",
                        response.status
                    )
                
                total_content = ""
                async for line in response.content:
                    if not line:
                        continue
                    
                    try:
                        data = json.loads(line.decode("utf-8"))
                        message = data.get("message", {})
                        content = message.get("content", "")
                        
                        if content:
                            total_content += content
                            yield content
                        
                        # Check if stream is done
                        if data.get("done"):
                            elapsed_ms = (time.perf_counter() - start_time) * 1000
                            self._metrics.successful_requests += 1
                            self._metrics.total_response_time_ms += elapsed_ms
                            self._metrics.total_prompt_tokens += data.get("prompt_eval_count", 0)
                            self._metrics.total_completion_tokens += data.get("eval_count", 0)
                            # Per-request tracking
                            self._metrics._last_prompt_tokens = data.get("prompt_eval_count", 0)
                            self._metrics._last_completion_tokens = data.get("eval_count", 0)
                            self._metrics._last_cached_tokens = 0
                            self._model_loaded = True
                            break
                            
                    except json.JSONDecodeError:
                        continue
                        
        except OllamaError:
            raise
        except Exception as e:
            self._metrics.failed_requests += 1
            raise OllamaError(f"Streaming error: {e}")

    async def chat_stream_full(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        cached_prefix_length: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream a chat completion response with full delta events.
        
        This method is used by the conversation system for TTS streaming.
        Yields structured delta events compatible with Groq/OpenRouter clients.
        
        Args:
            messages: Conversation messages
            tools: Optional tool definitions
            cached_prefix_length: Ignored (Ollama handles caching internally)
            
        Yields:
            dict with keys:
            - {"content": str} for content chunks
            - {"tool_calls": list[ToolCall]} when tool calls are complete
            - {"finish_reason": str} when stream is done
        """
        self._metrics.total_requests += 1
        start_time = time.perf_counter()
        
        try:
            session = await self._get_session()
            
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": self._convert_messages(messages),
                "stream": True,
                "keep_alive": self._format_keep_alive(),
                "options": {
                    "temperature": self._temperature,
                    "num_predict": self._max_tokens,
                    "num_ctx": self._num_ctx,
                },
            }
            
            # Always send tools - Ollama handles model capabilities
            if tools:
                payload["tools"] = self._convert_tools(tools)
            
            async with session.post(
                f"{self._base_url}/api/chat",
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self._metrics.failed_requests += 1
                    raise OllamaError(
                        f"Ollama API error: {response.status} - {error_text}",
                        response.status
                    )
                
                # Track tool calls from stream
                pending_tool_calls: list[dict[str, Any]] = []
                
                async for line in response.content:
                    if not line:
                        continue
                    
                    try:
                        data = json.loads(line.decode("utf-8"))
                        message = data.get("message", {})
                        content = message.get("content", "")
                        
                        # Yield content chunks
                        if content:
                            yield {"content": content}
                        
                        # Capture tool calls (usually in final message)
                        if "tool_calls" in message:
                            for tc in message["tool_calls"]:
                                function = tc.get("function", {})
                                pending_tool_calls.append({
                                    "id": tc.get("id", f"call_{len(pending_tool_calls)}"),
                                    "name": function.get("name", ""),
                                    "arguments": function.get("arguments", {}),
                                })
                        
                        # Check if stream is done
                        if data.get("done"):
                            elapsed_ms = (time.perf_counter() - start_time) * 1000
                            self._metrics.successful_requests += 1
                            self._metrics.total_response_time_ms += elapsed_ms
                            self._metrics.total_prompt_tokens += data.get("prompt_eval_count", 0)
                            self._metrics.total_completion_tokens += data.get("eval_count", 0)
                            # Per-request tracking
                            self._metrics._last_prompt_tokens = data.get("prompt_eval_count", 0)
                            self._metrics._last_completion_tokens = data.get("eval_count", 0)
                            self._metrics._last_cached_tokens = 0
                            self._model_loaded = True
                            
                            # Emit tool calls if any
                            if pending_tool_calls:
                                tool_calls = [
                                    ToolCall(
                                        id=tc["id"],
                                        name=tc["name"],
                                        arguments=tc["arguments"],
                                    )
                                    for tc in pending_tool_calls
                                ]
                                yield {"tool_calls": tool_calls}
                            
                            # Emit finish reason
                            yield {"finish_reason": data.get("done_reason", "stop")}
                            break
                            
                    except json.JSONDecodeError:
                        continue
                        
        except OllamaError:
            raise
        except asyncio.TimeoutError:
            self._metrics.failed_requests += 1
            raise OllamaError(
                f"Ollama streaming request timed out after {self._timeout}s.",
                status_code=408
            )
        except Exception as e:
            self._metrics.failed_requests += 1
            raise OllamaError(f"Streaming error: {e}")
