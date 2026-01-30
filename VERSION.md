# Smart Assist - Version History

## Current Version

| Component    | Version | Date       |
| ------------ | ------- | ---------- |
| Smart Assist | 1.0.30  | 2026-01-30 |

## Version History

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

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Entity History Queries | "How was the temperature yesterday?", "When was the light last on?" | High |
| Multi-Turn Improvements | Hybrid approach: ConversationContextTracker + automatic System Prompt injection. Tracks recent entities/rooms after tool calls, injects context for pronoun resolution ("make it brighter" -> understands last light). No new tools needed, minimal token overhead. | High |
| Persistent Memory | Hybrid injection: Memory section (~50-100 tokens) injected AFTER Entity Index, BEFORE dynamic content. Stored in HA Storage (`.storage/smart_assist`). Contains: user preferences ("dim evening lighting"), learned patterns, named entities ("Anna=wife"). Rarely changes, preserves cache for static prefix. LLM recognizes and saves new preferences automatically. | Medium |

#### v1.2.0 - Reminders and Notifications

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Voice Reminders | "Remind me in 10 minutes to check the oven" with proactive TTS | High |
| Scheduled Tasks | "Turn off the lights at 11pm" without creating HA automations | Medium |
| Proactive Notifications | LLM-triggered alerts based on entity state changes | Medium |

#### v1.3.0 - Media Enhancements

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Playlist Support | Spotify/local media playlist control by name | Medium |
| TTS Announcements | "Announce dinner is ready in all rooms" | Medium |
| Media Queue | "Add this song to the queue", "What's playing next?" | Low |

#### v1.4.0 - Vision and Camera Analysis

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Camera Image Analysis | "Who is at the door?" - Analyze doorbell/camera snapshots with vision LLM | High |
| Object Detection | "Is my car in the driveway?" - Check specific objects in camera view | Medium |
| Motion Summary | "What happened in the garage?" - Summarize recent camera activity | Medium |

#### v1.5.0 - Proactive Assistant

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Morning Briefing | Automatic daily summary (calendar, weather, reminders) via TTS | High |
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
| Spotify Deep Integration | Play by playlist name, liked songs, artist radio | Medium |

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
