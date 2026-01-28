# Smart Assist - Home Assistant LLM Integration

## Project Overview

A Home Assistant custom integration that connects LLMs (via Groq) with Home Assistant to create an intelligent smart home assistant capable of answering questions about the smart home environment and controlling devices.

**Primary Provider**: Groq (direct API with automatic prompt caching)  
**Fallback Provider**: OpenRouter (currently deprioritized, code preserved for compatibility)

## Groq Docs

https://console.groq.com/docs/overview
https://console.groq.com/docs/api-reference/chat/create

## OpenRouter Docs (Reference)

https://openrouter.ai/docs/api/reference/overview
https://openrouter.ai/docs/guides/best-practices/prompt-caching

**Version**: 1.7.9  
**Last Updated**: January 28, 2026

## Core Requirements

| Requirement | Description | Status |
| ----------- | ----------- | ------ |
| Assist Pipeline | Full integration with HA Assist Pipeline (conversation platform) | Done |
| LLM Provider | Groq API (direct) with automatic prompt caching | Done |
| Entity Access | Only exposed entities | Done |
| Tools | Unified control tool with efficient usage | Done |
| Web Search | DuckDuckGo integration (ddgs) | Done |
| Conversation | Interactive with follow-up prompts ("Anything else?") | Done |
| Performance | Prompt caching, cache warming, minimal context | Done |
| Responses | Concise LLM responses | Done |
| Streaming | Full streaming with tool execution | Done |
| TTS Streaming | Real-time token streaming to TTS via ChatLog API | Done |
| Multi-Language | Flexible language (auto-detect or any language) | Done |
| Reliability | Retry logic with exponential backoff | Done |
| Observability | Metrics/telemetry for debugging | Done |
| Calendar | Read/write calendar events with proactive reminders | Done |

---

## Architecture

### Project Structure

```
custom_components/smart_assist/
    __init__.py           # Integration setup, cache warming timer, session cleanup
    manifest.json         # HA integration manifest
    config_flow.py        # 4-step setup wizard
    conversation.py       # Assist pipeline integration with full streaming
    ai_task.py            # AI Task platform for automations
    sensor.py             # Metrics/telemetry sensor
    const.py              # Constants, models, helper functions
    utils.py              # TTS cleaning utilities
    translations/
        en.json           # English translations
        de.json           # German translations
    llm/
        __init__.py
        groq_client.py        # Groq API client (primary) with caching & metrics
        openrouter_client.py  # OpenRouter API client (fallback/legacy)
        models.py             # ChatMessage, StreamChunk models
    tools/
        __init__.py       # ToolRegistry with dynamic loading
        base.py           # BaseTool interface
        entity_tools.py   # Entity query tools
        unified_control.py # Unified entity control (all domains)
        scene_tools.py    # Scene/automation tools
        search_tools.py   # Utility tools (weather, web search)
        calendar_tools.py # Calendar read/write tools
    context/
        __init__.py
        entity_manager.py     # Entity indexing & state management
        conversation.py       # Conversation session management
        calendar_reminder.py  # Staged calendar reminder tracker
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
|  |  |   LLM Client     |--------> Groq API (Primary)             |  |
|  |  |   (Streaming)    |          - Automatic prompt caching     |  |
|  |  |                  |          - 2-hour cache TTL             |  |
|  |  |  - Retry logic   |          - ~95% cache hit rate          |  |
|  |  |  - Metrics       |                                         |  |
|  |  |  - Cache stats   |                                         |  |
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
| **Groq** | **Automatic** | **2 hours** | **No special handling - prefix matching** |
| Anthropic | Explicit | 5 min / 1 hour | `cache_control: {type: "ephemeral"}` |
| OpenAI | Automatic | ~1 hour | No special handling needed |

**Note**: Groq is the primary provider. Caching is automatic based on prefix matching. Not 100% guaranteed due to load-balanced servers, but typically achieves ~95% cache hit rate.

### CRITICAL: Prompt Construction Order for Caching

When modifying prompt construction, **ALWAYS maintain the static-to-dynamic order**:

```
STATIC  (cached, identical across requests)
  1. Technical System Prompt (tool schemas, rules)
  2. User System Prompt (personality, language)
  3. Entity Index (list of available entities)
  
DYNAMIC (changes between requests, breaks cache if in prefix)
  4. Calendar Context (upcoming events, reminders)
  5. Entity States (current values)
  6. Conversation History
  7. User Message
```

**Why this matters:**
- LLM providers cache based on **prefix matching**
- If dynamic content appears BEFORE static content, the cache is invalidated
- Even a single character difference in the prefix breaks caching
- Cache misses = higher latency + higher cost

**Rules for changes:**
1. New static context (e.g., room descriptions) goes AFTER Entity Index, BEFORE Calendar Context
2. New dynamic context (e.g., current time) goes AFTER Entity Index
3. Never inject timestamps, random IDs, or changing values in the static prefix (items 1-3)
4. Test cache hit rate after changes (target: >90%)

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

### Calendar Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `get_calendar_events` | time_range, calendar_id, max_events | Query upcoming events |
| `create_calendar_event` | calendar_id, summary, start_date_time/start_date, description, location | Create new event with fuzzy calendar matching |

**Calendar Features:**
- **Read Access**: Query events from all calendars or specific calendar
- **Write Access**: Create timed or all-day events
- **Fuzzy Matching**: Calendar names like "Patrick" match `calendar.patric`
- **Proactive Reminders**: Staged reminder injection (24h, 4h, 1h before events)
- **Deduplication**: Each reminder stage shown only once per event

### Utility Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `get_weather` | location (optional) | Current weather |
| `web_search` | query, max_results | DuckDuckGo search |

---

## Configuration Options

### Config Flow

```
Main Entry:
  - Groq API Key (validated)

