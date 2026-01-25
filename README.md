# Smart Assist

[![Validate](https://github.com/YOUR_USERNAME/smart-assist/actions/workflows/validate.yml/badge.svg)](https://github.com/YOUR_USERNAME/smart-assist/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration that connects LLMs (via OpenRouter) with Home Assistant to create an intelligent smart home assistant.

## Features

- **LLM-Powered Conversations**: Natural language control of your smart home
- **Assist Pipeline Integration**: Works with Home Assistant's native voice assistants
- **OpenRouter Support**: Access to Claude, GPT-4, Gemini, Llama, and more
- **Provider Selection**: Choose specific providers for guaranteed prompt caching
- **Unified Control Tool**: Single efficient tool for all entity types
- **Token Optimization**: Entity index caching, prompt caching, minimal context
- **Full Streaming**: Real-time token streaming even during tool execution
- **Retry Logic**: Automatic retry with exponential backoff for API failures
- **Metrics/Telemetry**: Track token usage, response times, cache hit rates
- **Cache Warming**: Optional periodic cache refresh for instant responses
- **Quick Actions**: Bypass LLM for simple commands (optional)
- **Multi-Language**: English and German support

## Installation

### HACS (Recommended)

1. Add this repository to HACS as a custom repository
2. Search for "Smart Assist" in HACS
3. Install the integration
4. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/smart_assist` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services**
2. Click **Add Integration**
3. Search for "Smart Assist"
4. Follow the setup wizard:
   - Enter your OpenRouter API key
   - Select your preferred LLM model and provider
   - Configure behavior settings (caching, quick actions, etc.)
   - Customize the system prompt

## Usage

Once configured, Smart Assist will appear as a conversation agent in Home Assistant:

- Use it with voice assistants (ESPHome Voice, etc.)
- Use the Assist dialog in the Home Assistant app
- Use any Assist-compatible frontend

### Example Commands

- "Turn off the living room lights"
- "Set the thermostat to 22 degrees"
- "What's the temperature in the bedroom?"
- "Activate the movie night scene"
- "Search for tomorrow's weather forecast"

## Configuration Options

### Model Settings

| Option | Description | Default |
|--------|-------------|---------|
| Model | LLM model to use | Claude 3 Haiku |
| Provider | Specific provider (for caching) | Automatic |
| Temperature | Response creativity (0-1) | 0.3 |
| Max Tokens | Maximum response length | 500 |

### Behavior Settings

| Option | Description | Default |
|--------|-------------|---------|
| Language | Response language | English |
| Exposed Only | Use only exposed entities | true |
| Confirm Critical | Confirm locks/alarms | true |
| Max History | Conversation history length | 10 |
| Web Search | Enable DuckDuckGo search | true |
| Quick Actions | Bypass LLM for simple commands | true |

### Caching Settings

| Option | Description | Default |
|--------|-------------|---------|
| Prompt Caching | Enable prompt caching | true |
| Extended TTL | 1 hour cache (Anthropic only) | false |
| Cache Warming | Periodic cache refresh | false |
| Refresh Interval | Cache refresh interval (min) | 4 |

**Note**: Cache Warming incurs additional API costs (~1 request per interval).

## Prompt Caching

Smart Assist uses OpenRouter's prompt caching to reduce latency and costs:

```
CACHED (identical every request):
- System Prompt (~500 tokens)
- User Prompt (~50 tokens)
- Entity Index (~2000 tokens)

DYNAMIC (changes every request):
- Current States (~200 tokens)
- Conversation History (~500 tokens)
- User Message (~20 tokens)
```

### Provider-Specific Caching

| Provider | Cache Support | TTL |
|----------|---------------|-----|
| Anthropic | Explicit (cache_control) | 5 min / 1 hour |
| OpenAI | Automatic | ~1 hour |
| Google | Implicit | 3-5 min |

When prompt caching is enabled, only caching-compatible models are shown in the selection.

## Supported Models

| Model | Provider | Caching |
|-------|----------|---------|
| Claude 3 Haiku | Anthropic | Yes |
| Claude 3.5 Haiku | Anthropic | Yes |
| Claude 3.5 Sonnet | Anthropic | Yes |
| Claude 3 Opus | Anthropic | Yes |
| GPT-4o Mini | OpenAI | Yes |
| GPT-4o | OpenAI | Yes |
| GPT-4 Turbo | OpenAI | Yes |
| Gemini 2.0 Flash | Google | Yes |
| Gemini 2.5 Pro | Google | Yes |
| Llama 3.3 70B | Meta | No |

## Tools

Smart Assist uses a unified control approach for efficiency:

### Core Tools

- `get_entities` - Query available entities by domain, area, or name
- `get_entity_state` - Get detailed entity state with attributes
- `control` - Unified control for all entity types (lights, climate, media, covers, scripts)

### Scene Tools

- `run_scene` - Activate scenes
- `trigger_automation` - Trigger automations

### Utility Tools

- `get_weather` - Current weather information
- `web_search` - DuckDuckGo web search

## Requirements

- Home Assistant 2024.1 or newer
- Python 3.12+
- OpenRouter API key (get one at [openrouter.ai/keys](https://openrouter.ai/keys))

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/smart-assist.git
cd smart-assist

# Install development dependencies
pip install -r requirements_dev.txt

# Run tests
pytest

# Run linting
ruff check custom_components/smart_assist
ruff format custom_components/smart_assist --check
```

### Project Structure

```text
custom_components/smart_assist/
    __init__.py           # Integration setup, cache warming, session cleanup
    manifest.json         # HA integration manifest
    config_flow.py        # Setup wizard (4 steps)
    conversation.py       # Assist pipeline with full streaming
    const.py              # Constants, model definitions
    utils.py              # TTS cleaning utilities
    translations/         # EN/DE translations
    llm/
        client.py         # OpenRouter API client with retry & metrics
        models.py         # Message/response models
    tools/
        base.py           # Tool base class
        entity_tools.py   # Entity query tools
        unified_control.py # Unified entity control
        scene_tools.py    # Scene/script tools
        search_tools.py   # Web search tools
    context/
        entity_manager.py # Entity indexing
        conversation.py   # Conversation history
```

See [.github/instructions/project-definition.md](.github/instructions/project-definition.md) for detailed architecture.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) for details.
