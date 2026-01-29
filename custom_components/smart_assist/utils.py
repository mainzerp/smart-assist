"""Utility functions for Smart Assist integration."""

from __future__ import annotations

import logging
import re
from typing import Any, Final, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry, ConfigSubentry

_LOGGER = logging.getLogger(__name__)


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

# URL pattern
URL_PATTERN: Final = re.compile(
    r"https?://[^\s\)\]\>]+|www\.[^\s\)\]\>]+",
    flags=re.IGNORECASE,
)

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
    - Status tags in brackets like [Keine weitere Aktion nötig], [No action needed], etc.

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
    # Supports: German (Aktion), English (action), French (action), Spanish (acción), 
    # Italian (azione), Dutch (actie), Portuguese (ação)
    result = re.sub(
        r'\s*\[[^\]]*(?:Aktion|action|acción|azione|actie|ação|Handlung|needed|nötig|required|erforderlich|nécessaire|necesario|necessario|nodig|necessário)[^\]]*\]\s*',
        ' ',
        result,
        flags=re.IGNORECASE
    )
    
    # Remove emojis
    result = EMOJI_PATTERN.sub("", result)

    # Remove URLs
    result = URL_PATTERN.sub("", result)

    # Remove markdown formatting
    for pattern, replacement in MARKDOWN_PATTERNS:
        result = pattern.sub(replacement, result)

    # Convert symbols to words (order matters - longer patterns first)
    # Use German symbols if language contains "de" (e.g., "de", "de-DE", "German (Deutsch)")
    is_german = "de" in language.lower() if language else False
    symbol_map = SYMBOL_MAPPINGS_DE if is_german else SYMBOL_MAPPINGS
    # Sort by length descending to match longer patterns first
    for symbol, word in sorted(symbol_map.items(), key=lambda x: len(x[0]), reverse=True):
        result = result.replace(symbol, word)

    # Clean up extra whitespace
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"\n\s*\n+", "\n", result)
    result = result.strip()

    return result
