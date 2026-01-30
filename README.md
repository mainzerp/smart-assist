# Smart Assist

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub Release](https://img.shields.io/github/release/mainzerp/smart-assist.svg)](https://github.com/mainzerp/smart-assist/releases)

**Fast, LLM-powered smart home assistant for Home Assistant with automatic Prompt Caching.**

Control your smart home with natural language. Uses **Groq API** or **OpenRouter** for ultra-fast inference with automatic prompt caching, achieving **~90% cache hit rates** and response times under 500ms.

## Features

### Core Features

- **Groq Integration**: Direct Groq API with automatic prompt caching (2-hour TTL)
- **OpenRouter Integration**: Access 200+ models via OpenRouter API
- **Natural Language Control**: Talk to your smart home naturally
- **Unified Control Tool**: Single efficient tool for all entity types (lights, switches, climate, covers, media players, fans)
- **Parallel Tool Execution**: Execute multiple tool calls concurrently for faster responses
- **Full Streaming**: Real-time token streaming to TTS, even during tool execution
- **Entity History Queries**: Query historical entity states ("How was the temperature yesterday?")
- **Multi-Turn Context**: Pronoun resolution across conversation turns ("it", "that", "the same one")

### Music Assistant Integration

- **Automatic Detection**: Detects Music Assistant when installed
- **Music Playback**: Play songs, albums, artists, playlists via voice
- **Radio Streaming**: Stream radio stations (TuneIn, Radio Browser)
- **Satellite-Aware**: Automatic player selection based on which satellite you're talking to

#### Satellite-to-Player Mapping

Smart Assist automatically detects which satellite you're speaking to and injects it into the context. To enable automatic player selection, add a mapping to your **User System Prompt** (in the integration configuration):

```
Satellite to Media Player Mappings:
- assist_satellite.satellite_kitchen -> media_player.kitchen_speaker
- assist_satellite.satellite_living_room -> media_player.living_room_sonos
- assist_satellite.satellite_bedroom -> media_player.bedroom_speaker
```

Now when you say "Play some jazz" in the kitchen, the music will automatically play on the kitchen speaker.

### Voice Timers

- **Native Assist Timers**: Uses Home Assistant's built-in voice timer system
- **Satellite-Specific**: Timers are tied to the satellite where they were set
- **Custom Commands**: Set timers with custom callback messages

### Calendar Integration

- **Read Events**: Query upcoming events from all calendars
- **Create Events**: Create timed or all-day events with fuzzy calendar matching
- **Proactive Reminders**: Staged context injection (24h, 4h, 1h before events)

### AI Task Platform

- **Automation Integration**: Use LLM in automations via `ai_task.generate_data` service
- **Background Tasks**: Summarize data, generate reports without user interaction
- **Full Tool Support**: All tools available in automation context

### Performance

- **Automatic Prompt Caching**: ~90% cache hit rate with Groq
- **Cache Warming**: Optional periodic cache refresh for instant responses
- **Metrics/Telemetry**: Track token usage, response times, cache hit rates

### Additional Features

- **Web Search**: DuckDuckGo integration for real-time information
- **Multi-Language**: Supports any language (auto-detect from HA or custom)
- **Debug Logging**: Detailed logging for troubleshooting

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu (top right) -> Custom repositories
3. Add this repository URL: `https://github.com/mainzerp/smart-assist`
4. Select category: Integration
5. Click Add, then search for "Smart Assist" and install
6. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/smart_assist` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services**
2. Click **Add Integration**
3. Search for "Smart Assist"
4. Follow the setup wizard:
   - Select LLM provider (Groq or OpenRouter)
   - Enter your API key ([Groq](https://console.groq.com/keys) or [OpenRouter](https://openrouter.ai/keys))
   - Select your preferred model
   - Configure behavior and caching settings

## Configuration Options

### Model Settings

| Option | Description | Default |
| ------ | ----------- | ------- |
| Model | Groq model ID | openai/gpt-oss-120b |
| Temperature | Response creativity (0-1) | 0.5 |
| Max Tokens | Maximum response length | 500 |

### Behavior Settings

| Option | Description | Default |
| ------ | ----------- | ------- |
| Language | Response language (empty = auto-detect from HA) | Auto |
| Exposed Only | Use only exposed entities | true |
| Confirm Critical | Confirm locks/alarms before action | true |
| Max History | Conversation history length | 10 |
| Web Search | Enable DuckDuckGo search | true |
| Calendar Context | Inject proactive calendar reminders | false |

### Caching Settings

| Option | Description | Default |
| ------ | ----------- | ------- |
| Prompt Caching | Enable prompt caching | true |
| Cache Warming | Periodic cache refresh | false |
| Refresh Interval | Cache refresh interval (minutes) | 4 |

### Advanced Settings

| Option | Description | Default |
| ------ | ----------- | ------- |
| Clean Responses | Remove markdown for TTS | false |
| Ask Follow-up | Assistant asks clarifying questions | true |
| Debug Logging | Enable verbose logging | false |
| System Prompt | Custom instructions for assistant | - |

## Prompt Caching

Smart Assist uses Groq's **automatic prompt caching** to reduce latency and costs.

### How It Works

1. **Prefix Matching**: Groq caches the prefix of your prompt (system prompt, tools, entity index)
2. **Automatic**: No configuration needed - caching happens automatically
3. **2-Hour TTL**: Cached data expires after 2 hours without use
4. **~90% Hit Rate**: Typical cache hit rates in production

### Cache Statistics

The integration provides sensors for monitoring cache performance:

| Sensor | Description |
| ------ | ----------- |
| Cache Hit Rate | Percentage of tokens served from cache |
| Cache Hits | Count of requests with cache hits |
| Response Time | Average LLM response time |
| Token Usage | Total tokens consumed |

### Cache Warming

Enable cache warming to keep the cache "warm" for instant responses. This sends periodic minimal requests to prevent cache expiration.

**Cost**: Minimal (~1 request per interval, ~$0.01/day with 10-minute interval)

## AI Task Platform (Automations)

Smart Assist registers as an `ai_task` platform for use in automations:

```yaml
service: ai_task.generate_data
target:
  entity_id: ai_task.smart_assist_task
data:
  task_type: generate_data
  instructions: "Summarize all lights that are currently on"
```

**Configuration:**

- **Task System Prompt**: Custom instructions for background tasks
- **Task Prompt Caching**: Disabled by default (tasks are not time-critical)
- **Task Cache Warming**: Disabled by default

## Tools

Smart Assist provides these tools to the LLM:

| Tool | Description |
| ---- | ----------- |
| `get_entities` | Query available entities by domain, area, or name |
| `get_entity_state` | Get detailed entity state with attributes |
| `control` | Unified control for lights, switches, climate, covers, media players, fans |
| `run_scene` | Activate scenes |
| `trigger_automation` | Trigger automations |
| `timer` | Set, cancel, or list voice timers (native Assist timers) |
| `music_assistant` | Play music/radio via Music Assistant (auto-detected) |
| `get_calendar_events` | Query upcoming calendar events |
| `create_calendar_event` | Create new calendar events (fuzzy calendar matching) |
| `get_weather` | Current weather information |
| `web_search` | DuckDuckGo web search |

## Supported Models

### Groq Models

| Model | Description |
| ----- | ----------- |
| `openai/gpt-oss-120b` | GPT-OSS 120B - Recommended |
| `openai/gpt-oss-20b` | GPT-OSS 20B - Faster, smaller |
| `llama-3.3-70b-versatile` | Llama 3.3 70B |
| `moonshotai/kimi-k2-instruct-0905` | Kimi K2 |

See [Groq Models](https://console.groq.com/docs/models) for the full list.

### OpenRouter Models

Access 200+ models including:
- Claude 3.5 Sonnet
- GPT-4o
- Gemini Pro
- And many more

See [OpenRouter Models](https://openrouter.ai/models) for the full list.

## Requirements

- Home Assistant 2024.1 or newer
- Python 3.12+
- Groq API key ([get one here](https://console.groq.com/keys)) or OpenRouter API key ([get one here](https://openrouter.ai/keys))

## Troubleshooting

### Enable Debug Logging

Enable debug logging in Advanced settings to see:

- Message structure per LLM iteration
- Cache hit/miss statistics
- Tool execution details
- Entity control actions

### Common Issues

**Low cache hit rate?**

- Groq uses load-balanced servers with separate caches
- Cache hits are not 100% guaranteed but typically ~90%
- Ensure consistent tool usage across requests

**Slow responses?**

- Check cache hit rate in sensors
- Enable cache warming for consistent performance
- Verify Groq API status

## Version History

See [VERSION.md](VERSION.md) for detailed changelog.

**Current Version**: 1.0.30

## License

MIT License - see [LICENSE](LICENSE) for details.
