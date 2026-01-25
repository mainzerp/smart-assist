# Smart Assist - Home Assistant LLM Integration

## Project Overview

A Home Assistant custom integration that connects LLMs (via OpenRouter) with Home Assistant to create an intelligent smart home assistant capable of answering questions about the smart home environment and controlling devices.

**Version**: 1.1.0  
**Last Updated**: January 2026

## Core Requirements

| Requirement | Description | Status |
| ----------- | ----------- | ------ |
| Assist Pipeline | Full integration with HA Assist Pipeline (conversation platform) | Done |
| LLM Provider | OpenRouter with provider selection | Done |
| Entity Access | Only exposed entities | Done |
| Tools | Unified control tool with efficient usage | Done |
| Web Search | DuckDuckGo integration (ddgs) | Done |
| Conversation | Interactive with follow-up prompts ("Anything else?") | Done |
| Performance | Prompt caching, cache warming, minimal context | Done |
| Responses | Concise LLM responses | Done |
| Streaming | Full streaming with tool execution | Done |
| Reliability | Retry logic with exponential backoff | Done |
| Observability | Metrics/telemetry for debugging | Done |

---

## Architecture

### Project Structure

```
custom_components/smart_assist/
    __init__.py           # Integration setup, cache warming timer, session cleanup
    manifest.json         # HA integration manifest
    config_flow.py        # 4-step setup wizard
    conversation.py       # Assist pipeline integration with full streaming
    const.py              # Constants, models, helper functions
    utils.py              # TTS cleaning utilities
    translations/
        en.json           # English translations
        de.json           # German translations
    llm/
        __init__.py
        client.py         # OpenRouter API client with streaming, retry & metrics
        models.py         # ChatMessage, StreamChunk models
    tools/
        __init__.py       # ToolRegistry with dynamic loading
        base.py           # BaseTool interface
        entity_tools.py   # Entity query tools
        unified_control.py # Unified entity control (all domains)
        scene_tools.py    # Scene/automation tools
        search_tools.py   # Utility tools (weather, web search)
    context/
        __init__.py
        entity_manager.py # Entity indexing & state management
        conversation.py   # Conversation session management
```

### Component Overview

```
+---------------------------------------------------------------------+
|                         Home Assistant                               |
|  +---------------------------------------------------------------+  |
|  |                        Smart Assist                            |  |
|  |                                                                |  |
|  |  +------------------+    +--------------------------------+   |  |
|  |  |  Conversation    |--->|      Context Manager           |   |  |
|  |  |    Handler       |    |  - Entity Index (cached)       |   |  |
|  |  |                  |    |  - Entity States (dynamic)     |   |  |
|  |  |  Full streaming  |    |  - Conversation History        |   |  |
|  |  |  with tools      |    +--------------------------------+   |  |
|  |  +--------+---------+                                         |  |
|  |           |                                                    |  |
|  |           v                                                    |  |
|  |  +------------------+                                         |  |
|  |  |   LLM Client     |--------> OpenRouter API                 |  |
|  |  |   (Streaming)    |          - Provider routing             |  |
|  |  |                  |          - Prompt caching               |  |
|  |  |  - Retry logic   |          - Extended TTL                 |  |
|  |  |  - Metrics       |                                         |  |
|  |  |  - cache_control |                                         |  |
|  |  +--------+---------+                                         |  |
|  |           |                                                    |  |
|  |           v                                                    |  |
|  |  +--------------------------------------------------------+   |  |
|  |  |                   Tool Executor                         |   |  |
|  |  |  +-------------+ +-----------+ +-----------------------+ |   |  |
|  |  |  |   Unified   | |   Scene   | |      Utility          | |   |  |
|  |  |  |   Control   | |   Tools   | |  (Weather/Search)     | |   |  |
|  |  |  +-------------+ +-----------+ +-----------------------+ |   |  |
|  |  +--------------------------------------------------------+   |  |
|  +---------------------------------------------------------------+  |
|                                                                      |
|  +---------------------------------------------------------------+  |
|  |                    Cache Warming Timer                         |  |
|  |  - Runs every N minutes (configurable, default: 4)            |  |
|  |  - Keeps prompt cache warm for instant responses              |  |
|  |  - Optional (disabled by default, incurs cost)                |  |
|  +---------------------------------------------------------------+  |
+---------------------------------------------------------------------+
```

