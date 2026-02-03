# Smart Assist - Version History

## Current Version

| Component    | Version | Date       |
| ------------ | ------- | ---------- |
| Smart Assist | 1.4.2   | 2026-02-03 |

## Version History

### v1.4.2 (2026-02-03) - Ollama Bug Fixes

**Fix: Ollama keep_alive Duration Parsing Error**

- Fixed `time: missing unit in duration "-1"` error
- Added `_format_keep_alive()` helper to send -1 as integer instead of string
- Ollama API now correctly receives keep_alive values

**Fix: Missing chat_stream_full Method**

- Added `chat_stream_full()` method to OllamaClient
- Required for TTS streaming in conversation system
- Returns structured delta events compatible with Groq/OpenRouter clients

### v1.4.1 (2026-02-03) - Reasoning Model Output Cleanup

**Fix: Filter `<think>` Tags from Reasoning Models**

- Added `THINKING_BLOCK_PATTERN` to filter `<think>...</think>` reasoning blocks
- Affects DeepSeek-R1, QwQ, Qwen with thinking, and other Chain-of-Thought models
- TTS output now clean without internal reasoning steps being spoken
- Regex is case-insensitive and handles multi-line content

### v1.4.0 (2026-02-03) - Ollama Integration

**Feature: Local LLM Support with Ollama**

- Added Ollama as third LLM provider for local, private inference
- No API key required - runs entirely on your hardware
- Full tool calling support (llama3.1+, mistral, qwen2.5, command-r)
- Automatic model discovery from local Ollama installation
- Configurable context window size (num_ctx)
- Model persistence with keep_alive setting (-1 = stay loaded)
- KV cache optimization for faster repeated queries

**Configuration Options**

