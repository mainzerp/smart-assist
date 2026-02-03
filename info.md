# Smart Assist

**Fast, LLM-powered smart home assistant for Home Assistant with dual provider support.**

Control your smart home with natural language. Supports **Groq API** for ultra-fast inference and **OpenRouter** for access to 200+ models (Claude, GPT-4, Llama, Mistral, etc.).

## Features

### Dual Provider Support

| Provider | Best For | Caching |
| -------- | -------- | ------- |
| **Groq** | Speed | Automatic prompt caching (2h TTL, ~90% hit rate) |
| **OpenRouter** | Model variety | Native caching for Anthropic models only |

> **Note**: Prompt caching works best with native provider APIs. Groq has automatic caching for all models. OpenRouter supports caching only for Anthropic models via `cache_control` headers.

### Core Features

- **Groq Integration**: Direct Groq API with automatic prompt caching (2-hour TTL)
- **OpenRouter Integration**: Access 200+ models (Claude, GPT-4, Llama, Mistral, Gemini, etc.)
- **Natural Language Control**: Talk to your smart home naturally
- **Unified Control Tool**: Single efficient tool for all entity types
- **Parallel Tool Execution**: Execute multiple tool calls concurrently
- **Full Streaming**: Real-time token streaming to TTS
- **Entity History Queries**: Query historical entity states
- **Multi-Turn Context**: Pronoun resolution across conversation turns

### Music Assistant Integration

- **Automatic Detection**: Detects Music Assistant when installed
- **Music Playback**: Play songs, albums, artists, playlists via voice
- **Radio Streaming**: Stream radio stations (TuneIn, Radio Browser)
- **Satellite-Aware**: Automatic player selection based on current satellite

### Voice Timers

- **Native Assist Timers**: Uses Home Assistant's built-in voice timer system
- **Satellite-Specific**: Timers are tied to the satellite where they were set
- **Custom Commands**: Set timers with custom callback messages

### Calendar Integration

- **Read Events**: Query upcoming events from all calendars
- **Create Events**: Create timed or all-day events
- **Proactive Reminders**: Staged context injection (24h, 4h, 1h before events)

### AI Task Platform

- **Automation Integration**: Use LLM in automations via `ai_task.generate_data` service
- **Background Tasks**: Summarize data, generate reports without user interaction

### Additional Features

- **Web Search**: DuckDuckGo integration for real-time information
- **Multi-Language**: Supports any language
- **Metrics/Telemetry**: Track token usage, response times, cache hit rates

## Requirements

- Home Assistant 2024.1 or newer
- Python 3.12+
- Groq API key ([get one here](https://console.groq.com/keys)) or OpenRouter API key ([get one here](https://openrouter.ai/keys))

## Installation

1. Open HACS in Home Assistant
2. Click the three dots menu -> Custom repositories
3. Add: `https://github.com/mainzerp/smart-assist`
4. Select category: Integration
5. Search for "Smart Assist" and install
6. Restart Home Assistant

## Documentation

See [README.md](https://github.com/mainzerp/smart-assist) for full documentation.
