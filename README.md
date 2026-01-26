# Smart Assist

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub Release](https://img.shields.io/github/release/mainzerp/smart-assist.svg)](https://github.com/mainzerp/smart-assist/releases)

**LLM-powered smart home assistant for Home Assistant using OpenRouter.**

Control your smart home with natural language. Access 200+ AI models via OpenRouter including Claude, GPT-4, Gemini, Llama, and more.

## Features

- **Natural Language Control**: Talk to your smart home naturally
- **OpenRouter Integration**: Access to 200+ AI models via single API
- **Provider Selection**: Choose specific providers for prompt caching support
- **Unified Control Tool**: Single efficient tool for all entity types
- **Full Streaming**: Real-time token streaming even during tool execution
- **Token Optimization**: Entity index caching, prompt caching, minimal context
- **Metrics/Telemetry**: Track token usage, response times, cache hit rates
- **Cache Warming**: Optional periodic cache refresh for instant responses
- **Debug Logging**: UI toggle for verbose logging in Home Assistant logs
- **Multi-Language**: English and German UI support

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
   - Enter your OpenRouter API key ([get one here](https://openrouter.ai/keys))
   - Select your preferred LLM model
   - Choose a provider (required for prompt caching)
   - Configure behavior and caching settings

## Configuration Options

### Model Settings

| Option | Description | Default |
|--------|-------------|---------|
| Model | Any OpenRouter model ID | GPT-OSS 120B |
| Provider | Specific provider for routing | Groq |
| Temperature | Response creativity (0-1) | 0.3 |
| Max Tokens | Maximum response length | 500 |

### Behavior Settings

| Option | Description | Default |
|--------|-------------|---------|
| Language | Response language | Auto |
| Exposed Only | Use only exposed entities | true |
| Confirm Critical | Confirm locks/alarms before action | true |
| Max History | Conversation history length | 10 |
| Web Search | Enable DuckDuckGo search | true |
| Quick Actions | Bypass LLM for simple commands | true |

### Caching Settings

| Option | Description | Default |
|--------|-------------|---------|
| Prompt Caching | Enable prompt caching | true |
| Extended TTL | 1 hour cache (provider-dependent) | false |
| Cache Warming | Periodic cache refresh | false |
| Refresh Interval | Cache refresh interval (min) | 4 |

### Advanced Settings

| Option | Description | Default |
|--------|-------------|---------|
| Clean Responses | Remove markdown for TTS | false |
| Ask Follow-up | Assistant asks clarifying questions | true |
| Debug Logging | Enable verbose logging | false |
| System Prompt | Custom instructions for assistant | - |

## Prompt Caching

Smart Assist supports OpenRouter's prompt caching to reduce latency and costs. The system prompt, entity index, and tools are cached and reused across requests.

### Provider Selection for Caching

**Important**: To use prompt caching, you must select a specific provider (not "Automatic"). 

See the [OpenRouter Prompt Caching documentation](https://openrouter.ai/docs/guides/best-practices/prompt-caching) for:
- List of providers that support prompt caching
- Cache TTL information per provider
- Cost savings details

When you select a model, Smart Assist shows only providers that offer that model. Select a caching-compatible provider from this list if you want to use prompt caching.

### Cache Warming

Enable cache warming to periodically refresh the cache with a minimal request. This keeps the cache "warm" for instant responses but incurs additional API costs (~1 request per interval).

## Tools

Smart Assist provides these tools to the LLM:

| Tool | Description |
|------|-------------|
| `get_entities` | Query available entities by domain, area, or name |
| `get_entity_state` | Get detailed entity state with attributes |
| `control` | Unified control for all entity types |
| `run_scene` | Activate scenes |
| `trigger_automation` | Trigger automations |
| `get_weather` | Current weather information |
| `web_search` | DuckDuckGo web search |

## Requirements

- Home Assistant 2024.1 or newer
- Python 3.12+
- OpenRouter API key

## Troubleshooting

Enable debug logging in the Advanced settings to see detailed logs in Home Assistant. This logs:
- Message processing details
- LLM request/response information
- Tool execution and results
- Entity control actions

## License

MIT License - see [LICENSE](LICENSE) for details.
