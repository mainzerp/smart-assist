"""Constants for Smart Assist integration."""

from typing import Final

# Integration domain
DOMAIN: Final = "smart_assist"

# Configuration keys
CONF_API_KEY: Final = "api_key"
CONF_GROQ_API_KEY: Final = "groq_api_key"
CONF_LLM_PROVIDER: Final = "llm_provider"  # "openrouter" or "groq"
CONF_MODEL: Final = "model"
CONF_PROVIDER: Final = "provider"  # OpenRouter routing provider (auto, anthropic, etc.)
CONF_TEMPERATURE: Final = "temperature"
CONF_MAX_TOKENS: Final = "max_tokens"
CONF_LANGUAGE: Final = "language"
CONF_EXPOSED_ONLY: Final = "exposed_only"
CONF_CONFIRM_CRITICAL: Final = "confirm_critical"
CONF_MAX_HISTORY: Final = "max_history"
CONF_ENABLE_WEB_SEARCH: Final = "enable_web_search"
CONF_ENABLE_QUICK_ACTIONS: Final = "enable_quick_actions"
CONF_ENABLE_PROMPT_CACHING: Final = "enable_prompt_caching"
CONF_CACHE_TTL_EXTENDED: Final = "cache_ttl_extended"
CONF_ENABLE_CACHE_WARMING: Final = "enable_cache_warming"
CONF_CACHE_REFRESH_INTERVAL: Final = "cache_refresh_interval"
CONF_CLEAN_RESPONSES: Final = "clean_responses"
CONF_ASK_FOLLOWUP: Final = "ask_followup"
CONF_USER_SYSTEM_PROMPT: Final = "user_system_prompt"
CONF_TASK_SYSTEM_PROMPT: Final = "task_system_prompt"
CONF_TASK_ENABLE_PROMPT_CACHING: Final = "task_enable_prompt_caching"
CONF_TASK_ENABLE_CACHE_WARMING: Final = "task_enable_cache_warming"
CONF_DEBUG_LOGGING: Final = "debug_logging"
CONF_CALENDAR_CONTEXT: Final = "calendar_context"

# Default values
DEFAULT_MODEL: Final = "openai/gpt-oss-120b"
DEFAULT_PROVIDER: Final = "groq"
DEFAULT_LLM_PROVIDER: Final = "openrouter"  # Use OpenRouter by default for backwards compatibility
DEFAULT_TEMPERATURE: Final = 0.5
DEFAULT_MAX_TOKENS: Final = 500
DEFAULT_MAX_HISTORY: Final = 10
DEFAULT_EXPOSED_ONLY: Final = True
DEFAULT_CONFIRM_CRITICAL: Final = True
DEFAULT_CACHE_TTL_EXTENDED: Final = False
DEFAULT_ENABLE_CACHE_WARMING: Final = False  # Disabled by default (costs extra)
DEFAULT_CACHE_REFRESH_INTERVAL: Final = 4  # Minutes
DEFAULT_CLEAN_RESPONSES: Final = False  # Disabled by default (preserves original response)
DEFAULT_ASK_FOLLOWUP: Final = True  # Enabled by default
DEFAULT_USER_SYSTEM_PROMPT: Final = "You are Smart Assist, a friendly and intelligent smart home assistant. You help users control their home devices, answer questions about their environment, and provide useful information. Be conversational yet concise."
DEFAULT_TASK_SYSTEM_PROMPT: Final = "You are a smart home task executor. Complete tasks efficiently and provide structured output."
DEFAULT_TASK_ENABLE_PROMPT_CACHING: Final = False  # Tasks are not time-critical
DEFAULT_TASK_ENABLE_CACHE_WARMING: Final = False   # Tasks are not time-critical
DEFAULT_DEBUG_LOGGING: Final = False  # Disabled by default
DEFAULT_CALENDAR_CONTEXT: Final = False  # Disabled by default (token cost)

# Common Home Assistant locale to language name mapping for auto-detection
# Used when language is empty/auto to show a readable language name in prompts
# Format: locale prefix -> (English name, native name)
LOCALE_TO_LANGUAGE: Final = {
    "de": ("German", "Deutsch"),
    "en": ("English", "English"),
    "fr": ("French", "Francais"),
    "es": ("Spanish", "Espanol"),
    "it": ("Italian", "Italiano"),
    "nl": ("Dutch", "Nederlands"),
    "pt": ("Portuguese", "Portugues"),
    "pl": ("Polish", "Polski"),
    "ru": ("Russian", "Russkij"),
    "uk": ("Ukrainian", "Ukrajinska"),
    "cs": ("Czech", "Cestina"),
    "sk": ("Slovak", "Slovencina"),
    "hu": ("Hungarian", "Magyar"),
    "sv": ("Swedish", "Svenska"),
    "no": ("Norwegian", "Norsk"),
    "da": ("Danish", "Dansk"),
    "fi": ("Finnish", "Suomi"),
    "ja": ("Japanese", "Nihongo"),
    "ko": ("Korean", "Hangugeo"),
    "zh": ("Chinese", "Zhongwen"),
}

