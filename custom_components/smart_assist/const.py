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
CONF_REASONING_EFFORT: Final = "reasoning_effort"
CONF_TEMPERATURE: Final = "temperature"
CONF_MAX_TOKENS: Final = "max_tokens"
CONF_LANGUAGE: Final = "language"
CONF_EXPOSED_ONLY: Final = "exposed_only"
CONF_CONFIRM_CRITICAL: Final = "confirm_critical"
CONF_TOOL_MAX_RETRIES: Final = "tool_max_retries"
CONF_TOOL_LATENCY_BUDGET_MS: Final = "tool_latency_budget_ms"
CONF_TOOL_MAX_ITERATIONS: Final = "tool_max_iterations"
CONF_MAX_HISTORY: Final = "max_history"
CONF_ENABLE_WEB_SEARCH: Final = "enable_web_search"
CONF_ENABLE_QUICK_ACTIONS: Final = "enable_quick_actions"
CONF_CACHE_TTL_EXTENDED: Final = "cache_ttl_extended"
CONF_ENABLE_CACHE_WARMING: Final = "enable_cache_warming"
CONF_CACHE_REFRESH_INTERVAL: Final = "cache_refresh_interval"
CONF_CLEAN_RESPONSES: Final = "clean_responses"
CONF_ASK_FOLLOWUP: Final = "ask_followup"
CONF_USER_SYSTEM_PROMPT: Final = "user_system_prompt"
CONF_TASK_SYSTEM_PROMPT: Final = "task_system_prompt"
CONF_TASK_ENABLE_PROMPT_CACHING: Final = "task_enable_prompt_caching"
CONF_TASK_ENABLE_CACHE_WARMING: Final = "task_enable_cache_warming"
CONF_TASK_ALLOW_CONTROL: Final = "task_allow_control"
CONF_TASK_ALLOW_LOCK_CONTROL: Final = "task_allow_lock_control"
CONF_DEBUG_LOGGING: Final = "debug_logging"
CONF_ENABLE_CANCEL_HANDLER: Final = "enable_cancel_handler"
CONF_CANCEL_INTENT_AGENT: Final = "cancel_intent_agent"
CONF_CALENDAR_CONTEXT: Final = "calendar_context"

# Calendar user filtering
CALENDAR_SHARED_MARKER: Final = "shared"

# Entity discovery mode
CONF_ENTITY_DISCOVERY_MODE: Final = "entity_discovery_mode"

# Memory configuration keys
CONF_ENABLE_MEMORY: Final = "enable_memory"
CONF_ENABLE_AGENT_MEMORY: Final = "enable_agent_memory"
CONF_USER_MAPPINGS: Final = "user_mappings"
CONF_ENABLE_PRESENCE_HEURISTIC: Final = "enable_presence_heuristic"

# Ollama configuration keys
CONF_OLLAMA_URL: Final = "ollama_url"
CONF_OLLAMA_MODEL: Final = "ollama_model"
CONF_OLLAMA_KEEP_ALIVE: Final = "ollama_keep_alive"
CONF_OLLAMA_NUM_CTX: Final = "ollama_num_ctx"
CONF_OLLAMA_TIMEOUT: Final = "ollama_timeout"

