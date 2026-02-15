"""Validators and model fetching utilities for Smart Assist config flow."""

from __future__ import annotations

import json
import logging
import re

import aiohttp

from .const import (
    ALARM_EXECUTION_MODE_DIRECT_ONLY,
    DEFAULT_MODEL,
    DIRECT_ALARM_BACKEND_TIMEOUT_MAX,
    DIRECT_ALARM_BACKEND_TIMEOUT_MIN,
    OLLAMA_DEFAULT_MODEL,
    OPENROUTER_API_BASE,
)

_LOGGER = logging.getLogger(__name__)


def validate_alarm_execution_mode(value: str) -> bool:
    """Validate alarm execution mode enum."""
    return str(value or "") == ALARM_EXECUTION_MODE_DIRECT_ONLY


def validate_service_string(value: str) -> bool:
    """Validate Home Assistant service string format domain.service."""
    raw = str(value or "").strip()
    if not raw:
        return False
    return bool(re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", raw))


def validate_script_entity_id(value: str) -> bool:
    """Validate script entity id format script.<object_id>."""
    raw = str(value or "").strip()
    if not raw:
        return False
    return bool(re.fullmatch(r"script\.[a-z0-9_]+", raw))


def validate_direct_alarm_timeout(value: int) -> bool:
    """Validate direct alarm backend timeout bounds in seconds."""
    return DIRECT_ALARM_BACKEND_TIMEOUT_MIN <= int(value) <= DIRECT_ALARM_BACKEND_TIMEOUT_MAX


async def fetch_model_providers(api_key: str, model_id: str) -> list[dict[str, str]]:
    """Fetch available providers for a specific model from OpenRouter API.
    
    Uses the /api/v1/models/:author/:slug/endpoints API to get providers.
    Returns list of {"value": provider_tag, "label": display_name} dicts.
    Always includes "auto" as first option.
    
    Model variants like :free or :exacto are kept as-is since they have
    different provider availability.
    """
    _LOGGER.debug("fetch_model_providers: Starting for model %s", model_id)
    
    # Always include auto option
    providers = [{"value": "auto", "label": "Automatic (Best Price)"}]
    
    # Parse model_id to get author/slug format
    if "/" not in model_id:
        _LOGGER.warning("fetch_model_providers: Invalid model_id format: %s", model_id)
        return providers
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        url = f"{OPENROUTER_API_BASE}/models/{model_id}/endpoints"
        _LOGGER.debug("fetch_model_providers: Fetching from %s", url)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                _LOGGER.debug("fetch_model_providers: Response status %s", response.status)
                if response.status != 200:
                    _LOGGER.warning(
                        "fetch_model_providers: Failed to fetch for model %s: status %s", 
                        model_id, response.status
                    )
                    return providers
                
                data = await response.json()
                endpoints = data.get("data", {}).get("endpoints", [])
                _LOGGER.debug("fetch_model_providers: Found %d endpoints for %s", len(endpoints), model_id)
                
                if not endpoints:
                    _LOGGER.debug("fetch_model_providers: No endpoints found for model %s", model_id)
                    return providers
                
                # Extract unique providers and sort by price
                seen_providers: set[str] = set()
                for endpoint in sorted(
                    endpoints, 
                    key=lambda e: float(e.get("pricing", {}).get("prompt", "999"))
                ):
                    tag = endpoint.get("tag", "")
                    provider_name = endpoint.get("provider_name", tag)
                    quantization = endpoint.get("quantization", "")
                    
                    if tag and tag not in seen_providers:
                        seen_providers.add(tag)
                        # Add pricing info and quantization to label
                        pricing = endpoint.get("pricing", {})
                        prompt_price = pricing.get("prompt", "0")
                        try:
                            price_per_m = float(prompt_price) * 1_000_000
                            if quantization and quantization != "unknown":
                                label = f"{provider_name} ({quantization}) - ${price_per_m:.2f}/M"
                            else:
                                label = f"{provider_name} - ${price_per_m:.2f}/M"
                        except (ValueError, TypeError):
                            label = provider_name
                        
                        providers.append({"value": tag, "label": label})
                
                _LOGGER.info(
                    "fetch_model_providers: Fetched %d providers for model %s", 
                    len(providers) - 1, model_id
                )
                return providers
                
    except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError) as err:
        _LOGGER.warning("fetch_model_providers: Error for model %s: %s", model_id, err)
        return providers


async def validate_api_key(api_key: str) -> bool:
    """Validate the OpenRouter API key."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{OPENROUTER_API_BASE}/models",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                return response.status == 200
    except (aiohttp.ClientError, TimeoutError):
        return False


async def validate_groq_api_key(api_key: str) -> bool:
    """Validate the Groq API key."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.groq.com/openai/v1/models",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                return response.status == 200
    except (aiohttp.ClientError, TimeoutError):
        return False


