"""Utility functions for Smart Assist integration."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Final, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry, ConfigSubentry
    from .llm.models import ChatMessage, ToolCall
    from .tools.base import ToolRegistry

_LOGGER = logging.getLogger(__name__)


def _is_german(language: str) -> bool:
    """Check if the language is German.
    
    Safely detects German without false positives from words like
    'undefined', 'modern', 'decoder'.
    
    Args:
        language: Language code or name string
        
    Returns:
        True if the language is German
    """
    lang = language.lower().strip()
    return lang in ("de", "deutsch", "german") or lang.startswith("de-") or lang.startswith("de_")


def get_config_value(
    source: ConfigEntry | ConfigSubentry | dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    """Get config value from entry, subentry, or dict.
    
    For ConfigEntry: checks options first, then data, then default.
    For ConfigSubentry/dict: checks data/dict directly, then default.
    
    Args:
        source: ConfigEntry, ConfigSubentry, or dict to read from
        key: Configuration key to look up
        default: Default value if key not found
    
    Returns:
        The configuration value or default
    """
    if hasattr(source, "options") and hasattr(source, "data"):
        # ConfigEntry: check options first (user overrides)
        if key in source.options:
            return source.options[key]
        return source.data.get(key, default)
    elif hasattr(source, "data"):
        # ConfigSubentry: check data
        return source.data.get(key, default)
    elif isinstance(source, dict):
        # Plain dict
        return source.get(key, default)
    return default

# Logger names for Smart Assist modules
SMART_ASSIST_LOGGERS: Final = (
    "custom_components.smart_assist",
    "custom_components.smart_assist.conversation",
    "custom_components.smart_assist.config_flow",
    "custom_components.smart_assist.llm",
    "custom_components.smart_assist.llm.client",
    "custom_components.smart_assist.llm.tools",
    "custom_components.smart_assist.sensor",
)


def apply_debug_logging(enabled: bool) -> None:
    """Apply debug logging setting to all Smart Assist loggers.
    
    Args:
        enabled: True to enable DEBUG level, False for INFO level
    """
    level = logging.DEBUG if enabled else logging.INFO
    
    for logger_name in SMART_ASSIST_LOGGERS:
        logging.getLogger(logger_name).setLevel(level)
    
    _LOGGER.info("Smart Assist debug logging %s", "enabled" if enabled else "disabled")

# Emoji pattern - covers most common emoji ranges
EMOJI_PATTERN: Final = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols & pictographs extended-A
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002300-\U000023FF"  # misc technical
    "]+",
    flags=re.UNICODE,
)

# Reasoning/thinking block pattern - used by DeepSeek-R1, QwQ, and other 
# Chain-of-Thought reasoning models that output their thinking process
# Matches <think>...</think> blocks including nested content and newlines
THINKING_BLOCK_PATTERN: Final = re.compile(
    r"<think>[\s\S]*?</think>",
    flags=re.IGNORECASE,
)

# URL pattern
URL_PATTERN: Final = re.compile(
    r"https?://[^\s\)\]\>]+|www\.[^\s\)\]\>]+",
    flags=re.IGNORECASE,
)

RAW_ERROR_PATTERNS: Final = [
    re.compile(r"\{\s*\"error\"[\s\S]*\}\s*$", flags=re.IGNORECASE),
    re.compile(r"\[[\s\S]*\]\s*$", flags=re.IGNORECASE),
    re.compile(r"traceback[\s\S]*", flags=re.IGNORECASE),
    re.compile(r"request id[:=]\s*[a-z0-9_-]+", flags=re.IGNORECASE),
]

# Markdown patterns
MARKDOWN_PATTERNS: Final = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),  # **bold**
    (re.compile(r"\*(.+?)\*"), r"\1"),      # *italic*
    (re.compile(r"__(.+?)__"), r"\1"),      # __bold__
    (re.compile(r"_(.+?)_"), r"\1"),        # _italic_
    (re.compile(r"~~(.+?)~~"), r"\1"),      # ~~strikethrough~~
    (re.compile(r"`(.+?)`"), r"\1"),        # `code`
    (re.compile(r"```[\s\S]*?```"), ""),    # ```code blocks```
    (re.compile(r"\[([^\]]+)\]\([^\)]+\)"), r"\1"),  # [text](url) -> text
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),   # # headers
    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), ""), # - bullet points
    (re.compile(r"^\s*\d+\.\s+", re.MULTILINE), ""), # 1. numbered lists
]

# Symbol to word mappings (for TTS)
SYMBOL_MAPPINGS: Final = {
    # Temperature
    "°C": " degrees Celsius",
    "°F": " degrees Fahrenheit",
    "°": " degrees",
    # Percentage
    "%": " percent",
    # Currency
    "$": " dollars",
    "€": " euros",
    "£": " pounds",
    # Math
    "+": " plus ",
    "=": " equals ",
    "×": " times ",
    "÷": " divided by ",
    # Common symbols
    "&": " and ",
    "@": " at ",
    "#": " number ",
    # Arrows
    "→": " to ",
    "←": " from ",
    "↑": " up ",
    "↓": " down ",
    # Comparison
    ">=": " greater than or equal to ",
    "<=": " less than or equal to ",
    ">": " greater than ",
    "<": " less than ",
}

# Language-specific symbol mappings
SYMBOL_MAPPINGS_DE: Final = {
    "°C": " Grad Celsius",
    "°F": " Grad Fahrenheit",
    "°": " Grad",
    "%": " Prozent",
    "$": " Dollar",
    "€": " Euro",
    "£": " Pfund",
    "+": " plus ",
    "=": " gleich ",
    "×": " mal ",
    "÷": " geteilt durch ",
    "&": " und ",
    "@": " at ",
    "#": " Nummer ",
    "→": " nach ",
    "←": " von ",
    "↑": " hoch ",
    "↓": " runter ",
    ">=": " groesser oder gleich ",
    "<=": " kleiner oder gleich ",
    ">": " groesser als ",
    "<": " kleiner als ",
}


def clean_for_tts(text: str, language: str = "") -> str:
    """Clean text for TTS output.

    Removes:
    - Emojis
    - Markdown formatting
    - URLs
    - Status tags in brackets like [Keine weitere Aktion noetig], [No action needed], etc.
    - Reasoning/thinking blocks (<think>...</think>) from reasoning models like DeepSeek-R1, QwQ

    Converts:
    - Symbols to spoken words (e.g., degrees Celsius -> Grad Celsius for German)

    Args:
        text: The text to clean
        language: Language code or name for symbol conversion. 
                  Detects German if "de" is in the string (e.g., "de", "de-DE", "German", "Deutsch")

    Returns:
        Cleaned text suitable for TTS
    """
    if not text:
        return text

    result = text

    # Remove status tags in brackets (LLM action indicators)
    # Supports: German (Aktion), English (action), French (action), Spanish (accion), 
    # Italian (azione), Dutch (actie), Portuguese (acao)
    result = re.sub(
        r'\s*\[[^\]]*(?:Aktion|action|accion|azione|actie|acao|Handlung|needed|noetig|required|erforderlich|necessaire|necesario|necessario|nodig|necessario)[^\]]*\]\s*',
        ' ',
        result,
        flags=re.IGNORECASE
    )

    # Remove <think>...</think> reasoning blocks from reasoning models
    # (DeepSeek-R1, QwQ, Qwen with thinking, etc.)
    result = THINKING_BLOCK_PATTERN.sub("", result)
    
    # Remove emojis
    result = EMOJI_PATTERN.sub("", result)

    # Remove URLs
    result = URL_PATTERN.sub("", result)

    # Remove markdown formatting
    for pattern, replacement in MARKDOWN_PATTERNS:
        result = pattern.sub(replacement, result)

    # Convert symbols to words (order matters - longer patterns first)
    # Use German symbols if language contains "de" (e.g., "de", "de-DE", "German (Deutsch)")
    is_german = _is_german(language) if language else False
    symbol_map = SYMBOL_MAPPINGS_DE if is_german else SYMBOL_MAPPINGS
    # Sort by length descending to match longer patterns first
    for symbol, word in sorted(symbol_map.items(), key=lambda x: len(x[0]), reverse=True):
        result = result.replace(symbol, word)

    # Clean up extra whitespace
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"\n\s*\n+", "\n", result)
    result = result.strip()

    return result


def remove_urls_for_tts(text: str) -> str:
    """Remove URLs from text for TTS output.
    
    This is a lightweight function that only removes URLs, without
    the full clean_for_tts processing. URLs are never useful when
    spoken aloud.
    
    Args:
        text: The text to clean
        
    Returns:
        Text with URLs removed
    """
    if not text:
        return text
    
    result = URL_PATTERN.sub("", text)
    
    # Clean up extra whitespace after URL removal
    result = re.sub(r"\s+", " ", result)
    result = result.strip()
    
    return result


def sanitize_user_facing_error(
    err: Exception | str,
    fallback: str = "Sorry, I ran into a temporary issue while processing that.",
) -> str:
    """Return a short, user-safe error message without raw backend payloads."""
    raw = str(err or "").strip()
    if not raw:
        return fallback

    safe = raw
    for pattern in RAW_ERROR_PATTERNS:
        safe = pattern.sub("", safe).strip()

    safe = URL_PATTERN.sub("", safe)
    safe = re.sub(r"\s+", " ", safe).strip(" .:-")

    lowered = safe.lower()
    if "timeout" in lowered:
        return "The request timed out. Please try again."
    if any(token in lowered for token in ("unauthorized", "forbidden", "401", "403")):
        return "Authentication failed while contacting the AI service."
    if any(token in lowered for token in ("429", "rate limit", "too many requests")):
        return "The AI service is busy right now. Please try again shortly."
    if any(token in lowered for token in ("network", "connection", "unreachable")):
        return "Network issue while contacting the AI service. Please try again."
    if any(token in lowered for token in ("api error", "server error", "500", "502", "503", "504")):
        return "The AI service returned an error. Please try again."

    if len(safe) < 10:
        return fallback
    if len(safe) > 180:
        return fallback
    return safe


async def execute_tools_parallel(
    tool_calls: list[ToolCall],
    tool_registry: ToolRegistry,
    *,
    max_retries: int | None = None,
    latency_budget_ms: int | None = None,
) -> list[ChatMessage]:
    """Execute tool calls in parallel and return ChatMessages with results.

    Handles both successful results and exceptions, always producing a
    tool-role ChatMessage for every tool_call so the LLM receives a
    response for each tool_call_id.

    Args:
        tool_calls: List of ToolCall objects from the LLM response.
        tool_registry: Tool registry to execute tools against.

    Returns:
        List of ChatMessage(role=TOOL) -- one per tool_call.
    """
    from .llm.models import ChatMessage, MessageRole

    async def _exec(tc: ToolCall) -> tuple[ToolCall, Any]:
        try:
            result = await tool_registry.execute(
                tc.name,
                tc.arguments,
                max_retries=max_retries,
                latency_budget_ms=latency_budget_ms,
            )
        except TypeError:
            result = await tool_registry.execute(tc.name, tc.arguments)
        return (tc, result)

    raw_results = await asyncio.gather(
        *[_exec(tc) for tc in tool_calls],
        return_exceptions=True,
    )

    messages: list[ChatMessage] = []
    for idx, item in enumerate(raw_results):
        if isinstance(item, Exception):
            _LOGGER.error("Tool execution failed: %s", item)
            tc = tool_calls[idx]
            messages.append(
                ChatMessage(
                    role=MessageRole.TOOL,
                    content=f"Error: {item}",
                    tool_call_id=tc.id,
                    name=tc.name,
                )
            )
        else:
            tc, result = item
            messages.append(
                ChatMessage(
                    role=MessageRole.TOOL,
                    content=result.to_string(),
                    tool_call_id=tc.id,
                    name=tc.name,
                )
            )

    return messages


def extract_target_domains(arguments: dict[str, Any]) -> set[str]:
    """Extract target domains from control-tool arguments.

    Handles nested dicts and lists to catch all entity references.
    """
    domains: set[str] = set()

    def _collect_entity_like(value: Any) -> None:
        if isinstance(value, str):
            if "." in value:
                domains.add(value.split(".", 1)[0])
            return

        if isinstance(value, list):
            for item in value:
                _collect_entity_like(item)
            return

        if isinstance(value, dict):
            for key in ("entity_id", "entity_ids", "target", "targets", "entity"):
                if key in value:
                    _collect_entity_like(value[key])

    for key in ("entity_id", "entity_ids", "target", "targets", "entity"):
        if key in arguments:
            _collect_entity_like(arguments[key])

    explicit_domain = arguments.get("domain")
    if isinstance(explicit_domain, str) and explicit_domain:
        domains.add(explicit_domain)

    return domains


def normalize_media_player_targets(targets: Any) -> list[str]:
    """Normalize media player targets from list or comma-separated string.

    Deduplicates, lowercases, and filters to media_player entities only.
    """
    if targets is None:
        return []
    if isinstance(targets, list):
        raw_values = [str(item or "") for item in targets]
    else:
        raw_values = str(targets).split(",")

    result: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        entity_id = value.strip().lower()
        if not entity_id or not entity_id.startswith("media_player."):
            continue
        if entity_id in seen:
            continue
        seen.add(entity_id)
        result.append(entity_id)
    return result


def resolve_media_players_by_satellite(
    hass: Any,
    satellite_id: str | None,
) -> list[str]:
    """Best-effort match from satellite id to media_player entities.

    Splits the satellite name into parts and matches against all
    media_player entity IDs using substring matching (parts >= 3 chars).
    """
    if not satellite_id:
        return []

    sat_name = str(satellite_id).lower().replace("assist_satellite.", "")
    sat_parts = sat_name.replace("satellite_", "").replace("_assist_satellit", "").split("_")
    candidates: list[str] = []

    for state in hass.states.async_all("media_player"):
        player_id = state.entity_id.lower()
        for part in sat_parts:
            if len(part) >= 3 and part in player_id:
                candidates.append(state.entity_id)
                break

    return normalize_media_player_targets(candidates)