# Default values
DEFAULT_MODEL: Final = "openai/gpt-oss-120b"
DEFAULT_PROVIDER: Final = "groq"
DEFAULT_REASONING_EFFORT: Final = "default"
REASONING_EFFORT_OPTIONS: Final = ["none", "default", "low", "medium", "high"]
DEFAULT_LLM_PROVIDER: Final = "openrouter"  # Use OpenRouter by default for backwards compatibility
DEFAULT_TEMPERATURE: Final = 0.5
DEFAULT_MAX_TOKENS: Final = 500
DEFAULT_MAX_HISTORY: Final = 10
DEFAULT_EXPOSED_ONLY: Final = True
DEFAULT_CONFIRM_CRITICAL: Final = True
DEFAULT_TOOL_MAX_RETRIES: Final = 1
DEFAULT_TOOL_LATENCY_BUDGET_MS: Final = 8000
DEFAULT_TOOL_MAX_ITERATIONS: Final = 10
TOOL_MAX_RETRIES_MIN: Final = 0
TOOL_MAX_RETRIES_MAX: Final = 5
TOOL_LATENCY_BUDGET_MS_MIN: Final = 1000
TOOL_LATENCY_BUDGET_MS_MAX: Final = 30000
TOOL_MAX_ITERATIONS_MIN: Final = 1
TOOL_MAX_ITERATIONS_MAX: Final = 20
DEFAULT_CACHE_TTL_EXTENDED: Final = False
DEFAULT_ENABLE_CACHE_WARMING: Final = False  # Disabled by default (costs extra)
DEFAULT_CACHE_REFRESH_INTERVAL: Final = 4  # Minutes
DEFAULT_CLEAN_RESPONSES: Final = False  # Disabled by default (preserves original response)
DEFAULT_ASK_FOLLOWUP: Final = True  # Enabled by default
MAX_CONSECUTIVE_FOLLOWUPS: Final = 3  # Max follow-up questions before aborting (prevents loops)
DEFAULT_USER_SYSTEM_PROMPT: Final = "You are Smart Assist, a friendly and intelligent smart home assistant. You help users control their home devices, answer questions about their environment, and provide useful information. Be conversational yet concise."
DEFAULT_TASK_SYSTEM_PROMPT: Final = "You are a smart home task executor. Complete tasks efficiently and provide structured output."
DEFAULT_TASK_ENABLE_PROMPT_CACHING: Final = False  # Tasks are not time-critical
DEFAULT_TASK_ENABLE_CACHE_WARMING: Final = False   # Tasks are not time-critical
DEFAULT_TASK_ALLOW_CONTROL: Final = False  # Explicit opt-in required for control tool use
DEFAULT_TASK_ALLOW_LOCK_CONTROL: Final = False  # Separate explicit opt-in for lock domain control
TASK_STRUCTURED_OUTPUT_INVALID_JSON_EN: Final = "Sorry, I could not generate valid structured output for this task."
TASK_STRUCTURED_OUTPUT_INVALID_JSON_DE: Final = "Entschuldigung, ich konnte keine gueltige strukturierte Ausgabe fuer diese Aufgabe erzeugen."
TASK_STRUCTURED_OUTPUT_SCHEMA_MISMATCH_EN: Final = "Sorry, the structured result did not match the required format."
TASK_STRUCTURED_OUTPUT_SCHEMA_MISMATCH_DE: Final = "Entschuldigung, das strukturierte Ergebnis entspricht nicht dem erforderlichen Format."

# Conversation engine constants
TTS_STREAM_MIN_CHARS: Final = 65  # Minimum chars to trigger TTS streaming in Companion App
MAX_TOOL_ITERATIONS: Final = 10  # Max LLM-tool execution loops per request
MALFORMED_TOOL_RECOVERY_MAX_RETRIES: Final = 1  # Bounded correction retries for malformed tool args
MISSING_TOOL_ROUTE_RECOVERY_MAX_RETRIES: Final = 1  # Bounded retries for no-tool when tool route is expected
SESSION_MAX_MESSAGES: Final = 20  # Max messages per conversation session
SESSION_RECENT_ENTITIES_MAX: Final = 5  # Max recent entities for pronoun resolution
SESSION_EXPIRY_MINUTES: Final = 30  # Session timeout in minutes
DEFAULT_DEBUG_LOGGING: Final = False  # Disabled by default
DEFAULT_ENABLE_CANCEL_HANDLER: Final = True  # Enabled by default (fixes satellite hang)
DEFAULT_CANCEL_INTENT_AGENT: Final = False  # Per-subentry: not the cancel handler by default
DEFAULT_CALENDAR_CONTEXT: Final = False  # Disabled by default (token cost)
DEFAULT_ENTITY_DISCOVERY_MODE: Final = "full_index"  # Full entity index in prompt
DEFAULT_ENABLE_MEMORY: Final = False  # Disabled by default
DEFAULT_ENABLE_AGENT_MEMORY: Final = True  # Enabled by default when memory is active
DEFAULT_ENABLE_PRESENCE_HEURISTIC: Final = False  # Disabled by default

