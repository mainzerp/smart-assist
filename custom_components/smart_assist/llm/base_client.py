"""Base LLM client interface for Smart Assist.

This module defines the abstract base class for all LLM clients,
providing common functionality for session management, retry logic,
and metrics tracking.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, TYPE_CHECKING

import aiohttp

from ..const import (
    LLM_MAX_RETRIES,
    LLM_RETRIABLE_STATUS_CODES,
    LLM_RETRY_BASE_DELAY,
    LLM_RETRY_MAX_DELAY,
)
from ..utils import sanitize_user_facing_error
from .models import LLMError

if TYPE_CHECKING:
    from .models import ChatMessage, ChatResponse

_LOGGER = logging.getLogger(__name__)


@dataclass
class LLMMetrics:
    """Metrics for LLM API calls.
    
    Tracks request counts, token usage, response times, and caching statistics.
    Used by both OpenRouter and Groq clients.
    """
    
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
    empty_responses: int = 0
    stream_timeouts: int = 0
    # Per-request tracking (last request only, not persisted)
    _last_prompt_tokens: int = 0
    _last_completion_tokens: int = 0
    _last_cached_tokens: int = 0
    
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
            "empty_responses": self.empty_responses,
            "stream_timeouts": self.stream_timeouts,
        }


class LLMClientError(LLMError):
    """Base exception for LLM client errors."""
    pass


class BaseLLMClient(ABC):
    """Abstract base class for LLM API clients.
    
    Provides common functionality:
    - Thread-safe session management with optional aging
    - Exponential backoff retry logic
    - Metrics tracking
    - Async context manager support
    
    Subclasses must implement:
    - _get_api_url(): Return the API endpoint URL
    - _get_session_headers(): Return headers for the session
    - chat(): Non-streaming chat completion
    - chat_stream(): Streaming chat completion
    """
    
    # Session max age in seconds (override in subclass if needed)
    SESSION_MAX_AGE_SECONDS: int | None = None
    
    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        temperature: float = 0.5,
        max_tokens: int = 500,
    ) -> None:
        """Initialize the LLM client.
        
        Args:
            api_key: API key for authentication
            model: Model identifier
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum completion tokens
        """
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._max_tokens = int(max_tokens)
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()
        self._session_created_at: float | None = None
        self._metrics = LLMMetrics()
    
    @abstractmethod
    def _get_api_url(self) -> str:
        """Return the API endpoint URL."""
        pass
    
    @abstractmethod
    def _get_session_headers(self) -> dict[str, str]:
        """Return headers for the HTTP session."""
        pass
    
    def _get_session_timeout(self) -> aiohttp.ClientTimeout:
        """Return timeout configuration for the HTTP session.
        
        Override in subclasses for custom timeout behavior.
        """
        return aiohttp.ClientTimeout(total=60)

    @property
    def supports_native_structured_output(self) -> bool:
        """Whether this provider/client can send native structured-output hints."""
        return False
    
    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        use_native_structured_output: bool = False,
        **kwargs: Any,
    ) -> ChatResponse:
        """Send a non-streaming chat completion request."""
        pass
    
    @abstractmethod
    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        use_native_structured_output: bool = False,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Send a streaming chat completion request."""
        pass
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session (thread-safe).
        
        Sessions are renewed if:
        - None or closed
        - Older than SESSION_MAX_AGE_SECONDS (if set)
        """
        async with self._session_lock:
            now = time.monotonic()
            session_expired = (
                self.SESSION_MAX_AGE_SECONDS is not None
                and self._session_created_at is not None
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
                    headers=self._get_session_headers(),
                    timeout=self._get_session_timeout(),
                )
                self._session_created_at = now
                if session_expired:
                    _LOGGER.debug("Created new session (previous expired)")
        
        return self._session
    
    async def _execute_with_retry(
        self,
        session: aiohttp.ClientSession,
        payload: dict[str, Any],
    ) -> aiohttp.ClientResponse:
        """Execute API request with exponential backoff retry.
        
        Args:
            session: aiohttp session
            payload: Request payload
            
        Returns:
            aiohttp.ClientResponse
            
        Raises:
            LLMClientError: If all retries fail
        """
        last_error: Exception | None = None
        api_url = self._get_api_url()
        
        for attempt in range(LLM_MAX_RETRIES):
            try:
                response = await session.post(api_url, json=payload)
                
                # Success or non-retriable error
                if response.status == 200 or response.status not in LLM_RETRIABLE_STATUS_CODES:
                    return response
                
                # Retriable error - close response and retry
                error_text = await response.text()
                response.close()
                last_error = LLMClientError(
                    sanitize_user_facing_error(
                        f"API error: {response.status} - {error_text}",
                        fallback=f"API error: {response.status}",
                    ),
                    response.status,
                )
                
                if attempt < LLM_MAX_RETRIES - 1:
                    delay = min(LLM_RETRY_BASE_DELAY * (2 ** attempt), LLM_RETRY_MAX_DELAY)
                    _LOGGER.warning(
                        "API error (attempt %d/%d): %s. Retrying in %.1fs",
                        attempt + 1, LLM_MAX_RETRIES, response.status, delay
                    )
                    self._metrics.total_retries += 1
                    await asyncio.sleep(delay)
                    
            except aiohttp.ClientError as err:
                last_error = LLMClientError(
                    sanitize_user_facing_error(err, fallback="Network error")
                )
                if attempt < LLM_MAX_RETRIES - 1:
                    delay = min(LLM_RETRY_BASE_DELAY * (2 ** attempt), LLM_RETRY_MAX_DELAY)
                    _LOGGER.warning(
                        "Network error (attempt %d/%d): %s. Retrying in %.1fs",
                        attempt + 1, LLM_MAX_RETRIES, err, delay
                    )
                    self._metrics.total_retries += 1
                    await asyncio.sleep(delay)
            
            except asyncio.TimeoutError as err:
                last_error = LLMClientError(
                    sanitize_user_facing_error(err, fallback="Request timeout")
                )
                if attempt < LLM_MAX_RETRIES - 1:
                    delay = min(LLM_RETRY_BASE_DELAY * (2 ** attempt), LLM_RETRY_MAX_DELAY)
                    _LOGGER.warning(
                        "Timeout (attempt %d/%d). Retrying in %.1fs",
                        attempt + 1, LLM_MAX_RETRIES, delay
                    )
                    self._metrics.total_retries += 1
                    await asyncio.sleep(delay)
        
        # All retries exhausted
        self._metrics.failed_requests += 1
        raise last_error or LLMClientError("Unknown error after retries")
    
    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def __aenter__(self) -> "BaseLLMClient":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - ensures session cleanup."""
        await self.close()
    
    @property
    def metrics(self) -> LLMMetrics:
        """Get current metrics."""
        return self._metrics
    
    def reset_metrics(self) -> None:
        """Reset all metrics to zero."""
        self._metrics = LLMMetrics()
    
    @property
    def model(self) -> str:
        """Get the model identifier."""
        return self._model
    
    @property
    def temperature(self) -> float:
        """Get the temperature setting."""
        return self._temperature
    
    @property
    def max_tokens(self) -> int:
        """Get the max tokens setting."""
        return self._max_tokens