async def validate_ollama_connection(base_url: str) -> bool:
    """Validate connection to Ollama server."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url.rstrip('/')}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                return response.status == 200
    except (aiohttp.ClientError, TimeoutError):
        return False


async def fetch_ollama_models(base_url: str) -> list[dict[str, str]]:
    """Fetch available models from Ollama server.
    
    Returns list of {"value": model_name, "label": display_name} dicts.
    Falls back to default models on error.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url.rstrip('/')}/api/tags",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    _LOGGER.warning("Failed to fetch models from Ollama: %s", response.status)
                    return _get_ollama_fallback_models()
                
                data = await response.json()
                models = data.get("models", [])
                
                if not models:
                    return _get_ollama_fallback_models()
                
                # Format for selector with size info
                model_options = []
                for model in sorted(models, key=lambda m: m.get("name", "")):
                    model_name = model.get("name", "")
                    size_bytes = model.get("size", 0)
                    size_gb = size_bytes / (1024 ** 3) if size_bytes else 0
                    
                    if size_gb > 0:
                        label = f"{model_name} ({size_gb:.1f} GB)"
                    else:
                        label = model_name
                    
                    model_options.append({"value": model_name, "label": label})
                
                _LOGGER.debug("Fetched %d models from Ollama", len(model_options))
                return model_options if model_options else _get_ollama_fallback_models()
                
    except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError) as err:
        _LOGGER.warning("Error fetching models from Ollama: %s", err)
        return _get_ollama_fallback_models()


def _get_ollama_fallback_models() -> list[dict[str, str]]:
    """Get fallback Ollama model list when server is unavailable."""
    return [
        {"value": OLLAMA_DEFAULT_MODEL, "label": f"{OLLAMA_DEFAULT_MODEL} (default)"},
        {"value": "mistral:7b", "label": "mistral:7b"},
        {"value": "qwen2.5:7b", "label": "qwen2.5:7b"},
        {"value": "llama3.2:3b", "label": "llama3.2:3b"},
    ]


async def fetch_groq_models(api_key: str) -> list[dict[str, str]]:
    """Fetch available models from Groq API.
    
    Returns list of {"value": model_id, "label": display_name} dicts.
    Falls back to default models on error.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.groq.com/openai/v1/models",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status == 401:
                    _LOGGER.debug("Groq API key not valid or not set, using fallback models")
                    return _get_groq_fallback_models()
                if response.status != 200:
                    _LOGGER.warning("Failed to fetch models from Groq: %s", response.status)
                    return _get_groq_fallback_models()
                
                data = await response.json()
                models = data.get("data", [])
                
                if not models:
                    return _get_groq_fallback_models()
                
                # Sort by model id and format for selector
                model_options = []
                for model in sorted(models, key=lambda m: m.get("id", "")):
                    model_id = model.get("id", "")
                    # Skip non-chat models (e.g., whisper, embeddings)
                    if "whisper" in model_id.lower() or "embed" in model_id.lower():
                        continue
                    label = f"{model_id}"
                    model_options.append({"value": model_id, "label": label})
                
                _LOGGER.debug("Fetched %d models from Groq", len(model_options))
                return model_options if model_options else _get_groq_fallback_models()
                
    except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError) as err:
        _LOGGER.warning("Error fetching models from Groq: %s", err)
        return _get_groq_fallback_models()


def _get_groq_fallback_models() -> list[dict[str, str]]:
    """Get fallback Groq model list when API is unavailable."""
    return [
        {"value": "llama-3.3-70b-versatile", "label": "llama-3.3-70b-versatile"},
        {"value": "openai/gpt-oss-120b", "label": "openai/gpt-oss-120b"},
        {"value": "openai/gpt-oss-20b", "label": "openai/gpt-oss-20b"},
    ]


async def fetch_openrouter_models(api_key: str) -> list[dict[str, str]]:
    """Fetch available models from OpenRouter API.
    
    Returns list of {"value": model_id, "label": display_name} dicts.
    Falls back to DEFAULT_MODEL on error.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{OPENROUTER_API_BASE}/models",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    _LOGGER.warning("Failed to fetch models from OpenRouter: %s", response.status)
                    return _get_fallback_models()
                
                data = await response.json()
                models = data.get("data", [])
                
                if not models:
                    return _get_fallback_models()
                
                # Sort by model id and format for selector
                model_options = []
                for model in sorted(models, key=lambda m: m.get("id", "")):
                    model_id = model.get("id", "")
                    name = model.get("name", model_id)
                    # Add pricing info if available
                    pricing = model.get("pricing", {})
                    prompt_price = pricing.get("prompt", "0")
                    try:
                        # Convert to dollars per million tokens
                        price_per_m = float(prompt_price) * 1_000_000
                        if price_per_m > 0:
                            label = f"{model_id} - {name} (${price_per_m:.2f}/M)"
                        else:
                            label = f"{model_id} - {name} (Free)"
                    except (ValueError, TypeError):
                        label = f"{model_id} - {name}"
                    
                    model_options.append({"value": model_id, "label": label})
                
                _LOGGER.debug("Fetched %d models from OpenRouter", len(model_options))
                return model_options
                
    except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError) as err:
        _LOGGER.warning("Error fetching models from OpenRouter: %s", err)
        return _get_fallback_models()


def _get_fallback_models() -> list[dict[str, str]]:
    """Get minimal fallback model list when API is unavailable."""
    # Only show default model - user can enter any model manually
    return [
        {"value": DEFAULT_MODEL, "label": f"{DEFAULT_MODEL} (default)"}
    ]