# OpenRouter API
OPENROUTER_API_URL: Final = "https://openrouter.ai/api/v1/chat/completions"

# Groq API (direct)
GROQ_API_URL: Final = "https://api.groq.com/openai/v1/chat/completions"

# LLM API Configuration
LLM_MAX_RETRIES: Final = 3
LLM_RETRY_BASE_DELAY: Final = 1.0  # seconds
LLM_RETRY_MAX_DELAY: Final = 10.0  # seconds
LLM_STREAM_CHUNK_TIMEOUT: Final = 30.0  # seconds
LLM_RETRIABLE_STATUS_CODES: Final = frozenset({429, 500, 502, 503, 504})

# LLM Provider types
LLM_PROVIDER_OPENROUTER: Final = "openrouter"
LLM_PROVIDER_GROQ: Final = "groq"
LLM_PROVIDERS: Final = {
    LLM_PROVIDER_OPENROUTER: "OpenRouter (All Models)",
    LLM_PROVIDER_GROQ: "Groq (Direct, Ultra Fast)",
}

# Model prefixes that support prompt caching
# Used for automatic detection - user can use any model with these prefixes
# Anthropic: requires cache_control breakpoints
# OpenAI/Gemini/Groq: automatic caching
PROMPT_CACHING_PREFIXES: Final = {
    "anthropic/",
    "openai/",
    "google/",
    "groq/",
}

# Provider-specific prompt caching support
# Maps model prefix to providers that support caching
# See: https://openrouter.ai/docs/prompt-caching
PROVIDER_CACHING_SUPPORT: Final = {
    "anthropic/": {
        "anthropic": True,      # Native Anthropic - explicit cache_control required
        "aws-bedrock": True,    # AWS Bedrock supports caching for Claude
        "google-vertex": False, # Vertex Claude - no caching
    },
    "openai/": {
        "openai": True,         # Native OpenAI - automatic caching
        "azure": True,          # Azure OpenAI - automatic caching
    },
    "google/": {
        "google": True,         # Native Google - automatic/implicit caching
        "google-vertex": True,  # Vertex AI - same as native
    },
    "groq/": {
        "groq": True,           # Groq - automatic caching (no discount, Kimi K2 only)
    },
}

# Provider display names for UI
PROVIDERS: Final = {
    "auto": "Automatic (Best Price)",
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI",
    "azure": "Azure OpenAI",
    "google": "Google AI",
    "google-vertex": "Google Vertex AI",
    "aws-bedrock": "AWS Bedrock",
    "groq": "Groq (Ultra Fast)",
    "together": "Together AI",
    "fireworks": "Fireworks AI",
    "deepinfra": "DeepInfra",
}

# Cache TTLs (seconds)
CACHE_TTL_ENTITY_STATE: Final = 5
CACHE_TTL_ENTITY_LIST: Final = 60
CACHE_TTL_AREA_ROOM: Final = 300

# Critical action domains (require confirmation)
CRITICAL_DOMAINS: Final = {
    "lock",
    "alarm_control_panel",
    "cover",  # Garage doors
}

# Supported entity domains
SUPPORTED_DOMAINS: Final = {
    "light",
    "switch",
    "climate",
    "cover",
    "fan",
    "media_player",
    "scene",
    "script",
    "automation",
    "lock",
    "alarm_control_panel",
    "sensor",
    "binary_sensor",
    "weather",
    "vacuum",
    "camera",
    "calendar",
}

# Technical system prompt (not user-editable)
TECHNICAL_SYSTEM_PROMPT: Final = """You are a Home Assistant smart home controller. Be concise and helpful.

## Response Rules
- Confirm actions taken briefly
- End responses with "Anything else?" for follow-up
- If uncertain about entity, ask for clarification
- Never assume entity states - use tools to check

## Entity Lookup Strategy
1. FIRST: Check the ENTITY INDEX (if provided) to find entity_ids
2. ONLY if entity not found in index: Use get_entities tool with domain filter
3. Use get_entity_state to check current state before taking action

## Entity Control
- Use the 'control' tool for all entity types (lights, climate, covers, media, scripts)
- Domain is auto-detected from entity_id (e.g., light.living_room -> light domain)
- Use action appropriate to domain (turn_on/off for all, brightness for lights, etc.)

## Error Handling
- If an action fails, explain why and suggest alternatives
- If entity not found, suggest similar entities from the index
"""


def supports_prompt_caching(model_id: str) -> bool:
    """Check if a model supports prompt caching based on its prefix."""
    for prefix in PROMPT_CACHING_PREFIXES:
        if model_id.startswith(prefix):
            return True
    return False


def get_caching_provider_info(model_id: str) -> dict[str, bool] | None:
    """Get provider caching info for a model.
    
    Returns dict of provider -> supports_caching, or None if unknown.
    """
    for prefix, providers in PROVIDER_CACHING_SUPPORT.items():
        if model_id.startswith(prefix):
            return providers
    return None