Subentry (Conversation Agent / AI Task):
  Step 1: Model Selection
    - Model (Groq models: llama-3.3-70b-versatile, etc.)
  
  Step 2: Settings
    - Temperature (0.0 - 1.0)
    - Max Tokens
    - Language (empty = auto-detect from HA, or any language text)
    - Exposed entities only
    - Confirm critical actions
    - Max conversation history
    - Enable web search
    - Enable prompt caching
    - Extended cache TTL (Anthropic only)
    - Enable cache warming (incurs cost)
    - Cache refresh interval
  
  Step 3 (Conversation only): Prompt Configuration
    - User System Prompt (custom personality)
```

### Configuration Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `api_key` | string | - | Groq API key |
| `model` | string | llama-3.3-70b-versatile | LLM model |
| `provider` | string | groq | LLM provider (groq = primary) |
| `temperature` | float | 0.5 | Response creativity |
| `max_tokens` | int | 500 | Max response length |
| `language` | string | "" (auto) | Response language (empty = auto-detect from HA) |
| `exposed_only` | bool | true | Use only exposed entities |
| `confirm_critical` | bool | true | Confirm locks/alarms |
| `max_history` | int | 10 | Conversation history |
| `enable_web_search` | bool | true | DuckDuckGo search |
| `enable_quick_actions` | bool | false | Bypass LLM for simple (disabled) |
| `enable_prompt_caching` | bool | true | Prompt caching |
| `cache_ttl_extended` | bool | false | 1h TTL (Anthropic) |
| `enable_cache_warming` | bool | false | Periodic warming |
| `cache_refresh_interval` | int | 4 | Warming interval (min) |
| `user_system_prompt` | string | - | Custom personality |
| `ask_followup` | bool | true | Ask follow-up questions |
| `clean_responses` | bool | true | Clean LLM response for TTS |
| `calendar_context` | bool | false | Inject calendar reminders |
| `task_system_prompt` | string | - | AI Task instructions |
| `task_enable_prompt_caching` | bool | false | AI Task caching (not needed) |
| `task_enable_cache_warming` | bool | false | AI Task warming (not needed) |

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
| LLM API | Groq (primary), OpenRouter (legacy/fallback) |
| Web Search | ddgs (DuckDuckGo) |
| Caching | Automatic (Groq), In-memory entity index |
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
| -------- | ------- | ------- |
| validate.yml | Push/PR | Manifest validation, translation check, ruff lint, hassfest |
| release.yml | Release published | Version validation, create zip artifact |

---

## Future Enhancements

### Phase 2 - Reliability & Quality

- [ ] **Response Validator**: Validate LLM responses before output
  - Entity-ID validation (check if referenced entities exist)
  - Hallucination detection (compare claimed actions with tool results)
  - State consistency check (verify claimed states match actual states)
  - Safety filter (block problematic content, code injection attempts)
- [x] **Parallel Tool Execution**: Execute multiple tool calls concurrently
  - LLMs can request multiple tools in one response (e.g., "turn off all lights")
  - Uses `asyncio.gather()` to execute independent tools in parallel
  - Reduces response latency for multi-entity commands
- [x] **AI Task Platform**: Register as `ai_task` platform in addition to `conversation`
  - Enables LLM usage in automations via `ai_task.generate_data` service
  - Background tasks without user interaction (e.g., "Summarize today's events")
  - Separate configurable system prompt for task-oriented responses
  - Full tool support with parallel execution
- [x] **Direct LLM Provider**: Groq API with automatic caching (v1.7.0)
  - Groq as primary provider with ~95% cache hit rate
  - OpenRouter preserved for backwards compatibility
  - Future: Local LLM support (Ollama, llama.cpp)
- [ ] **Scheduled Actions**: Time-based command execution via LLM
  - "Turn off lights in 30 minutes"
  - Integration with HA's built-in scheduler
  - Persistent schedules surviving restarts
- [ ] **Rate Limiting**: Protect against API cost spikes
  - Configurable requests per minute/hour
  - Token budget limits (daily/monthly)
  - Graceful degradation when limits reached

### Phase 3 - Advanced Features

- [ ] **Proactive Suggestions**: Context-aware recommendations without user prompts
  - "Garage door open for 30 min - close it?"
  - "AC running but window open"
  - Event-based triggers (time, state changes)
- [ ] **Multi-User Support**: Per-user preferences and permissions
  - Different system prompts per user
  - User-specific entity access
  - Voice recognition integration
- [ ] **Learning from Preferences**: Adapt to user behavior patterns
  - Remember preferred brightness levels
  - Learn routine schedules
  - Personalized response style
- [ ] **Automation Suggestions**: AI-generated automation ideas
  - "You turn on porch light every evening - create automation?"
  - Analyze usage patterns for optimization
  - One-click automation creation
- [ ] **Energy Optimization**: Smart energy management via LLM
  - Peak/off-peak aware scheduling
  - Solar production integration
  - Cost-saving recommendations
- [x] **Calendar Integration**: Schedule-aware responses (v1.6.0)
  - Read access: Query events from all calendars
  - Write access: Create timed and all-day events
  - Proactive reminders: Staged context injection (24h, 4h, 1h before)
  - Fuzzy calendar matching for easier event creation
- [ ] **Custom Tool Plugins**: User-defined tools for LLM
  - YAML-based tool definitions
  - Custom service calls
  - Third-party API integrations