# Request history storage constants
REQUEST_HISTORY_STORAGE_KEY: Final = "smart_assist_request_history"
REQUEST_HISTORY_STORAGE_VERSION: Final = 1
REQUEST_HISTORY_MAX_ENTRIES: Final = 500
REQUEST_HISTORY_INPUT_MAX_LENGTH: Final = 200
REQUEST_HISTORY_RESPONSE_MAX_LENGTH: Final = 300
REQUEST_HISTORY_TOOL_ARGS_MAX_LENGTH: Final = 100
CONF_ENABLE_REQUEST_HISTORY_CONTENT: Final = "enable_request_history_content"
CONF_HISTORY_RETENTION_DAYS: Final = "history_retention_days"
CONF_HISTORY_REDACT_PATTERNS: Final = "history_redact_patterns"
DEFAULT_ENABLE_REQUEST_HISTORY_CONTENT: Final = True
DEFAULT_HISTORY_RETENTION_DAYS: Final = 30
DEFAULT_HISTORY_REDACT_PATTERNS: Final = ""
HISTORY_REDACTION_MAX_PATTERNS: Final = 20
HISTORY_REDACTION_MAX_PATTERN_LENGTH: Final = 120
HISTORY_REDACTION_MAX_REGEX_TEXT_LENGTH: Final = 4000

# Memory storage constants
MEMORY_STORAGE_KEY: Final = "smart_assist_memory"
MEMORY_STORAGE_VERSION: Final = 1
MEMORY_MAX_PER_USER: Final = 100
MEMORY_MAX_GLOBAL: Final = 50
MEMORY_MAX_AGENT: Final = 50  # Max agent-level memories
MEMORY_AGENT_EXPIRE_DAYS: Final = 30  # Auto-expire agent memories older than this with low access
MEMORY_MAX_CONTENT_LENGTH: Final = 100
MEMORY_MAX_INJECTION: Final = 20  # Max memories injected per request
MEMORY_MAX_AGENT_INJECTION: Final = 15  # Max agent memories injected per request
MEMORY_DEFAULT_USER: Final = "default"
MEMORY_AGENT_USER_ID: Final = "_agent"  # Reserved user ID for agent memory

# Persistent alarm storage constants
PERSISTENT_ALARM_STORAGE_KEY: Final = "smart_assist_persistent_alarms"
PERSISTENT_ALARM_STORAGE_VERSION: Final = 3
PERSISTENT_ALARM_EVENT_FIRED: Final = "smart_assist_alarm_fired"
PERSISTENT_ALARM_EVENT_UPDATED: Final = "smart_assist_alarm_updated"
POST_FIRE_SNOOZE_CONTEXT_WINDOW_MINUTES: Final = 5