---

## Token Optimization Strategies

### 1. Prompt Caching Architecture

OpenRouter supports prompt caching for compatible models. The cache works on the **prefix** of the prompt.

```
┌─────────────────────────────────────────────────────────────┐
│  CACHED PREFIX (identical on every request)                 │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 1. Technical System Prompt                            │  │
│  │    - Tool schemas, response format, behavioral rules  │  │
│  │    - cache_control: ephemeral (for Anthropic)         │  │
│  ├───────────────────────────────────────────────────────┤  │
│  │ 2. User System Prompt                                 │  │
│  │    - Custom personality, language preferences         │  │
│  ├───────────────────────────────────────────────────────┤  │
│  │ 3. Entity Index (SEMI-STATIC)                         │  │
│  │    - entity_id, domain, friendly_name, area           │  │
│  │    - NO states - just what exists                     │  │
│  │    - Hash-based invalidation                          │  │
│  └───────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  DYNAMIC SUFFIX (changes on every request)                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 4. Relevant Entity States                             │  │
│  │    - Current states for query-relevant entities only  │  │
│  ├───────────────────────────────────────────────────────┤  │
│  │ 5. Conversation History + User Message                │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 2. Provider-Specific Caching

| Provider | Caching Type | TTL | Implementation |
|----------|--------------|-----|----------------|
| Anthropic | Explicit | 5 min (default) / 1 hour (extended) | `cache_control: {type: "ephemeral", ttl: "1h"}` |
| OpenAI | Automatic | ~1 hour | No special handling needed |
| Google | Implicit | 3-5 min | No special handling needed |

### 3. Cache Warming

Optional periodic refresh to keep cache warm:

```python
# Configuration
enable_cache_warming: bool = False  # Disabled by default (costs extra)
cache_refresh_interval: int = 4    # Minutes (1-55)

# Implementation
- Timer starts on HA startup
- Sends minimal "ping" request to populate cache
- Runs every N minutes (before cache expires)
- Automatically cancelled on reload/shutdown
```

**Cost consideration**: Each warming request costs ~0.001-0.003 USD depending on model.

### 4. Entity Index Caching

```python
# Entity Index is invalidated when:
entity_index_hash = hash(sorted([e.entity_id for e in exposed_entities]))

# Only changes when entities are added/removed (rare)
# Entity STATES change frequently but don't affect the index
```

---

## Smart Tools

### Tool Architecture

Smart Assist uses a **unified control tool** approach to minimize token usage while maintaining full entity control capabilities.

### Core Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `get_entities` | domain, area, name_filter | Query available entities |
| `get_entity_state` | entity_id | Get detailed entity state |
| `control` | entity_id, action, [domain-specific params] | Unified control for all entity types |

### Domain-Specific Control via `control` Tool

The `control` tool auto-detects domain from entity_id and supports:

| Domain | Supported Actions/Parameters |
|--------|------------------------------|
| `light.*` | turn_on, turn_off, toggle, brightness (0-100), color_temp, rgb_color |
| `climate.*` | turn_on, turn_off, set temperature, hvac_mode, preset |
| `media_player.*` | play, pause, stop, next, previous, volume (0-100), source |
| `cover.*` | open, close, stop, position (0-100) |
| `switch.*` | turn_on, turn_off, toggle |
| `script.*` | turn_on (execute) |
| `fan.*` | turn_on, turn_off, speed |

### Scene Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `run_scene` | scene_id | Activate scene |
| `trigger_automation` | automation_id | Trigger automation |

### Utility Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `get_weather` | location (optional) | Current weather |
| `web_search` | query, max_results | DuckDuckGo search |

---

## Configuration Options

### Config Flow (4 Steps)

```
Step 1: API Configuration
  - OpenRouter API Key (validated)

Step 2: Model Configuration
  - Model Selection (filtered by caching support if enabled)
  - Provider Selection (for guaranteed caching)
  - Temperature (0.0 - 1.0)
  - Max Tokens

