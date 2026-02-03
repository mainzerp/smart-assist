"""LLM module for Smart Assist."""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

from .base_client import BaseLLMClient, LLMClientError, LLMMetrics
from .openrouter_client import OpenRouterClient, OpenRouterError
from .groq_client import GroqClient, GroqError, GroqMetrics
from .models import ChatMessage, ChatResponse, LLMConfigurationError, LLMError, ToolCall

if TYPE_CHECKING:
    LLMClient = Union[OpenRouterClient, GroqClient]

__all__ = [
    # Base classes
    "BaseLLMClient",
    "LLMClientError",
    "LLMMetrics",
    # Clients
    "OpenRouterClient",
    "OpenRouterError",
    "GroqClient",
    "GroqError",
    "GroqMetrics",
    # Models
    "ChatMessage",
    "ChatResponse",
    "LLMError",
    "LLMConfigurationError",
    "ToolCall",
    # Factory
    "create_llm_client",
]


def create_llm_client(
    provider: str,
    api_key: str,
    model: str,
    temperature: float = 0.5,
    max_tokens: int = 500,
    openrouter_provider: str = "auto",
) -> OpenRouterClient | GroqClient:
    """Create an LLM client based on provider selection.
    
    Args:
        provider: "openrouter" or "groq"
        api_key: API key for the selected provider
        model: Model ID (e.g., 'openai/gpt-oss-120b')
        temperature: Sampling temperature (0-2)
        max_tokens: Maximum completion tokens
        openrouter_provider: OpenRouter routing provider (only for OpenRouter)
    
    Returns:
        OpenRouterClient or GroqClient instance
    
    Raises:
        LLMConfigurationError: If API key is missing or invalid
    """
    if not api_key:
        raise LLMConfigurationError(
            f"API key is required for {provider}. Please configure your API key."
        )
    
    if provider == "groq":
        return GroqClient(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        # Default to OpenRouter for backwards compatibility
        return OpenRouterClient(
            api_key=api_key,
            model=model,
            provider=openrouter_provider,
            temperature=temperature,
            max_tokens=max_tokens,
        )
