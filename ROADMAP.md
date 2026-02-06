# Smart Assist - Roadmap

> Last updated: 2026-02-08 (v1.8.0)

## Completed Milestones

### v1.1.0 - Context and History (2026-01-30)

| Feature | Description |
| ------- | ----------- |
| Entity History Queries | `get_entity_history` tool for querying historical states ("How was the temperature yesterday?") |
| Multi-Turn Improvements | `RecentEntity` tracking with automatic context injection for pronoun resolution |

### v1.2.0 - Reminders and Notifications (2026-01-31)

| Feature | Description |
| ------- | ----------- |
| Voice Reminders | Timer with `command` parameter for voice-based reminders |
| Scheduled Tasks | Timer with `command` parameter (e.g., "Turn off lights in 2 hours") |
| Universal Send Tool | `send` tool for delivering content to notification targets (mobile_app, telegram, email) |

### v1.3.0 - Media Enhancements (2026-01-31)

| Feature | Description |
| ------- | ----------- |
| Playlist Support | Music Assistant integration with playlist playback |
| Media Queue | Media queue management through Music Assistant |
| TTS Announcements | Use `tts.speak` service in automations after `ai_task.generate_data` |

### Other Completed Features

| Feature | Version | Description |
| ------- | ------- | ----------- |
| Local LLM Support | v1.4.0 | Ollama integration as privacy-first alternative to cloud LLMs |
| Morning Briefing | v1.5.0 | Use `ai_task.generate_data` + `tts.speak` in a time-triggered automation |
| BaseLLMClient Refactoring | v1.5.0 | All LLM clients extend shared base class (~340 lines removed) |
| Config Flow Modularization | v1.5.0 | Split 1500-line config_flow.py into 3 focused modules |
| Memory & Personalization | v1.6.0 | Persistent user memory (100 chars, 100/user), hybrid injection + tool CRUD, 5-layer multi-user identification, presence heuristic (opt-in) |
| Dashboard & UI | v1.7.0 | Custom sidebar panel (vanilla Web Component), WebSocket API for real-time metrics, token/cache/memory/tools/calendar overview, multi-agent selector, HA theme integration |
| Memory Management UI | v1.7.1 | Rename/merge/delete user memories from dashboard, persistent calendar reminder state (HA Storage API), First Seen tracking fix |
| Token-Efficient Entity Discovery | v1.8.0 | Smart Discovery mode: no entity index in prompt, on-demand entity discovery via tool calls, 100% token savings on entity context |

---

## Planned Features

### v1.9.0 - Persistent Alarms and Scheduling

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Persistent Alarms | Real alarm clock functionality with absolute times. Creates HA automations for persistence across restarts. Supports repeating alarms, alarm management. Survives HA restarts unlike timer-based solution. | High |
| Proactive Notifications | LLM-triggered alerts based on entity state changes ("Your energy usage is unusually high today") | Medium |
| Weather Suggestions | Context-aware hints ("It will rain, should I close the windows?") | Low |

### v1.10.0 - Vision and Camera Analysis

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Camera Image Analysis | "Who is at the door?" - Analyze doorbell/camera snapshots with vision-capable LLM | High |
| Object Detection | "Is my car in the driveway?" - Check specific objects in camera view | Medium |
| Motion Summary | "What happened in the garage?" - Summarize recent camera activity | Medium |

### v1.11.0 - Natural Language Automations

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Natural Language Automations | "When I come home, turn on the lights" - Creates HA automations from natural language | High |
| Routine Creation | "Create a 'Good Night' routine" - Define multi-step sequences via conversation | Medium |
| Conditional Actions | "Turn off lights only if no one is home" - Smart conditionals in automations | Medium |

---

## Future Considerations

These features are not yet assigned to a specific version.

### High Priority

| Feature | Description | Effort |
| ------- | ----------- | ------ |
| Dashboard Generation | Create HA dashboards via natural language ("Create an energy dashboard for the kitchen"). Requires v1.7.0 panel infrastructure. | Medium |
| Per-Request History Log | Track individual request metrics (timestamp, tokens, response_time, tools_used) for trend analysis in dashboard. | Medium |
| Tool Usage Analytics | Track tool call frequency and success rates for dashboard visualization. | Low |
| MCP Server Mode | Expose Smart Assist tools via Model Context Protocol (MCP) for external clients (Claude Desktop, LM Studio, etc.). Enables external LLMs to discover and control HA entities through Smart Assist tools without full entity context dumps. Inspired by [mcp-assist](https://github.com/mike-nott/mcp-assist). | High |
| RAG Integration | Search own documents, manuals, recipes with vector embeddings. Use device manuals for troubleshooting advice, recipe retrieval for kitchen assistants, or household rules/instructions. | High |
| LLM Fallback Chain | Try local LLM (Ollama) first, fallback to cloud provider if local model fails or is unavailable. Balances privacy, cost, and reliability. | Medium |

### Medium Priority

| Feature | Description | Effort |
| ------- | ----------- | ------ |
| Web Search Enhancement | Expand existing DuckDuckGo search with provider options (Brave Search, SearXNG). Add search result caching and summarization. | Low |
| Energy Analysis | "How can I save energy?" - Consumption analysis with actionable suggestions. Compare usage patterns, identify wasteful devices, track costs over time. | Medium |
| Floor/Zone-Aware Context | Detect which room/zone the user is in (via voice satellite, BLE beacon, or companion app). Automatically scope commands to current location ("turn on the lights" = lights in current room). | Medium |
| Shopping List Management | Voice-controlled shopping lists integrated with HA shopping list or Bring/Todoist. "Add milk to the shopping list", "What's on my shopping list?", "Clear completed items". | Low |
| Multi-LLM Provider Support | Add support for Google Gemini, Anthropic Claude, and local LM Studio as additional LLM providers alongside existing OpenRouter/Groq/Ollama. | Medium |

### Low Priority

| Feature | Description | Effort |
| ------- | ----------- | ------ |
| Multi-Language Switching | "Spreche jetzt Deutsch" - Switch language mid-conversation without reconfiguration | Low |
| Cancel Intent Handler | Custom handler for "Abbrechen"/"Cancel" that returns TTS confirmation instead of empty response (workaround for HA Core bug where HassNevermind leaves satellite hanging) | Low |
| Presence-Based Suggestions | Proactive suggestions based on presence detection ("Welcome home! Should I turn on the heating?") | Medium |
| Health/Wellness Integration | Integration with health sensors (sleep trackers, air quality) for wellness suggestions and morning health reports | Medium |
| Cost Tracking | Track LLM API costs per conversation/day/month. Display in Custom Panel. Set budget alerts. | Low |
| Conversation Summarization | Auto-summarize long conversations for quick review. Daily/weekly conversation digest. | Low |
| Multi-Profile Support | Run multiple conversation agents with different models/personas for different rooms or use cases (e.g., kitchen assistant vs security assistant) | Medium |

---

## Contributing Ideas

Have a feature idea? Open an issue on [GitHub](https://github.com/mainzerp/smart-assist/issues) with the `feature-request` label.
