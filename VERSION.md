# Smart Assist - Version History

## Current Version

| Component | Version | Date |
|-----------|---------|------|
| Smart Assist | 1.0.0 | 2026-01-25 |

## Version History

### v1.0.0 (2026-01-25) - Initial Release

**Core Features:**
- LLM-powered smart home control via OpenRouter API
- ConversationEntity-based architecture with streaming support
- Real token-by-token streaming for responsive UI
- Tool-based entity control (lights, climate, covers, media, scripts, etc.)
- Multi-turn conversation with ChatLog integration
- Marker-based conversation continuation (`[AWAIT_RESPONSE]`)

**Model Support:**
- Dynamic model fetching from OpenRouter API
- Free text model input (any OpenRouter model supported)
- Automatic prompt caching detection based on model prefix
- Provider-specific caching support (Anthropic, OpenAI, Google, Groq)

**Prompt Caching:**
- Anthropic: Explicit cache_control with 5min/1h TTL options
- OpenAI/Google/Groq: Automatic caching
- Cache warming option for consistent low latency
- System prompt caching optimization

**Configuration:**
- Multi-step config flow (API key, model, behavior, prompt)
- Options flow for runtime configuration changes
- Bilingual UI (English/German)
- Custom system prompt support

**Reliability:**
- Retry logic with exponential backoff (max 3 retries)
- LLM metrics tracking (requests, tokens, response times, cache hits)
- Session cleanup on integration unload
- Graceful error handling

**Entity Management:**
- Entity index for fast lookup
- Support for exposed entities only mode
- Critical action confirmation (locks, alarms)
- Domain-based entity filtering

## Technology Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| Home Assistant | 2024.1+ | Core platform |
| Python | 3.11+ | Runtime |
| aiohttp | 3.9+ | Async HTTP client |
| OpenRouter API | v1 | LLM gateway |

## Changelog Format

Each release follows this format:
- **Major (X.0.0)**: Breaking changes
- **Minor (1.X.0)**: New features, backward compatible
- **Patch (1.0.X)**: Bug fixes, small improvements
