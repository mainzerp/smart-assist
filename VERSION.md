# Smart Assist - Version History

## Current Version

| Component    | Version | Date       |
| ------------ | ------- | ---------- |
| Smart Assist | 1.6.8   | 2026-01-27 |

## Version History

### v1.6.8 (2026-01-27) - Extended Reminder Window

**Improvements:**

- Extended last reminder window from 30-90min to 10-90min before event
- Reminder now shows actual minutes instead of fixed "in einer Stunde"
- Example: "In 15 Minuten hast du 'Meeting'"

### v1.6.7 (2026-01-27) - Fuzzy Calendar Matching

**Improvements:**

- Calendar event creation now uses fuzzy matching for calendar names
- "Patrick" matches `calendar.patric`, "Laura" matches `calendar.laura`
- LLM no longer needs exact entity IDs to create calendar events
- Shows available calendars in error message if no match found

### v1.6.6 (2026-01-27) - AWAIT_RESPONSE Logging

**Improvements:**

- Added debug logging for `[AWAIT_RESPONSE]` marker detection
- Log shows whether marker was found or missing in LLM response
- Helps diagnose when LLM doesn't follow instruction to keep conversation open

### v1.6.5 (2026-01-27) - AWAIT_RESPONSE Prompt Fix

**Fix:**

- Strengthened `[AWAIT_RESPONSE]` marker instruction in system prompt
- LLM was not consistently adding the marker when asking follow-up questions
- Added "CRITICAL" label and more explicit examples to improve compliance

### v1.6.4 (2026-01-27) - Debug Log Improvements

**Improvements:**

- Improved calendar context log readability (replaced newlines with spaces)
- Added calendar context length logging for debugging

### v1.6.3 (2026-01-27) - Chat History Fix

**Bug Fix:**

- Fixed "slice indices must be integers" error in chat history processing
- max_history config value now explicitly cast to integer

### v1.6.2 (2026-01-27) - Calendar Reminder Mention Fix

**Bug Fix:**

- LLM now explicitly instructed to mention calendar reminders in responses
- Added "Calendar Reminders" instruction to system prompt
- Calendar context was being injected but LLM wasn't aware it should mention it

**Debug:**

- Added detailed calendar context logging for troubleshooting

### v1.6.1 (2026-01-27) - Debug Logging

**Debug:**

- Added calendar context debug logging for troubleshooting

### v1.6.0 (2026-01-27) - Calendar Integration

**New Features:**

- **Calendar Read Access**: Query upcoming events with `get_calendar_events` tool
  - Time ranges: today, tomorrow, this_week, next_7_days
  - Filter by specific calendar or query all calendars
  - Owner extraction from calendar entity names (calendar.laura -> "Laura")
- **Calendar Write Access**: Create events with `create_calendar_event` tool
  - Support for timed events (datetime) and all-day events (date)
  - Optional description and location fields
  - Automatic duration defaults (1 hour for timed, 1 day for all-day)
- **Proactive Calendar Reminders**: Context injection with staged reminder windows
  - 24h before (reminder window +/- 4 hours)
  - 4h before (reminder window +/- 1 hour)
  - 1h before (reminder window +/- 30 minutes)
  - Deduplication: each event mentioned only once per stage
  - No catch-up reminders for missed windows
- **Calendar Context Toggle**: New configuration option to enable/disable proactive reminders

**Technical Changes:**

- Added "calendar" to SUPPORTED_DOMAINS
- New file: `tools/calendar_tools.py` with GetCalendarEventsTool and CreateCalendarEventTool
- New file: `context/calendar_reminder.py` with CalendarReminderTracker
- Updated conversation.py with `_get_calendar_context()` method
- Added CONF_CALENDAR_CONTEXT configuration constant
- UI translations for calendar context option (en/de)

### v1.5.11 (2026-01-27) - Flexible Language Configuration

**New Features:**