- Ollama server URL (default: http://localhost:11434)
- Model selection with size information
- Keep-alive duration for model persistence
- Context window size (1024-131072 tokens)
- Request timeout (30-600 seconds)

**Privacy Benefits**

- All data stays local - no cloud transmission
- No API costs - only electricity
- 100% availability - no service dependencies
- Full control over model versions

### v1.3.1 (2026-02-03) - Async Fix

**Fix: SyntaxError in conversation.py**

- Fixed `await` outside async function error
- Made `_build_messages_for_llm` async to support thread-safe tool registry
- No changes to prompt caching behavior or static-to-dynamic message order

### v1.3.0 (2026-02-03) - OpenRouter Integration

**Feature: Dual LLM Provider Support**

- Added OpenRouter as alternative LLM provider alongside Groq
- Access to 200+ models (Claude, GPT-4, Llama, Mistral, Gemini, etc.)
- Provider selection in Conversation Agent and AI Task configuration
- Dynamic model list fetched from provider APIs
- OpenRouter-specific provider routing (choose specific cloud providers)
- Automatic provider detection based on configured API keys

**Code Quality Improvements**

- Added asyncio.Lock for thread-safe tool registry initialization
- Created BaseLLMClient abstract class for LLM client code reuse
- Centralized LLM constants (retry logic, timeouts)
- Added ToolParameterType enum for type-safe tool definitions
- Added async context manager support for LLM clients
- Unified logging with exc_info=True pattern
- Fixed mutable default argument anti-pattern
- Created test infrastructure (pytest fixtures, unit tests)
- Fixed 63 markdown linting errors in documentation

### v1.2.9 (2026-02-01) - TTS Delta Listener Fix

**Fix: TTS Streaming After Non-Streaming Iterations**

- Non-streaming responses now notify ChatLog's delta_listener
- TTS stream receives content even when using non-streaming fallback
- Fixes TTS hanging on Companion App after tool calls (web_search + send)

### v1.2.8 (2026-02-01) - TTS Companion App Fix

**Fix: TTS Hanging on Companion App After Tool Calls**

- Only use streaming in the first LLM iteration
- Subsequent iterations (after tool calls) use non-streaming
- Prevents TTS pipeline issues when ChatLog receives multiple streams
- Companion App now correctly plays TTS after web_search + send

### v1.2.7 (2026-02-01) - TTS Fallback Fix

**Fix: TTS Not Working After Non-Streaming Fallback**

- Fixed TTS not playing when streaming falls back to non-streaming
- Fallback response is now properly added to ChatLog for TTS
- Ensures voice confirmation after multi-tool execution (web_search + send)

### v1.2.6 (2026-02-01) - Streaming State Fix

**Fix: "Invalid State" Error After Multi-Tool Execution**

- Fixed error when LLM performs multiple tool calls (e.g., web_search then send)
- ChatLog streaming now falls back to non-streaming on subsequent iterations
- Prevents "invalid state" exception from HA ChatLog API
- Ensures user gets confirmation after successful tool execution

### v1.2.5 (2026-01-31) - Language Consistency Fix

**Fix: LLM No Longer Mixes Languages in Responses**

- Strengthened language instruction in system prompt with [CRITICAL] marker
- Removed English examples from follow-up behavior section that LLM was copying
- Language instruction now explicitly covers follow-ups, confirmations, and errors
- Added instruction to never mix languages in responses

### v1.2.4 (2026-01-31) - Concise Send Responses

**Improvement: LLM Responds Briefly After Sending**

- Updated system prompt to instruct LLM to respond briefly after send actions
- Example: "Sent to your Pixel" instead of repeating the sent content
- User will see the content on their device, no need to read it aloud

### v1.2.3 (2026-01-31) - TTS URL Removal

**Improvement: URLs Always Removed from TTS Output**

- URLs are now always removed from spoken responses, regardless of clean_responses setting
- Prevents TTS from reading out long URLs like "https colon slash slash..."
- Added `remove_urls_for_tts()` utility function

### v1.2.2 (2026-01-31) - Chat History Fix for Tool Results

**Fix: Tool Results Now Included in Conversation History**

- Fixed issue where tool call results (e.g., web search results) were lost between conversation turns
- LLM now receives full context including previous tool calls and their results
- Enables proper follow-up conversations after tool executions (e.g., "send me the link" after a web search)
- Added debug logging for chat history entry types

### v1.2.1 (2026-01-31) - Send Tool Debug Logging

**Improvement: Debug Logging for Send Tool**

- Added debug logging for available notification targets (mobile apps, other services)
- Logs target resolution when send tool is called
- Helps troubleshoot device matching issues

### v1.2.0 (2026-01-31) - Send Tool for Notifications

**New Feature: Universal Send Tool**

Added `send` tool for sending content (links, messages) to notification targets:
- Dynamically discovers all `notify.*` services (mobile apps, Telegram, email, groups, etc.)
- LLM sees available targets in tool description
- Can send links, reminders, or any text content
- Supports single and multiple URLs with actionable notifications

Example flow:
1. LLM has useful information or links to share
2. LLM offers: "Soll ich dir die Links schicken?"
3. User responds: "Ja, auf Patrics Handy" or "Schick es an Telegram"
4. LLM calls `send` tool with content and target
5. User receives notification with clickable links

Features:
- Automatic URL extraction from content
- Single URL: notification clickable to open link
- Multiple URLs: action buttons for up to 3 links
- Fuzzy matching for target names (e.g., "patrics_handy" matches "mobile_app_patrics_iphone")
- Works with any HA notify service (mobile_app, telegram, email, groups, etc.)

### v1.1.3 (2026-01-30) - Follow-up Loop Protection

**Fix: Prevent Infinite Follow-up Loops**

Added protection against endless clarification loops when satellite is triggered by false positive (e.g., TV audio):
- Tracks consecutive follow-up questions per conversation session
- After 3 consecutive follow-ups without meaningful action, conversation aborts
- Returns "I did not understand. Please try again." instead of another question
- Counter resets after any successful tool execution

How it works:
1. Satellite triggered by TV audio (false positive wake word)
2. LLM receives unintelligible input, asks for clarification (followup #1)
3. Satellite listens again, captures more TV audio (followup #2)
4. After 3rd failed attempt, Smart Assist aborts and stops listening

This prevents the satellite from getting stuck in an infinite loop of questions when triggered accidentally.

### v1.1.2 (2026-01-30) - Entity History Periods Aggregation

**Improvement: Better History Output for Binary Entities**

Added `periods` aggregation option to `get_entity_history` tool:
- Calculates on/off time ranges for switches, lights, locks, etc.
- Returns human-readable periods: "from 15:18 to 19:45 (4h 27min)"
- Includes total on-time calculation
- Supports states: on, playing, home, open, unlocked, active, heating, cooling

Example output:
```
switch.keller was on during 24h:
  from 15:18 to 19:45 (4h 27min)
  from 20:01 to 20:03 (2min)
  Total on time: 4h 29min
```

LLM can now say "Das Licht war von 15:18 bis 19:45 Uhr an" instead of just listing state changes.

### v1.1.1 (2026-01-30) - Recorder Dependency Fix

**Bugfix: Missing Recorder Dependency**

- Added `recorder` to manifest.json dependencies
- Required for `get_entity_history` tool to access historical states
- Fixes GitHub Actions CI validation error

### v1.1.0 (2026-01-30) - Entity History Queries & Multi-Turn Context

**New Feature: Entity History Queries**

New `get_entity_history` tool allows querying historical entity states:
- Time periods: 1h, 6h, 12h, 24h, 48h, 7d
- Aggregation modes: raw (all changes), summary (min/max/avg), last_change
- Supports numeric sensors (temperature, humidity) with statistics
- Supports discrete state entities (lights, switches) with occurrence counts

Example queries:
- "How was the temperature yesterday?"
- "When was the light last on?"
- "What was the average humidity in the last 6 hours?"

**New Feature: Multi-Turn Context Improvements**

Enhanced pronoun resolution for natural conversations:
- Tracks last 5 entities interacted with per conversation
- Injects `[Recent Entities]` context for LLM pronoun resolution
- System prompt instructs LLM to use context for "it", "that", "the same one"

Example conversation:
1. User: "Turn on the kitchen light" -> Tracks light.kitchen
2. User: "Make it brighter" -> LLM resolves "it" = light.kitchen
3. User: "What's the temperature?" -> Tracks sensor.kitchen_temp
4. User: "Turn that off" -> LLM resolves "that" = light.kitchen (most recent controllable)

**Implementation Details:**
- `GetEntityHistoryTool` in entity_tools.py - Uses HA recorder/history API
- `RecentEntity` dataclass in context/conversation.py - Tracks entity_id, friendly_name, action, timestamp
- `ConversationSession.recent_entities` - deque with maxlen=5
- Context placed in dynamic section to preserve prompt caching

### v1.0.30 (2026-01-30) - Auto-Detect Questions for Conversation Continuation

**Improvement: Question Detection Fallback**

- Auto-detects when LLM response ends with `?` but forgot to call `await_response` tool
- Automatically enables `continue_conversation` for questions
- Ensures user can always respond to questions, even if LLM doesn't follow instructions perfectly

### v1.0.29 (2026-01-30) - Fix Duplicate Tool Calls

**Fix: Duplicate Tool Call Execution**

- Added deduplication of tool calls by ID before execution
- LLM sometimes sends duplicate tool calls (same ID), now only one is executed
- Changed Music Assistant `play_media` to non-blocking to prevent hanging
- Prevents processing loop getting stuck when Music Assistant takes too long

### v1.0.28 (2026-01-30) - Conditional Music Instructions

**Improvement: Dynamic Prompt Injection Based on Tool Availability**

- Music/Radio Playback instructions now only appear in system prompt when `music_assistant` tool is registered
- Simpler, clearer instructions without conditional logic for the LLM
- Added `has_tool()` method to ToolRegistry for checking tool availability
- Fixed duplicate MusicAssistantTool registration bug

### v1.0.27 (2026-01-30) - Clearer Music Assistant Instructions

**Improvement: Explicit Tool Selection for Music**

- System prompt now explicitly tells LLM to check available tools
- Clear priority: 1) music_assistant tool if available, 2) control tool as fallback
- Clearer separation: control for lights/switches/etc, music_assistant for music/radio
- Improved satellite-to-player mapping reference

### v1.0.26 (2026-01-30) - Music Assistant Detection & System Prompt

**Fix: Music Assistant Tool Detection**

- Improved detection logic with 3 methods:
  1. Check `hass.data` for music_assistant key
  2. Check for MA player attributes (mass_player_id, mass_player_type)
  3. Check if `music_assistant.play_media` service exists
- Added debug logging for detection method
- Added fallback logging when not detected

**New: Music/Radio Playback Instructions in System Prompt**

- Added instructions for when to use `music_assistant` tool
- LLM now knows to use music_assistant for songs, artists, albums, playlists, radio
- References satellite-to-player mapping from user system prompt

### v1.0.25 (2026-01-30) - Satellite Context for Media Playback

**New Feature: Current Assist Satellite in Context**

- Satellite entity_id is now included in the dynamic context
- LLM knows which Assist satellite initiated the request
- Enables automatic media player mapping based on user system prompt

How it works:
- ConversationInput.satellite_id is passed through to message builder
- Added `[Current Assist Satellite: assist_satellite.xxx]` to dynamic context
- User can define mappings in system prompt (satellite -> media_player)

Example user system prompt:
```
Satellite to Media Player Mappings:
- assist_satellite.satellite_kuche_assist_satellit -> media_player.ma_satellite_kuche
- assist_satellite.satellite_flur_assist_satellit -> media_player.ma_satellite_flur
```

Now "play music" without specifying player will use the correct mapped player.

### v1.0.24 (2026-01-30) - Music Assistant Integration

**New Feature: MusicAssistantTool**

- New `music_assistant` tool for advanced music control
- Uses Music Assistant integration for multi-provider support
- Actions: play, search, queue_add

Features:
- Play music from any provider (Spotify, YouTube Music, local files, etc.)
- Internet radio support (TuneIn, Radio Browser, etc.)
- Radio mode for endless dynamic playlists based on seed track/artist
- Queue management (play, replace, next, add)
- Search across all configured providers

Parameters:
- `action`: play, search, queue_add
- `query`: Search term (song, artist, album, playlist, radio station)
- `media_type`: track, album, artist, playlist, radio
- `artist`, `album`: Optional filters
- `player`: Target media player entity_id
- `enqueue`: play, replace, next, add
- `radio_mode`: Enable endless similar music

Examples:
- Play song: `action=play, query="Bohemian Rhapsody", media_type=track`
- Play radio: `action=play, query="SWR3", media_type=radio`
- Radio mode: `action=play, query="Queen", media_type=artist, radio_mode=true`
- Add to queue: `action=queue_add, query="Another One Bites the Dust"`

Tool is automatically available when Music Assistant is installed.

### v1.0.23 (2026-01-30) - Timer Reminders and Delayed Commands

**New Feature: conversation_command Support**

- Timer tool now supports `command` parameter for delayed actions
- Execute any voice command when timer finishes
- Enables voice reminders without separate reminder system
- Uses native Assist `conversation_command` slot

Examples:
- Reminder: `timer(action=start, minutes=30, command="Remind me to drink water")`
- Delayed action: `timer(action=start, hours=1, command="Turn off the lights")`
- Combined: `timer(action=start, minutes=10, name="Pizza", command="Check the oven")`

### v1.0.22 (2026-01-30) - Unified Timer Tool with Native Intents

**Improvement: Simplified Timer Management**

- Single `timer` tool now uses native Assist intents (HassStartTimer, etc.)
- No Timer Helper entities required - uses built-in Assist voice timers
- Removed separate voice_timer tool - one unified timer tool
- Actions: start, cancel, pause, resume, status
- Parameters: hours, minutes, seconds, name

### v1.0.21 (2026-01-30) - Native Voice Timer Support

**New Feature: VoiceTimerTool**

- New `voice_timer` tool using native Assist intents
- Uses HassStartTimer, HassCancelTimer, HassPauseTimer, etc.
- Does NOT require Timer Helper entities - uses built-in Assist voice timers
- Actions: start, cancel, pause, resume, status, add_time, remove_time
- Parameters: hours, minutes, seconds, name, area
- Always available (not domain-dependent)

**Two Timer Options:**
1. `voice_timer` - Native Assist voice timers (satellite-specific, no entities)
2. `timer` - Timer Helper entities (for automations, requires timer domain)

### v1.0.20 (2026-01-30) - Timer Tool

- New `timer` tool for managing HA timer helpers
- Actions: start, cancel, pause, finish, change
- Auto-finds available timer if not specified
- Duration format: HH:MM:SS (e.g., "00:05:00" for 5 minutes)
- Requires timer helper to be configured in HA

### v1.0.19 (2026-01-30) - Calendar: Only Show Upcoming Events

- Fixed: "What's on my calendar today?" no longer returns past events
- get_calendar_events now starts from current time, not midnight
- Past events from today are filtered out

### v1.0.18 (2026-01-30) - Double Cache Warming at Startup

**Improvement: Faster Initial Response**

- Cache warming now runs TWICE at startup
- First warmup creates the cache, second warmup uses it
- Immediate benefit from prompt caching on first user request
- warmup_count sensor now reflects both warmups

### v1.0.17 (2026-01-30) - TTS Response Format Rules

**Improvement: TTS-Optimized Output**

- Added rule: Use plain text only - no markdown, no bullet points, no formatting
- Added rule: Responses are spoken aloud (TTS) - avoid URLs, special characters, abbreviations
- Cleaner audio output from voice assistants

### v1.0.16 (2026-01-30) - English System Prompt Examples

**Improvement: Consistent Language**

- Changed examples in system prompt from German to English
- LLMs understand English instructions better
- Example now uses "Is there anything else I can help with?" instead of German

### v1.0.15 (2026-01-30) - Mandatory await_response for Questions

**Improvement: Stronger System Prompt**

- Added explicit rule: EVERY question MUST use await_response tool
- Clear WRONG vs CORRECT examples in system prompt
- Rule: If response ends with "?", must call await_response
- LLM should no longer ask questions without tool call

### v1.0.14 (2026-01-30) - await_response with Message Parameter

**Improvement: Tool Redesign**

- Added required `message` parameter to await_response tool
- LLM now passes the question text directly in the tool call
- Conversation handler extracts message from tool arguments
- No more reliance on LLM outputting text before tool call
- System prompt updated with new tool usage examples

Example: `await_response(message="Which room?", reason="clarification")`

### v1.0.13 (2026-01-30) - Simplified await_response Tool

**Improvement: Tool Definition**

- Simplified await_response tool description to match other working tools
- Changed reason parameter from optional to required
- Removed verbose instructions from tool description
- Cleaner system prompt with example flow
- Removed text fallback workaround (pure tool-based solution)

### v1.0.12 (2026-01-30) - Text Fallback for await_response

**Bugfix: Model Compatibility**

- Fixed issue where some models (e.g., gpt-oss-120b) output `await_response({...})` as text instead of a proper tool call
- Added regex detection to extract await_response from text output
- Text is cleaned (await_response removed) and conversation continuation is properly set
- Satellites now correctly enter listening mode even when model uses text syntax

### v1.0.11 (2026-01-30) - await_response Fix for Satellites

**Bugfix: Voice Assistant Satellites**

- Fixed issue where satellites (e.g., ESP32-S3) would not enter listening mode after `await_response`
- Root cause: LLM called `await_response` tool without providing speech text first
- Speech was empty, so no audio was played, and satellite never transitioned to listening mode

**Improvements:**

- Updated system prompt with explicit instruction to ALWAYS include text BEFORE calling `await_response`
- Enhanced `await_response` tool description with clear examples of correct/incorrect usage
- Added warning log when `await_response` is called without response text

### v1.0.10 (2026-01-29) - await_response Tool

**Refactor: Conversation Continuation**

- Replaced text marker `[AWAIT_RESPONSE]` with `await_response` tool
- LLM now calls a tool to signal "keep microphone open" instead of adding text markers
- Prevents LLM from inventing markers like `[Keine weitere Aktion nötig]` or `[No action needed]`
- Deterministic, debuggable (tool calls visible in logs)
- System prompt updated with clear tool usage instructions
- Proactive follow-up: LLM can now ask "Is there anything else I can help with?"

**Benefits:**
- No more random action status tags in TTS output
- Cleaner, more predictable conversation flow
- Better for AI Tasks that need user confirmation

### v1.0.9 (2026-01-29) - TTS Cleanup for Action Tags

- Removed action status tags from TTS output (e.g., [Keine weitere Aktion nötig], [No action needed])
- These LLM action indicators are now stripped before speech synthesis

### v1.0.8 (2026-01-29) - Cache Warming Sensor Update Fix

- Fixed sensors not updating after cache warming (missing dispatcher signal)
- Fixed Groq client double-counting usage metrics (usage sent twice in stream)
- Cache warming requests now correctly contribute to all metric sensors

### v1.0.7 (2026-01-29) - Cached Tokens Tracking Fix

- Fixed cached_tokens metric not being tracked in OpenRouter client
- Cache warming now correctly contributes to average cached tokens sensor
- Note: For device grouping issues, please remove and re-add the Smart Assist integration

### v1.0.6 (2026-01-29) - Per-Agent Metrics (Bugfix)

**Bugfixes**

- Fixed sensor subentry grouping: sensors now correctly appear only under their respective agent/task device
- Fixed Cache Warming sensor state class (string status, not measurement)

### v1.0.5 (2026-01-29) - Per-Agent Metrics

**Improvements**

- **Per-Agent Sensors**: Metrics are now tracked per Conversation Agent and AI Task instead of aggregated
  - Each agent/task now has its own set of sensors (response time, requests, tokens, cache hits, etc.)
  - Sensors are grouped under the respective device in Home Assistant
- **Average Cached Tokens Sensor**: New sensor showing average cached tokens per request
  - Formula: `cached_tokens / successful_requests`
  - Helps track caching efficiency per agent
- **Cache Warming Status Sensor**: New sensor for agents with cache warming enabled
  - Shows warming status: "active", "warming", "inactive"
  - Attributes: last_warmup, next_warmup, warmup_count, warmup_failures, interval_minutes
- **AI Task Metrics**: AI Task entities now also have their own metric sensors
  - Average Response Time, Total Requests, Success Rate, Total Tokens
- Cache warming now tracks success/failure counts and timestamps
- Dispatcher signals changed from entry-level to subentry-level for better isolation

### v1.0.4 (2026-01-28) - API Key Reconfigure

**New Feature**

- Added reconfigure flow for parent entry to update API keys
- Go to Settings -> Integrations -> Smart Assist -> Configure to change API keys
- Both Groq and OpenRouter API keys can be updated without removing the integration

### v1.0.3 (2026-01-28) - API Key Storage Fix

**Bugfix**

- Fixed API key incorrectly being copied to subentry data during reconfigure
- This caused "Invalid API Key" errors after reconfiguring a conversation agent
- API keys are now correctly read from parent entry only

### v1.0.2 (2026-01-28) - Reliability Improvements

**HTTP Client Reliability Enhancements**

- Added granular timeouts (connect=10s, sock_connect=10s, sock_read=30s)
- Session auto-renewal after 4 minutes to prevent stale HTTP connections
- Explicit timeout error handling with separate exception handler
- Improved error logging: all failures now logged with attempt count
- Final failure always logged at ERROR level with full context

### v1.0.1 (2026-01-28) - Bugfixes

**Bugfixes**

- Fixed Media Player select_source for devices without SELECT_SOURCE feature
- Added legacy API key location fallback for config migrations
- Reduced 401 log level to DEBUG when fetching Groq models (expected behavior)
- Restored info.md for HACS repository description

### v1.0.0 (2026-01-28) - Initial Release

**Smart Assist** is a fast, LLM-powered smart home assistant for Home Assistant with automatic prompt caching.

#### Core Features

- **Groq Integration**: Direct Groq API with automatic prompt caching (2-hour TTL)
- **Natural Language Control**: Control your smart home with natural language
- **Unified Control Tool**: Single efficient tool for all entity types (lights, switches, climate, covers, media players, fans)
- **Parallel Tool Execution**: Execute multiple tool calls concurrently for faster responses
- **Full Streaming**: Real-time token streaming to TTS, even during tool execution
- **Prompt Caching**: ~90% cache hit rate with Groq for faster responses

#### Calendar Integration

- **Read Events**: Query upcoming events from all calendars
- **Create Events**: Create timed or all-day events with fuzzy calendar matching
- **Proactive Reminders**: Staged context injection (24h, 4h, 1h before events)

#### AI Task Platform

- **Automation Integration**: Use LLM in automations via ai_task.generate_data service
- **Background Tasks**: Summarize data, generate reports without user interaction
- **Full Tool Support**: All tools available in automation context

#### Performance and Telemetry

- **Cache Warming**: Optional periodic cache refresh for instant responses
- **Metrics Sensors**: Track token usage, response times, cache hit rates
  - Average Response Time (ms)
  - Request Count
  - Success Rate (%)
  - Token Usage
  - Cache Hits
  - Cache Hit Rate (%)

#### Additional Features

- **Web Search**: DuckDuckGo integration for real-time information
- **Multi-Language**: Supports any language (auto-detect from HA or custom)
- **Debug Logging**: Detailed logging for troubleshooting

#### Available Tools

| Tool                    | Description                                |
| ----------------------- | ------------------------------------------ |
| get_entities            | Query available entities by domain/area    |
| get_entity_state        | Get detailed entity state with attributes  |
| control                 | Unified control for all entity types       |
| run_scene               | Activate scenes                            |
| trigger_automation      | Trigger automations                        |
| get_calendar_events     | Query upcoming calendar events             |
| create_calendar_event   | Create new calendar events                 |
| get_weather             | Current weather information                |
| web_search              | DuckDuckGo web search                      |

#### Supported Models

| Model                             | Description                 |
| --------------------------------- | --------------------------- |
| llama-3.3-70b-versatile           | Llama 3.3 70B (Recommended) |
| openai/gpt-oss-120b               | GPT-OSS 120B                |
| openai/gpt-oss-20b                | GPT-OSS 20B (Faster)        |
| moonshotai/kimi-k2-instruct-0905  | Kimi K2                     |

#### Requirements

- Home Assistant 2024.1 or newer
- Python 3.12+
- Groq API key

---

## Roadmap

### Planned Features

#### v1.1.0 - Context and History

**Implemented in v1.1.0 (2026-01-30):**
- ~~Entity History Queries~~ - `get_entity_history` tool for querying historical states
- ~~Multi-Turn Improvements~~ - `RecentEntity` tracking with automatic context injection

| Feature | Description | Status |
| ------- | ----------- | ------ |
| ~~Entity History Queries~~ | "How was the temperature yesterday?", "When was the light last on?" | Done |
| ~~Multi-Turn Improvements~~ | Tracks recent entities after tool calls, injects `[Recent Entities]` context for pronoun resolution ("make it brighter" -> understands last light) | Done |
| Persistent Memory | Hybrid injection: Memory section (~50-100 tokens) injected AFTER Entity Index, BEFORE dynamic content. Stored in HA Storage (`.storage/smart_assist`). Contains: user preferences ("dim evening lighting"), learned patterns, named entities ("Anna=wife"). Rarely changes, preserves cache for static prefix. LLM recognizes and saves new preferences automatically. | Planned |

#### v1.2.0 - Reminders and Notifications

**Implemented:**
- ~~Voice Reminders~~ - Implemented in v1.0.23 (Timer with `command` parameter)
- ~~Scheduled Tasks~~ - Implemented in v1.0.23 (Timer with `command` parameter, e.g., "Turn off lights in 2 hours")
- ~~Universal Send Tool~~ - Implemented in v1.2.0 (`send` tool for notifications)

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| ~~Universal Send Tool~~ | `send` tool for delivering content (links, text) to notification targets. Supports all `notify.*` services (mobile_app, telegram, email, groups). LLM offers to send content, user specifies target. | ~~Done~~ |
| Proactive Notifications | LLM-triggered alerts based on entity state changes | Medium |

#### v1.3.0 - Media Enhancements

**Implemented:**
- ~~Playlist Support~~ - Implemented in v1.0.24 (Music Assistant Tool)
- ~~Media Queue~~ - Implemented in v1.0.24 (Music Assistant Tool)
- ~~TTS Announcements~~ - Use `tts.speak` service in automations after `ai_task.generate_data`

#### v1.4.0 - Vision and Camera Analysis

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Camera Image Analysis | "Who is at the door?" - Analyze doorbell/camera snapshots with vision LLM | High |
| Object Detection | "Is my car in the driveway?" - Check specific objects in camera view | Medium |
| Motion Summary | "What happened in the garage?" - Summarize recent camera activity | Medium |

#### v1.5.0 - Proactive Assistant

**Implemented:**
- ~~Morning Briefing~~ - Use `ai_task.generate_data` + `tts.speak` in a time-triggered automation

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Anomaly Alerts | "Your energy usage is unusually high today" - Proactive notifications | Medium |
| Weather Suggestions | "It will rain, should I close the windows?" - Context-aware hints | Low |

#### v1.6.0 - Advanced Control

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Natural Language Automations | "When I come home, turn on the lights" - Creates HA automation | High |
| Routine Creation | "Create a 'Good Night' routine" - Define multi-step sequences | Medium |
| Conditional Actions | "Turn off lights only if no one is home" - Smart conditionals | Medium |

#### Future Considerations

| Feature | Description | Effort |
| ------- | ----------- | ------ |
| Local LLM Support | Ollama integration as privacy-first alternative to cloud LLMs | Medium |
| RAG Integration | Search own documents, manuals, recipes with vector embeddings | High |
| Multi-Language Switching | "Spreche jetzt Deutsch" - Switch language mid-conversation | Low |
| Energy Dashboard | "How can I save energy?" - Consumption analysis with suggestions | Medium |
| ~~Spotify Deep Integration~~ | ~~Play by playlist name, liked songs, artist radio~~ - Implemented in v1.0.24 (Music Assistant) | ~~Medium~~ |
| Cancel Intent Handler | Custom handler for "Abbrechen"/"Cancel" that returns TTS confirmation instead of empty response (workaround for HA Core bug where HassNevermind leaves satellite hanging) | Low |

---

## Technology Stack

| Technology       | Version  | Purpose                    |
| ---------------- | -------- | -------------------------- |
| Python           | 3.12+    | Core language              |
| Home Assistant   | 2024.1+  | Smart home platform        |
| aiohttp          | 3.8.0+   | Async HTTP client          |
| Groq API         | latest   | LLM inference              |
| DuckDuckGo ddgs  | 7.0.0+   | Web search integration     |

## License

MIT License - see LICENSE for details.
