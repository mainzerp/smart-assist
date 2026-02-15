# Smart Assist

**Fast, LLM-powered smart home assistant for Home Assistant with triple provider support.**

Control your smart home with natural language. Supports **Groq API** for ultra-fast inference, **OpenRouter** for access to 200+ models, and **Ollama** for local private inference.

## Features

### Triple Provider Support

| Provider | Best For | Caching |
| -------- | -------- | ------- |
| **Groq** | Speed | Automatic prompt caching |
| **OpenRouter** | Model variety | Caching for some models |
| **Ollama** | Privacy/Local | Internal KV cache (no metrics exposed) |

> **Note**: Ollama does not expose cache statistics via API. Cache-related sensors will show 0 for Ollama. This is a limitation of the Ollama API, not Smart Assist.

### Core Features

- **Groq Integration**: Direct Groq API with automatic prompt caching (2-hour TTL)
- **OpenRouter Integration**: Access 200+ models
- **Ollama Integration**: Run LLMs locally with full privacy
- **Natural Language Control**: Talk to your smart home naturally
- **Unified Control Tool**: Single efficient tool for all entity types
- **Parallel Tool Execution**: Execute multiple tool calls concurrently
- **Full Streaming**: Real-time token streaming to TTS
- **Entity History Queries**: Query historical entity states
- **Multi-Turn Context**: Pronoun resolution across conversation turns
- **Smart Discovery Mode**: On-demand entity discovery via tools (saves tokens)
- **Agent Memory**: LLM learns from interactions and saves observations for future use

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
- **Per-User Filtering**: Calendar reminders filtered by user identity via `Calendar Mappings:` in the User System Prompt

### Send Content to Devices

- **Universal Send Tool**: Send links, text, or messages to any notification target
- **Mobile Apps**: Companion App notifications with clickable URLs
- **Smart Matching**: Fuzzy device name matching for reliable delivery

### Memory & Personalization

- **Persistent User Memory**: Remembers preferences, facts, and instructions across sessions
- **Multi-User Identity**: 5-layer identification (HA auth, session switch, satellite mapping, presence, fallback)
- **Memory Tool**: LLM can save, recall, update, and delete memories
- **Agent Memory**: LLM saves its own observations and patterns, auto-expires stale entries after 30 days

### Cancel Intent Handler

- **Satellite Fix**: Prevents voice satellites from hanging on cancel/nevermind
- **LLM-Powered**: Generates natural TTS confirmation instead of empty silence
- **Per-Agent Selection**: Choose which agent handles cancel intents in the agent's settings
- **Global Toggle**: Enable/disable under Settings > Integrations > Smart Assist > Configure

### Dashboard & UI

- **Custom Sidebar Panel**: Admin-only panel with overview, memory, calendar, history, and prompt tabs
- **Memory Management**: Rename users, merge profiles, delete individual memories
- **History & Analytics**: Per-request history log with token usage, tool calls, and tool usage analytics
- **Prompt Preview**: View full system prompt and custom instructions for each agent
- **Real-Time Updates**: WebSocket API with live metric subscription

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
- At least one LLM provider:
  - Groq API key ([get one here](https://console.groq.com/keys))
  - OpenRouter API key ([get one here](https://openrouter.ai/keys))
  - Ollama running locally (no API key needed)

## Installation

1. Open HACS in Home Assistant
2. Click the three dots menu -> Custom repositories
3. Add: `https://github.com/mainzerp/smart-assist`
4. Select category: Integration
5. Search for "Smart Assist" and install
6. Restart Home Assistant

## Documentation

See [README.md](https://github.com/mainzerp/smart-assist) for full documentation.
