# Smart Assist - Version History

## Current Version

| Component    | Version | Date       |
| ------------ | ------- | ---------- |
| Smart Assist | 1.0.0   | 2026-01-28 |

## Version History

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
