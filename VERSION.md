# Smart Assist - Version History

## Current Version

| Component    | Version | Date       |
| ------------ | ------- | ---------- |
| Smart Assist | 1.0.6   | 2026-01-29 |

## Version History

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

#### Future Considerations

| Feature | Description | Effort |
| ------- | ----------- | ------ |
| Local LLM Support | Ollama integration as privacy-first alternative to Groq | Medium |
| Natural Language Automations | "When I come home, turn on the lights" creates HA automation | High |
| Multimodal Vision | Camera image analysis: "Who is at the door?" | High |
| Weather-based Suggestions | Proactive hints: "It will rain, should I close the windows?" | Low |
| Energy Optimization | "How can I save energy?" with consumption analysis | Medium |
| RAG Integration | Search own documents, manuals, recipes | High |

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