Step 3: Behavior Settings
  - Language (en/de)
  - Exposed entities only
  - Confirm critical actions
  - Max conversation history
  - Enable web search
  - Enable quick actions
  - Enable prompt caching
  - Extended cache TTL (Anthropic only)
  - Enable cache warming (incurs cost)
  - Cache refresh interval

Step 4: Prompt Configuration
  - User System Prompt (custom personality)
```

### Configuration Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `api_key` | string | - | OpenRouter API key |
| `model` | string | claude-3-haiku | LLM model |
| `provider` | string | auto | Provider for routing |
| `temperature` | float | 0.3 | Response creativity |
| `max_tokens` | int | 500 | Max response length |
| `language` | string | en | Response language |
| `exposed_only` | bool | true | Use only exposed entities |
| `confirm_critical` | bool | true | Confirm locks/alarms |
| `max_history` | int | 10 | Conversation history |
| `enable_web_search` | bool | true | DuckDuckGo search |
| `enable_quick_actions` | bool | true | Bypass LLM for simple |
| `enable_prompt_caching` | bool | true | Prompt caching |
| `cache_ttl_extended` | bool | false | 1h TTL (Anthropic) |
| `enable_cache_warming` | bool | false | Periodic warming |
| `cache_refresh_interval` | int | 4 | Warming interval (min) |
| `user_system_prompt` | string | - | Custom personality |

---

## Supported Models

| Model ID | Display Name | Caching |
|----------|--------------|---------|
| anthropic/claude-3-haiku | Claude 3 Haiku (Fast, Cheap) | Yes |
| anthropic/claude-3.5-haiku | Claude 3.5 Haiku (Faster) | Yes |
| anthropic/claude-3.5-sonnet | Claude 3.5 Sonnet (Balanced) | Yes |
| anthropic/claude-3-opus | Claude 3 Opus (Most Capable) | Yes |
| openai/gpt-4o-mini | GPT-4o Mini (Fast, Cheap) | Yes |
| openai/gpt-4o | GPT-4o (Balanced) | Yes |
| openai/gpt-4-turbo | GPT-4 Turbo (Capable) | Yes |
| google/gemini-2.0-flash | Gemini 2.0 Flash (Fast) | Yes |
| google/gemini-2.5-pro | Gemini 2.5 Pro (Capable) | Yes |
| meta-llama/llama-3.3-70b-instruct | Llama 3.3 70B | No |

---

## Security Considerations

### Entity Access Control
- **Exposed Entities Only**: Respects HA's exposed entity settings
- **Domain Filtering**: Only supported domains included

### Action Safety
- **Confirmation Required**: Critical actions (locks, alarms) need confirmation
- **Audit Logging**: All commands logged

### API Security
- **Encrypted Storage**: API keys stored in HA's credential store
- **No Key Exposure**: Keys never sent to LLM

---

## Development

### Tech Stack

| Component | Technology |
|-----------|------------|
| Runtime | Python 3.12+ |
| Framework | Home Assistant Custom Integration |
| LLM API | OpenRouter (aiohttp) |
| Web Search | ddgs (DuckDuckGo) |
| Caching | In-memory with hash-based invalidation |
| Async | asyncio, aiohttp |

### Testing

```bash
# Install dev dependencies
pip install -r requirements_dev.txt

# Run tests
pytest

# Run linting
ruff check custom_components/smart_assist
ruff format custom_components/smart_assist --check
```

### CI/CD Workflows

| Workflow | Trigger | Actions |
|----------|---------|---------|
| validate.yml | Push/PR | Manifest validation, translation check, ruff lint, hassfest |
| release.yml | Release published | Version validation, create zip artifact |

---

## Future Enhancements

### Phase 2
- [ ] Additional LLM providers (direct API access)
- [ ] Proactive suggestions
- [ ] Scheduled actions
- [ ] Multi-user support
- [ ] Rate limiting

### Phase 3
- [ ] Learning from user preferences
- [ ] Automation suggestions
- [ ] Energy optimization
- [ ] Calendar integration
- [ ] Custom tool plugins
