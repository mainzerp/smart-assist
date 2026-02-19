"""LLM module for Smart Assist."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base_client import BaseLLMClient, LLMClientError, LLMMetrics
from .openrouter_client import OpenRouterClient, OpenRouterError
from .groq_client import GroqClient, GroqError
from .ollama_client import OllamaClient, OllamaError, OllamaMetrics
from .models import ChatMessage, ChatResponse, LLMConfigurationError, LLMError, ToolCall

if TYPE_CHECKING:
    LLMClient = BaseLLMClient

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
    "OllamaClient",
    "OllamaError",
    "OllamaMetrics",
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
    api_key: str = "",
    model: str = "",
    reasoning_effort: str = "default",
    temperature: float = 0.5,
    max_tokens: int = 500,
    openrouter_provider: str = "auto",
    ollama_url: str = "http://localhost:11434",
    ollama_keep_alive: str = "-1",
    ollama_num_ctx: int = 8192,
    ollama_timeout: int = 120,
) -> OpenRouterClient | GroqClient | OllamaClient:
    """Create an LLM client based on provider selection.
    
    Args:
        provider: "openrouter", "groq", or "ollama"
        api_key: API key for cloud providers (not needed for Ollama)
        model: Model ID (e.g., 'openai/gpt-oss-120b', 'llama3.1:8b')
        reasoning_effort: Reasoning effort profile (none/default/low/medium/high)
        temperature: Sampling temperature (0-2)
        max_tokens: Maximum completion tokens
        openrouter_provider: OpenRouter routing provider (only for OpenRouter)
        ollama_url: Ollama server URL (only for Ollama)
        ollama_keep_alive: How long to keep model loaded (only for Ollama)
        ollama_num_ctx: Context window size (only for Ollama)
        ollama_timeout: Request timeout in seconds (only for Ollama)
    
    Returns:
        OpenRouterClient, GroqClient, or OllamaClient instance
    
    Raises:
        LLMConfigurationError: If configuration is invalid
    """
    if provider == "ollama":
        # Ollama doesn't need an API key
        return OllamaClient(
            base_url=ollama_url,
            model=model,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            max_tokens=max_tokens,
            keep_alive=ollama_keep_alive,
            num_ctx=ollama_num_ctx,
            timeout=ollama_timeout,
        )
    
    if not api_key:
        raise LLMConfigurationError(
            f"API key is required for {provider}. Please configure your API key."
        )
    
    if provider == "groq":
        return GroqClient(
            api_key=api_key,
            model=model,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        # Default to OpenRouter for backwards compatibility
        return OpenRouterClient(
            api_key=api_key,
            model=model,
            provider=openrouter_provider,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            max_tokens=max_tokens,
        )