- Response language is now a free text field instead of dropdown
- Leave empty for auto-detection (uses Home Assistant's configured language)
- Enter any language name or code: "French", "es-ES", "Japanese", etc.
- Added `LOCALE_TO_LANGUAGE` mapping for 20+ common locales
- Auto-detection now shows native language name (e.g., "German (Deutsch)")

**Technical Changes:**

- Replaced `SelectSelector` with `TextSelector` for language field
- Removed `SUPPORTED_LANGUAGES` constant and `DEFAULT_LANGUAGE`
- Updated `_build_system_prompt()` to use flexible language instruction
- Updated `clean_for_tts()` to detect German from any language string containing "de"

### v1.5.10 (2026-01-26) - TTS Marker Fix

**Bug Fix:**

- Fixed `[AWAIT_RESPONSE]` marker being spoken by TTS
- Added 16-char buffer in streaming to filter markers across chunk boundaries

### v1.5.9 (2026-01-26) - True TTS Streaming

**New Features:**

- Implemented true streaming to Home Assistant ChatLog
- Uses `chat_log.async_add_delta_content_stream()` API
- LLM responses now stream directly to TTS for faster voice output

### v1.5.6 (2026-01-26) - Sensor Fix

**Bug Fix:**

- Fixed sensor entities not showing metrics with subentry architecture
- Sensors now aggregate metrics from all conversation agents

### v1.5.5 (2026-01-26) - Bug Fix

**Bug Fix:**

- Fixed double listener removal error in cache warming callback
- Listener now properly tracks if callback was already called before unsubscribing

### v1.5.4 (2026-01-26) - Code Quality Improvements

**Refactoring:**

- Centralized `apply_debug_logging` function in `utils.py` (deduplicated from `__init__.py` and `config_flow.py`)
- Added constants: `DEFAULT_EXPOSED_ONLY`, `DEFAULT_CONFIRM_CRITICAL`, `SUPPORTED_LANGUAGES`
- Replaced hardcoded language options with `SUPPORTED_LANGUAGES` constant
- Changed debug-level warnings to proper `debug` log level during module loading
- Removed unused `traceback` import from `__init__.py`
- Fixed type annotation: `subentry: Any` to `ConfigSubentry`

**Code Quality:**

- Reduced code duplication (-15 lines net)
- Improved maintainability through centralized constants
- Better type safety with proper annotations

### v1.5.3 (2026-01-26) - Hassfest Validation Fix

**Bug Fix:**

- Added `reconfigure_successful` abort translation for subentries

### v1.5.2 (2026-01-26) - Hassfest Validation

**Bug Fix:**

- Added `entry_type` and `CONFIG_SCHEMA` for hassfest validation compliance

### v1.5.1 (2026-01-26) - Translation Fix

**Bug Fix:**

- Added missing `reconfigure_settings` German translation for Conversation subentry

### v1.5.0 (2026-01-26) - Two-Step Config Flow

**New Features:**

- Two-step config flow with dynamic provider selection
- Provider selection happens after model selection for accurate pricing display
- Dynamic provider fetching from OpenRouter API endpoints

### v1.4.0 (2026-01-26) - Simplified Subentry Flow

**Improvements:**

- Simplified subentry flow - skip provider step during creation
- Provider can be changed via reconfigure

### v1.3.3 (2026-01-26) - Debug Logging

**Debug:**

- Added WARNING level logging to provider fetch for debugging

### v1.3.2 (2026-01-26) - Model Variants

**Bug Fix:**

- Keep model variants in provider fetch (e.g., `:free`, `:exacto`)

### v1.3.1 (2026-01-26) - Translation Fix

**Bug Fix:**

- Fixed translation mismatch for subentry steps
- Improved provider fetch logging

### v1.3.0 (2026-01-26) - Subentry Architecture

**Breaking Change:**

- Major refactoring to use Home Assistant's Subentry system
- Existing configurations will need to be reconfigured

**New Architecture:**

- Multiple Conversation Agents: Add multiple conversation agents with different models/settings
- Multiple AI Tasks: Add multiple AI tasks with different configurations
- Per-agent configuration: Each agent/task has independent model, provider, and behavior settings
- Unified API key: Single API key shared across all agents and tasks

**Config Flow Changes:**

- Main config entry now only stores API key
- Conversation Agents added via "Add Conversation Agent" subentry button
- AI Tasks added via "Add AI Task" subentry button
- Each subentry has multi-step wizard: Model -> Provider -> Behavior/Settings -> Prompt

**Technical Improvements:**

- `ConfigSubentryFlow` handlers for conversation and ai_task types
- Entity creation from subentries with proper device registry
- Per-agent cache warming with individual timers
- Subentry-based unique IDs and device identifiers

**Reference Implementation:**

- Based on pattern from skye-harris/hass_local_openai_llm

### v1.2.0 (2026-01-26) - AI Task Platform & Parallel Execution

**New Features:**

- AI Task Platform: Use LLM in automations via `ai_task.generate_data` service
- Parallel Tool Execution: Execute multiple tool calls concurrently with `asyncio.gather()`
- Separate AI Task caching options (disabled by default - tasks are not time-critical)

**AI Task Platform:**

- Registers as `ai_task` platform in addition to `conversation`
- Full tool support (entity queries, control, scenes, web search)
- Configurable task-specific system prompt
- Independent caching settings for background tasks

**Configuration:**

- New options: `task_system_prompt`, `task_enable_prompt_caching`, `task_enable_cache_warming`
- Task caching disabled by default (background tasks are not time-critical)
- UI hints explaining why task caching is usually not needed

### v1.1.0 (2026-01-26) - Code Quality and Stability

**Improvements:**

- Thread-safe session management with AsyncLock (prevents race conditions)
- Unified DEFAULT_MODEL constant usage across codebase
- Tool argument validation (brightness, color_temp, volume, position, rgb_color)
- Removed legacy tool class imports (ControlEntityTool, ControlLightTool, etc.)
- Added type hints to inner functions
- Fixed Markdown table formatting in documentation

**Changes:**

- Quick Actions feature disabled by default (removed from UI)
- README header updated to highlight Prompt Caching benefits
- Added Response Validator concept to roadmap

**Documentation:**

- Created docs/code-improvements.md for tracking improvements
- Updated README with Prompt Caching focus

### v1.0.0 (2026-01-25) - Initial Release

**Core Features:**

- LLM-powered smart home control via OpenRouter API
- ConversationEntity-based architecture with streaming support
- Real token-by-token streaming for responsive UI
- Tool-based entity control (lights, climate, covers, media, scripts, etc.)
- Multi-turn conversation with ChatLog integration
- Marker-based conversation continuation (`[AWAIT_RESPONSE]`)

**Model Support:**

- Dynamic model fetching from OpenRouter API
- Free text model input (any OpenRouter model supported)
- Automatic prompt caching detection based on model prefix
- Provider-specific caching support (Anthropic, OpenAI, Google, Groq)

**Prompt Caching:**

- Anthropic: Explicit cache_control with 5min/1h TTL options
- OpenAI/Google/Groq: Automatic caching
- Cache warming option for consistent low latency
- System prompt caching optimization

**Configuration:**

- Multi-step config flow (API key, model, behavior, prompt)
- Options flow for runtime configuration changes
- Bilingual UI (English/German)
- Custom system prompt support

**Reliability:**

- Retry logic with exponential backoff (max 3 retries)
- LLM metrics tracking (requests, tokens, response times, cache hits)
- Session cleanup on integration unload
- Graceful error handling

**Entity Management:**

- Entity index for fast lookup
- Support for exposed entities only mode
- Critical action confirmation (locks, alarms)
- Domain-based entity filtering

## Technology Stack

| Technology | Version | Purpose |
| ---------- | ------- | ------- |
| Home Assistant | 2024.1+ | Core platform |
| Python | 3.11+ | Runtime |
| aiohttp | 3.9+ | Async HTTP client |
| OpenRouter API | v1 | LLM gateway |

## Changelog Format

Each release follows this format:

- **Major (X.0.0)**: Breaking changes
- **Minor (1.X.0)**: New features, backward compatible
- **Patch (1.0.X)**: Bug fixes, small improvements
