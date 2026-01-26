# Smart Assist

**LLM-powered smart home assistant for Home Assistant using OpenRouter.**

Control your smart home with natural language. Supports Claude, GPT-4, Gemini, Llama, and 200+ other models via OpenRouter.

## Features

- **Natural Language Control**: Talk to your smart home in plain language
- **OpenRouter Integration**: Access 200+ AI models (Claude, GPT-4, Gemini, Llama, etc.)
- **Dynamic Provider Selection**: Choose specific providers per model
- **Prompt Caching**: Reduce costs with Anthropic/Google prompt caching
- **Auto-detect Language**: Uses Home Assistant's configured language
- **Metrics Tracking**: Monitor response times, token usage, success rates
- **Streaming Responses**: Real-time token streaming

## Installation

1. Add this repository to HACS as a custom repository
2. Install "Smart Assist" from HACS
3. Restart Home Assistant
4. Add integration: Settings > Devices & Services > Add Integration > Smart Assist
5. Enter your OpenRouter API key

## Requirements

- Home Assistant 2024.1.0 or newer
- OpenRouter API key (https://openrouter.ai)
