# Smart Assist

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub Release](https://img.shields.io/github/release/mainzerp/smart-assist.svg)](https://github.com/mainzerp/smart-assist/releases)

**Fast, LLM-powered smart home assistant for Home Assistant with automatic Prompt Caching.**

Control your smart home with natural language. Supports **Groq API** for ultra-fast inference, **OpenRouter** for access to 200+ models, and **Ollama** for local private inference.

## Features

### Core Features

- **Triple Provider Support**: Choose between Groq, OpenRouter, or Ollama (local/private)
- **Groq Integration**: Direct Groq API with automatic prompt caching (2-hour TTL, ~90% cache hit rate)
- **OpenRouter Integration**: Access to 200+ models including Claude, GPT-4, Llama, Mistral, and more
- **Ollama Integration**: Run LLMs locally on your own hardware with full privacy
- **Natural Language Control**: Talk to your smart home naturally
- **Unified Control Tool**: Single efficient tool for all entity types (lights, switches, climate, covers, media players, fans)
- **Parallel Tool Execution**: Execute multiple tool calls concurrently for faster responses
- **Full Streaming**: Real-time token streaming to TTS, even during tool execution
- **Entity History Queries**: Query historical entity states ("How was the temperature yesterday?")
- **Multi-Turn Context**: Pronoun resolution across conversation turns ("it", "that", "the same one")
- **Smart Discovery Mode**: On-demand entity discovery via tools instead of full entity index in prompt (saves tokens)
- **Agent Memory**: LLM learns from interactions and saves observations for future use

### Music Assistant Integration

- **Automatic Detection**: Detects Music Assistant when installed
- **Music Playback**: Play songs, albums, artists, playlists via voice
- **Radio Streaming**: Stream radio stations (TuneIn, Radio Browser)
- **Satellite-Aware**: Automatic player selection based on which satellite you're talking to

#### Satellite-to-Player Mapping

Smart Assist automatically detects which satellite you're speaking to and injects it into the context. To enable automatic player selection, add a mapping to your **User System Prompt** (in the integration configuration):

```text
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
- **Per-User Filtering**: Calendar reminders filtered by recognized user identity via configurable mappings

#### Calendar Mappings (Optional)

By default, all users see reminders from all calendars. To filter reminders per user, add a `Calendar Mappings:` block to your **User System Prompt**:

```text
Calendar Mappings:
- calendar.anna_privat -> Anna
- calendar.patric_arbeit -> Patric
- calendar.patric_privat -> Patric
- calendar.familie -> shared
- calendar.feiertage -> shared
```

**Behavior:**
- **User recognized** (e.g., Anna): Sees only her own calendars + calendars marked `shared`
- **User not recognized**: Sees all calendars (fallback)
- **Calendars not listed** in the mapping: Treated as `shared` (visible to everyone)

### Send Content to Devices

- **Universal Send Tool**: Send links, text, or messages to any notification target
- **Mobile Apps**: Companion App notifications with clickable URLs
- **Other Services**: Telegram, email, groups, or any HA notify service
- **Smart Matching**: Say "send it to Patrics phone" and it finds `mobile_app_patrics_iphone`

### Memory & Personalization

- **Persistent User Memory**: LLM remembers user preferences, named entities, patterns, and instructions across sessions
- **Multi-User Identity**: 5-layer user identification (HA auth, session switch, satellite mapping, presence heuristic, fallback)
- **Memory Tool**: LLM can save, recall, update, and delete memories via the `memory` tool
- **Per-User Profiles**: Up to 100 memories per user, 50 global memories, LRU eviction
- **Management UI**: Rename users, merge profiles, delete individual memories from the dashboard
- **Agent Memory (Auto-Learning)**: LLM saves its own observations and patterns (independent of user)
- **Auto-Expire**: Agent memories older than 30 days with low usage are automatically cleaned up

### Cancel Intent Handler

- **Satellite Fix**: Prevents voice satellites from hanging when users say "Cancel", "Abbrechen", or "Nevermind"
- **LLM-Powered**: Generates a brief, natural TTS confirmation (e.g., "Alles klar.") instead of empty silence
- **Per-Agent Selection**: Choose which conversation agent handles cancel intents (Settings > Integrations > Smart Assist > Agent > Reconfigure > "Use as cancel intent handler")
- **Global Toggle**: Enable/disable the entire feature under Settings > Integrations > Smart Assist > Configure
- **Auto-Fallback**: If no agent is explicitly selected, the first available agent is used

### Dashboard & UI

- **Custom Sidebar Panel**: Admin-only panel in HA sidebar with `mdi:brain` icon
- **Overview Tab**: Total requests, success rate, response time, tokens, cache hit rate, registered tools
- **Memory Tab**: Browse user profiles, view/manage individual memories, rename/merge/delete users
- **Calendar Tab**: Upcoming events with reminder status badges (upcoming/pending/announced/passed)
- **History Tab**: Per-request history log with token usage, response times, tool calls, and success/error status; tool usage analytics with call frequency, success rates, and average execution times
- **Prompt Tab**: View the full system prompt and user custom instructions for each agent; displays agent name, prompt lengths, and formatted sections
- **Real-Time Updates**: WebSocket API with subscription for live metric updates
- **Theme Integration**: Adapts to HA light/dark mode via CSS custom properties

#### Dashboard Data Flow

- **Hot-path Metrics via Push**: Subscription updates focus on lightweight metrics refreshes
- **Tab-Scoped Heavy Data**: Calendar data is fetched via dedicated endpoint when Calendar tab is active (with short cache TTL)
- **Push/Poll Coordination**: Auto-refresh polling backs off while subscription is healthy and resumes as fallback on degraded push/reconnect
- **Stale-Data UX**: Last valid snapshot stays visible on refresh errors with a non-blocking warning banner
- **History Analytics Caching**: Tool analytics and summary stats are cached server-side and invalidated on add/clear/prune

Example workflow:

1. Ask a question that requires web search
2. LLM offers: "Want me to send you the links?"
3. Say: "Yes, to my phone" or "Send it to Telegram"
4. Receive notification with clickable links

#### Device Name Mappings (Optional)

The send tool uses fuzzy matching to automatically find the right notification service based on the device name. **Mappings are not required** - the tool will try to match phrases like "my phone" to services like `mobile_app_pixel_8a` automatically.

However, for more reliable matching (especially with ambiguous names or multiple devices), you can add explicit mappings to your **User System Prompt** (in the integration configuration):

```text
Device to Notification Service Mappings:
- patrics phone or my phone -> notify.mobile_app_pixel_8a
- lauras iphone or lauras phone -> notify.mobile_app_lauras_iphone
- telegram -> notify.telegram
- family group -> notify.family_group
```

When you add these mappings, the LLM will use them directly from the system prompt context, making device selection more reliable.

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
   - **Step 1**: Choose your LLM provider (Groq, OpenRouter, or Ollama)
   - **Step 2**: Enter your API key
     - Groq: [Get API key](https://console.groq.com/keys)
     - OpenRouter: [Get API key](https://openrouter.ai/keys)
5. Add a **Conversation Agent** or **AI Task** via the integration's subentries
6. If both API keys are configured, you can create agents with different providers

## Configuration Options

### Provider Settings

| Provider | Best For | Features |
| -------- | -------- | -------- |
| Groq | Speed | Ultra-fast inference, automatic caching, ~90% cache hit rate |
| OpenRouter | Model Variety | 200+ models, provider routing, Claude/GPT-4/Llama access |
| Ollama | Privacy/Local | No cloud, no API key, runs on your hardware, full data privacy |

### Ollama Settings

When using Ollama, you can configure these additional settings in the reconfigure dialog:

| Option | Description | Default |
| ------ | ----------- | ------- |
| Context Window Size | Number of tokens the model can see (higher = more context, more RAM) | 8192 |
| Keep Model Loaded | How long to keep the model in memory after a request | Forever |
| Request Timeout | Maximum time to wait for Ollama to respond | 120s |

> **Note**: Ollama does not expose cache statistics via API. Cache-related sensors (Cache Hit Rate, Cached Tokens) will show 0 for Ollama. This is a limitation of the Ollama API, not Smart Assist. Ollama uses an internal KV cache that works automatically but doesn't report metrics.

### Model Settings

| Option | Description | Default |
| ------ | ----------- | ------- |
| Model | LLM model ID (fetched dynamically from provider) | llama-3.3-70b-versatile |
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
| Request History Content | Store request/response/tool argument content in history (disable = metadata only) | true |
| History Retention (days) | Auto-prune request history entries older than this limit | 30 |
| History Redact Patterns | Comma/newline-separated regex or text patterns replaced with [REDACTED] before persistence | (empty) |
| Entity Discovery Mode | Entity lookup strategy: "Full Index" (all in prompt) or "Smart Discovery" (on-demand via tools) | Full Index |

### Caching Settings

| Option | Description | Default |
| ------ | ----------- | ------- |
| Cache Warming | Periodic cache refresh | false |
| Refresh Interval | Cache refresh interval (minutes) | 4 |

> **Note**: Prompt Caching is always enabled automatically by Groq. There is no option to disable it.

### Advanced Settings

| Option | Description | Default |
| ------ | ----------- | ------- |
| Clean Responses | Remove markdown for TTS | false |
| Ask Follow-up | Assistant asks clarifying questions | true |
| Debug Logging | Enable verbose logging | false |
| Cancel Intent Handler | Use LLM to respond to cancel/nevermind (fixes satellite hang) | true |
| System Prompt | Custom instructions for assistant | - |

## Prompt Caching

Smart Assist supports prompt caching to reduce latency and costs.

### Provider Caching Comparison

| Provider | Caching Type | TTL | Models |
| -------- | ------------ | --- | ------ |
| **Groq** | Automatic | 2 hours | All models |
| **OpenRouter** | Explicit | 5 min / 1 hour | some models |

> **Recommendation**: For best caching performance, use **Groq** as your provider.
### How It Works (Groq)

1. **Prefix Matching**: Groq caches the prefix of your prompt (system prompt, tools, entity index)
2. **Automatic**: No configuration needed - caching happens automatically

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

**Cost**: Approximately $0.10/day with ~3,500 token prompts and 10-minute refresh interval (144 requests/day at Groq pricing).

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

### Structured Output (`task.structure`)

`ai_task.generate_data` supports schema-constrained structured output for automation-safe data contracts.
When `task.structure` is present, Smart Assist validates the generated JSON locally before returning it.

Example: return a weather decision object

```yaml
service: ai_task.generate_data
target:
  entity_id: ai_task.smart_assist_task
data:
  task_type: generate_data
  instructions: "Check weather and decide if windows should stay open"
  task:
    structure:
      type: object
      properties:
        keep_windows_open:
          type: boolean
        reason:
          type: string
      required: [keep_windows_open, reason]
      additionalProperties: false
```

Example: return an array of entities to switch off

```yaml
service: ai_task.generate_data
target:
  entity_id: ai_task.smart_assist_task
data:
  task_type: generate_data
  instructions: "List only currently-on lights in the house"
  task:
    structure:
      type: object
      properties:
        entities:
          type: array
          items:
            type: string
      required: [entities]
      additionalProperties: false
```

If the model returns invalid JSON or schema-mismatched data, Smart Assist returns a concise localized error string in `data`.

**Configuration:**

- **Task System Prompt**: Custom instructions for background tasks
- **Tool Max Retries**: Maximum retry attempts for failed tool calls per request
- **Tool Latency Budget (ms)**: Per-tool timeout budget in milliseconds
- **Task Prompt Caching**: Disabled by default (tasks are not time-critical)
- **Task Cache Warming**: Disabled by default

## Tools

Smart Assist provides these tools to the LLM:

| Tool | Description |
| ---- | ----------- |
| `get_entities` | Query available entities by domain, area, or name |
| `get_entity_state` | Get detailed entity state with attributes |
| `get_entity_history` | Query historical entity states |
| `control` | Unified control for lights, switches, climate, covers, media players, fans |
| `run_scene` | Activate scenes |
| `trigger_automation` | Trigger automations |
| `timer` | Set, cancel, or list voice timers (native Assist timers) |
| `music_assistant` | Play music/radio via Music Assistant (auto-detected) |
| `get_calendar_events` | Query upcoming calendar events |
| `create_calendar_event` | Create new calendar events (fuzzy calendar matching) |
| `get_weather` | Current weather information |
| `web_search` | DuckDuckGo web search |
| `send` | Send links, text, or messages to any notification target |
| `memory` | Save, recall, update, delete user/global/agent memories and switch user identity |
| `await_response` | Keep microphone open for follow-up questions |

## Supported Models

### Groq Models

| Model | Description |
| ----- | ----------- |
| `openai/gpt-oss-120b` | GPT-OSS 120B - Recommended |
| `openai/gpt-oss-20b` | GPT-OSS 20B - Faster, smaller |
| `llama-3.3-70b-versatile` | Llama 3.3 70B |
| `moonshotai/kimi-k2-instruct-0905` | Kimi K2 |

See [Groq Models](https://console.groq.com/docs/models) for the full list.

## Requirements

- Home Assistant 2024.1 or newer
- Python 3.12+
- At least one LLM provider:
  - Groq API key ([get one here](https://console.groq.com/keys))
  - OpenRouter API key ([get one here](https://openrouter.ai/keys))
  - Ollama running locally (no API key needed)

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

## License

MIT License - see [LICENSE](LICENSE) for details.
