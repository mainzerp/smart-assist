# API Reference Documentation

This document contains the current API specifications for all external services used by Smart Assist.

> **Last Updated:** January 2026 | **Version:** 1.0.0

---

## Table of Contents

1. [Groq API](#1-groq-api)
2. [DuckDuckGo Search (DDGS)](#2-ddgs-duckduckgo-search)
3. [Home Assistant APIs](#3-home-assistant-apis)
4. [Version Compatibility](#version-compatibility)
5. [References](#references)

---

## 1. Groq API

### Overview

Smart Assist uses the Groq API for fast LLM inference with automatic prompt caching.

### Endpoint

```text
POST https://api.groq.com/openai/v1/chat/completions
```

### Headers

```python
headers = {
    "Authorization": "Bearer <GROQ_API_KEY>",
    "Content-Type": "application/json"
}
```

### Request Schema

```typescript
type Request = {
    model: string;                     // e.g., "llama-3.3-70b-versatile"
    messages: Message[];
    
    // Response format
    stream?: boolean;                  // Enable SSE streaming
    
    // LLM Parameters
    max_completion_tokens?: number;    // Max tokens to generate
    temperature?: number;              // Range: [0, 2], default: 1
    
    // Tool calling
    tools?: Tool[];
    tool_choice?: ToolChoice;          // 'none' | 'auto' | 'required' | { type: 'function', function: { name: string } }
    parallel_tool_calls?: boolean;     // Allow multiple tool calls in one response
    
    // Advanced parameters
    top_p?: number;                    // Range: (0, 1], default: 1
    stop?: string | string[];          // Stop sequences
    seed?: number;                     // For reproducibility
};
```

### Message Types

```typescript
type Message = 
    | {
        role: 'user' | 'assistant' | 'system';
        content: string;
        name?: string;
    }
    | {
        role: 'tool';
        content: string;
        tool_call_id: string;
    };
```

### Tool Definition

```typescript
type Tool = {
    type: 'function';
    function: {
        name: string;
        description?: string;
        parameters: object;    // JSON Schema
    };
};

type ToolCall = {
    id: string;
    type: 'function';
    function: {
        name: string;
        arguments: string;     // JSON string
    };
};
```

### Response Schema

```typescript
type Response = {
    id: string;
    object: 'chat.completion' | 'chat.completion.chunk';
    created: number;
    model: string;
    choices: Choice[];
    usage?: Usage;
    x_groq?: {
        id: string;
        usage: {
            queue_time: number;
            prompt_tokens: number;
            prompt_time: number;
            completion_tokens: number;
            completion_time: number;
            total_tokens: number;
            total_time: number;
        };
    };
};

type Usage = {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    queue_time?: number;
    prompt_time?: number;
    completion_time?: number;
    total_time?: number;
    prompt_tokens_details?: {
        cached_tokens: number;
    };
};

type Choice = {
    index: number;
    finish_reason: string | null;  // 'stop' | 'tool_calls' | 'length'
    message: {
        role: 'assistant';
        content: string | null;
        tool_calls?: ToolCall[];
    };
    logprobs?: object | null;
};
```

### Prompt Caching

Groq provides automatic prompt caching for repeated context.

- **Cache hit**: Uses cached prompt tokens (no additional cost)
- **Cache miss**: Full prompt processing
- **Reported in**: `usage.prompt_tokens_details.cached_tokens`

Smart Assist achieves approximately 90% cache hit rate due to consistent system prompts.

### Streaming Response

When `stream: true`, responses are delivered as Server-Sent Events (SSE):

```text
data: {"id":"...","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hello"}}]}
data: {"id":"...","object":"chat.completion.chunk","choices":[{"delta":{"content":" world"}}]}
data: [DONE]
```

### Rate Limits

Rate limits vary by model and API tier. Check Groq console for current limits.

### Error Handling

| Status Code | Meaning | Retry |
| ----------- | ------- | ----- |
| 400 | Bad request (invalid parameters) | No |
| 401 | Invalid API key | No |
| 429 | Rate limit exceeded | Yes (with backoff) |
| 500 | Server error | Yes |
| 503 | Service unavailable | Yes |

Smart Assist uses exponential backoff for retryable errors (configured in `const.py`).

---

## 2. DDGS (DuckDuckGo Search)

### Installation

```bash
pip install ddgs>=7.0.0
```

### Basic Usage

```python
from ddgs import DDGS

# Text search
results = DDGS().text(
    keywords="search query",
    region="wt-wt",           # wt-wt (worldwide), de-de, us-en, etc.
    safesearch="moderate",    # on, moderate, off
    timelimit=None,           # d (day), w (week), m (month), y (year)
    max_results=10
)
```

### Available Methods

```python
# Text search
DDGS().text(keywords, region, safesearch, timelimit, max_results)

# Image search
DDGS().images(keywords, region, safesearch, timelimit, max_results, size, color, ...)

# Video search
DDGS().videos(keywords, region, safesearch, timelimit, max_results, resolution, duration)

# News search
DDGS().news(keywords, region, safesearch, timelimit, max_results)
```

### Response Format (text search)

```python
[
    {
        "title": "Page Title",
        "href": "https://example.com/page",
        "body": "Page description or snippet..."
    },
    # ...
]
```

### Proxy Support

```python
# HTTP/HTTPS/SOCKS5 proxy
ddgs = DDGS(proxy="socks5://user:password@host:port", timeout=20)
```

### Exceptions

```python
from ddgs.exceptions import (
    DuckDuckGoSearchException,  # Base exception
    RatelimitException,         # Rate limit exceeded
    TimeoutException,           # Request timeout
)
```

---

## 3. Home Assistant APIs

### Conversation Entity

#### Base Class

```python
from homeassistant.components.conversation import ConversationEntity

class MyConversationEntity(ConversationEntity):
    """Custom conversation entity."""
    
    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return supported languages."""
        return "*"  # All languages
    
    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
    ) -> ConversationResult:
        """Handle incoming message."""
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech("Response text")
        
        return ConversationResult(
            response=response,
            conversation_id="...",
            continue_conversation=True,
        )
```

#### ConversationInput

| Property | Type | Description |
| -------- | ---- | ----------- |
| `text` | str | User input text |
| `context` | Context | HA context for actions |
| `conversation_id` | str or None | Multi-turn tracking |
| `language` | str | Input language |
| `continue_conversation` | bool | If agent expects response |

#### ConversationResult

| Property | Type | Description |
| -------- | ---- | ----------- |
| `response` | IntentResponse | The response object |
| `conversation_id` | str | Session identifier |
| `continue_conversation` | bool | If True, expect follow-up |

#### ChatLog (New API)

```python
# Access conversation history
for content in chat_log.content:
    # Process messages...

# Add assistant response
chat_log.async_add_assistant_content_without_tools(
    AssistantContent(
        agent_id=user_input.agent_id,
        content="Response text",
    )
)
```

### Conversation API (HTTP)

#### Process Request

```text
POST /api/conversation/process
```

```json
{
    "text": "turn on the lights in the living room",
    "language": "en",
    "agent_id": "smart_assist",
    "conversation_id": "<optional-session-id>"
}
```

#### Response

```json
{
    "conversation_id": "<generated-id>",
    "continue_conversation": true,
    "response": {
        "response_type": "action_done",
        "language": "en",
        "data": {
            "targets": [],
            "success": [],
            "failed": []
        },
        "speech": {
            "plain": {
                "speech": "Turned Living Room lights on"
            }
        }
    }
}
```

### LLM API Integration

#### Get Available APIs

```python
from homeassistant.helpers import llm

apis = llm.async_get_apis(hass)
for api in apis:
    print(f"{api.id}: {api.name}")
```

#### Provide LLM Data to ChatLog

```python
await chat_log.async_provide_llm_data(
    user_input.as_llm_context(DOMAIN),
    config_entry.options.get(CONF_LLM_HASS_API),
    config_entry.options.get(CONF_PROMPT),
    user_input.extra_system_prompt,
)

# Access tools from LLM API
if chat_log.llm_api:
    tools = [format_tool(t) for t in chat_log.llm_api.tools]
```

### Exposed Entities

Exposed entities are entities the user has marked as accessible to voice assistants.

```python
from homeassistant.components.homeassistant.exposed_entities import (
    async_should_expose,
)

# Check if entity is exposed
is_exposed = async_should_expose(hass, "conversation", entity_id)

# Get all exposed entities
for state in hass.states.async_all():
    if async_should_expose(hass, "conversation", state.entity_id):
        # Entity is exposed to conversation
        pass
```

---

## Version Compatibility

| Component | Minimum Version | Tested Version |
| --------- | --------------- | -------------- |
| Home Assistant | 2024.1.0 | 2025.1+ |
| Python | 3.12 | 3.12 |
| aiohttp | 3.8.0 | 3.11+ |
| ddgs | 7.0.0 | 7.5+ |
| Groq API | v1 | v1 |

---

## References

- [Groq API Documentation](https://console.groq.com/docs/api-reference)
- [Groq Console](https://console.groq.com/)
- [DDGS GitHub](https://github.com/deedy5/ddgs)
- [DDGS PyPI](https://pypi.org/project/ddgs/)
- [HA Conversation Entity](https://developers.home-assistant.io/docs/core/entity/conversation)
- [HA Conversation API](https://developers.home-assistant.io/docs/intent_conversation_api)
- [HA LLM API](https://developers.home-assistant.io/docs/core/llm/)