# Alarm execution settings
CONF_ALARM_EXECUTION_MODE: Final = "alarm_execution_mode"
CONF_DIRECT_ALARM_ENABLE_NOTIFICATION: Final = "direct_alarm_enable_notification"
CONF_DIRECT_ALARM_ENABLE_NOTIFY: Final = "direct_alarm_enable_notify"
CONF_DIRECT_ALARM_ENABLE_TTS: Final = "direct_alarm_enable_tts"
CONF_DIRECT_ALARM_ENABLE_SCRIPT: Final = "direct_alarm_enable_script"
CONF_DIRECT_ALARM_NOTIFY_SERVICE: Final = "direct_alarm_notify_service"
CONF_DIRECT_ALARM_TTS_SERVICE: Final = "direct_alarm_tts_service"
CONF_DIRECT_ALARM_TTS_TARGET: Final = "direct_alarm_tts_target"
CONF_DIRECT_ALARM_SCRIPT_ENTITY_ID: Final = "direct_alarm_script_entity_id"
CONF_DIRECT_ALARM_BACKEND_TIMEOUT_SECONDS: Final = "direct_alarm_backend_timeout_seconds"
ALARM_EXECUTION_MODE_DIRECT_ONLY: Final = "direct_only"
DEFAULT_ALARM_EXECUTION_MODE: Final = ALARM_EXECUTION_MODE_DIRECT_ONLY
DEFAULT_DIRECT_ALARM_ENABLE_NOTIFICATION: Final = True
DEFAULT_DIRECT_ALARM_ENABLE_NOTIFY: Final = False
DEFAULT_DIRECT_ALARM_ENABLE_TTS: Final = True
DEFAULT_DIRECT_ALARM_ENABLE_SCRIPT: Final = False
DEFAULT_DIRECT_ALARM_NOTIFY_SERVICE: Final = "notify.notify"
DEFAULT_DIRECT_ALARM_TTS_SERVICE: Final = "tts.speak"
DEFAULT_DIRECT_ALARM_TTS_TARGET: Final = ""
DEFAULT_DIRECT_ALARM_SCRIPT_ENTITY_ID: Final = ""
DEFAULT_DIRECT_ALARM_BACKEND_TIMEOUT_SECONDS: Final = 8
DIRECT_ALARM_BACKEND_TIMEOUT_MIN: Final = 1
DIRECT_ALARM_BACKEND_TIMEOUT_MAX: Final = 30

# Direct alarm execution states/backends/errors
DIRECT_ALARM_STATE_OK: Final = "ok"
DIRECT_ALARM_STATE_PARTIAL: Final = "partial"
DIRECT_ALARM_STATE_FAILED: Final = "failed"
DIRECT_ALARM_STATE_SKIPPED: Final = "skipped"
DIRECT_ALARM_BACKEND_NOTIFICATION: Final = "notification"
DIRECT_ALARM_BACKEND_NOTIFY: Final = "notify"
DIRECT_ALARM_BACKEND_TTS: Final = "tts"
DIRECT_ALARM_BACKEND_SCRIPT: Final = "script"
DIRECT_ALARM_ERROR_UNSUPPORTED: Final = "unsupported"
DIRECT_ALARM_ERROR_VALIDATION: Final = "validation_error"
DIRECT_ALARM_ERROR_SERVICE_FAILED: Final = "service_call_failed"
DIRECT_ALARM_ERROR_TIMEOUT: Final = "timeout"

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
OPENROUTER_API_BASE: Final = "https://openrouter.ai/api/v1"
OPENROUTER_API_URL: Final = f"{OPENROUTER_API_BASE}/chat/completions"

# Groq API (direct)
GROQ_API_BASE: Final = "https://api.groq.com/openai/v1"
GROQ_API_URL: Final = f"{GROQ_API_BASE}/chat/completions"

# Ollama API (local)
OLLAMA_DEFAULT_URL: Final = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL: Final = "llama3.1:8b"
OLLAMA_DEFAULT_KEEP_ALIVE: Final = "-1"  # Keep model loaded indefinitely
OLLAMA_DEFAULT_NUM_CTX: Final = 8192  # Context window size
OLLAMA_DEFAULT_TIMEOUT: Final = 120  # Seconds (local inference can be slow)

# LLM API Configuration
LLM_MAX_RETRIES: Final = 3
LLM_RETRY_BASE_DELAY: Final = 1.0  # seconds
LLM_RETRY_MAX_DELAY: Final = 10.0  # seconds
LLM_STREAM_CHUNK_TIMEOUT: Final = 30.0  # seconds
LLM_RETRIABLE_STATUS_CODES: Final = frozenset({429, 500, 502, 503, 504})

# LLM Provider types
LLM_PROVIDER_OPENROUTER: Final = "openrouter"
LLM_PROVIDER_GROQ: Final = "groq"
LLM_PROVIDER_OLLAMA: Final = "ollama"
LLM_PROVIDERS: Final = {
    LLM_PROVIDER_OPENROUTER: "OpenRouter",
    LLM_PROVIDER_GROQ: "Groq",
    LLM_PROVIDER_OLLAMA: "Ollama",
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
