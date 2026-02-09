# Smart Assist - Roadmap

> Last updated: 2026-02-09 (v1.11.5)

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
| Agent Memory (Auto-Learning) | v1.9.0 | Agent-level memory for LLM observations, entity mappings, patterns. Auto-saves surprising discoveries. Grows prompt context over time. |
| Cancel Intent Handler | v1.10.0 | Custom `HassNevermind` handler returns LLM-generated TTS confirmation instead of empty response. Fixes voice satellite hang on "Cancel"/"Abbrechen". Toggleable, enabled by default. |
| Per-Request History Log | v1.11.0 | Track individual request metrics (timestamp, tokens, response_time, tools_used) for trend analysis in dashboard History tab. Persistent storage, pagination, per-agent filtering. |
| Tool Usage Analytics | v1.11.0 | Track tool call frequency, success rates, and avg execution times. Dashboard visualization with summary cards and analytics table. Computed on-demand from request history. |
| Cancel Handler Agent Selection | v1.10.1 | Per-agent "Use as cancel intent handler" toggle. Preferred agent selection instead of first-available fallback. |
| Group Entity Handling Fix | v1.11.4 | Group entities (light groups) no longer incorrectly short-circuit "already on/off". Member states exposed to LLM. |
| Dashboard Auto-Refresh | v1.11.5 | Configurable auto-refresh (5s/10s/30s/60s, default 30s ON). Pauses when tab hidden, persisted in localStorage. |

---

## Planned Features

### v1.12.0 - Persistent Alarms and Scheduling

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Persistent Alarms | Real alarm clock functionality with absolute times. Creates HA automations for persistence across restarts. Supports repeating alarms, alarm management. Survives HA restarts unlike timer-based solution. | High |
| Proactive Notifications | LLM-triggered alerts based on entity state changes ("Your energy usage is unusually high today"). Architecture: HA automation triggers (state, numeric_state, person, calendar) call `conversation.process` to invoke Smart Assist LLM with context. Includes arrival/departure greetings via person triggers and calendar-triggered briefings. | Medium |
| Weather Suggestions | Context-aware hints ("It will rain, should I close the windows?") | Low |

### v1.13.0 - Vision and Camera Analysis

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Camera Image Analysis | "Who is at the door?" - Analyze doorbell/camera snapshots with vision-capable LLM | High |
| Object Detection | "Is my car in the driveway?" - Check specific objects in camera view | Medium |
| Motion Summary | "What happened in the garage?" - Summarize recent camera activity | Medium |

### v1.14.0 - Natural Language Automations

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Natural Language Automations | "When I come home, turn on the lights" - Creates HA automations from natural language. Leverages HA 2026.1/2026.2 purpose-specific triggers (person arrived/left, climate mode, light brightness, calendar events) and conditions for more natural automation generation. | High |
| Trigger Type Catalog | System prompt includes catalog of available purpose-specific triggers and conditions from HA 2025.12/2026.1/2026.2. LLM suggests the most appropriate trigger type for each scenario. | Medium |
| Routine Creation | "Create a 'Good Night' routine" - Define multi-step sequences via conversation | Medium |
| Conditional Actions | "Turn off lights only if no one is home" - Smart conditionals in automations | Medium |

### v1.15.0 - Proactive State Monitoring

| Feature | Description | Priority |
| ------- | ----------- | -------- |
| Entity State Watcher | Per-agent configurable watchlist of entities. When watched entities change, Smart Assist's LLM evaluates the change in context and decides whether to act (notify, control devices, log to memory). Uses `async_track_state_change_event()` with configurable cooldown (5min-1hr). | High |
| Automation Blueprints | Ready-made HA automation blueprints that call `conversation.process` for common monitoring scenarios (security alerts, energy warnings, comfort adjustments, arrival/departure greetings). Zero-code approach. | Medium |
| Anomaly Detection | Agent memory learns normal state patterns over time. Detects and reports anomalies ("The garage door has been open for 3 hours, which is unusual for a Tuesday"). Requires historical baseline. | Low |

---

## Future Considerations

These features are not yet assigned to a specific version.

### High Priority

| Feature | Description | Effort |
| ------- | ----------- | ------ |
| Dashboard Generation | Create HA dashboards via natural language ("Create an energy dashboard for the kitchen"). Requires v1.7.0 panel infrastructure. | Medium |
| MCP Server Mode | Expose Smart Assist tools via Model Context Protocol (MCP) for external clients (Claude Desktop, LM Studio, etc.). Enables external LLMs to discover and control HA entities through Smart Assist tools without full entity context dumps. Inspired by [mcp-assist](https://github.com/mike-nott/mcp-assist). HA Core 2026.2.1 fixed MCP server unicode escaping, confirming active MCP development. | High |
| RAG Integration | Search own documents, manuals, recipes with vector embeddings. Use device manuals for troubleshooting advice, recipe retrieval for kitchen assistants, or household rules/instructions. | High |
| LLM Fallback Chain | Try local LLM (Ollama) first, fallback to cloud provider if local model fails or is unavailable. Balances privacy, cost, and reliability. | Medium |
| Todo / Shopping List Integration | Voice-controlled todo/shopping lists via HA `todo` platform. "Add milk to the shopping list", "What's on my list?", "Mark eggs as done". Works with HA Shopping List, Todoist, Bring!, Google Tasks. HA 2026.2 fixed `todo.*` action data conversion. | Low |
| SQLite History Queries | LLM generates read-only SQL queries against HA's recorder database for complex historical questions ("When was the last time the garage door was open for more than 30 minutes?"). Restricted to exposed entities. | High |

### Medium Priority

| Feature | Description | Effort |
| ------- | ----------- | ------ |
| Web Search Enhancement | Expand existing DuckDuckGo search with provider options (Brave Search, SearXNG). Add search result caching and summarization. | Low |
| Energy Analysis | "How can I save energy?" - Consumption analysis with actionable suggestions. Compare usage patterns, identify wasteful devices, track costs over time. | Medium |
| Floor/Zone-Aware Context | Detect which room/zone the user is in (via voice satellite, BLE beacon, or companion app). Automatically scope commands to current location ("turn on the lights" = lights in current room). | Medium |
| Custom Tool Definitions | Let users define custom LLM tools via YAML/UI that call HA services, REST APIs, or templates. Bridges gap with Extended OpenAI Conversation's flexible function system (native, script, template, rest, scrape, composite, sqlite). | High |
| Response Quality Tracking | Track user satisfaction signals (conversation completed vs. repeated/frustrated attempts). Compute quality scores per model/agent. Help users compare LLM models objectively. | Medium |
| Multi-LLM Provider Support | Add support for Google Gemini, Anthropic Claude, and local LM Studio as additional LLM providers alongside existing OpenRouter/Groq/Ollama. | Medium |

### Low Priority

| Feature | Description | Effort |
| ------- | ----------- | ------ |
| Multi-Language Switching | "Spreche jetzt Deutsch" - Switch language mid-conversation without reconfiguration | Low |
| Presence-Based Suggestions | Proactive suggestions based on presence detection ("Welcome home! Should I turn on the heating?") | Medium |
| Health/Wellness Integration | Integration with health sensors (sleep trackers, air quality) for wellness suggestions and morning health reports | Medium |
| Cost Tracking | Track LLM API costs per conversation/day/month. Display in Custom Panel. Set budget alerts. Use OpenRouter pricing API. | Low |
| Conversation Export | Export conversation history as text/markdown/JSON. View past conversations in dashboard. Share transcripts for debugging. | Low |
| Conversation Summarization | Auto-summarize long conversations for quick review. Daily/weekly conversation digest. | Low |
| Multi-Profile Support | Run multiple conversation agents with different models/personas for different rooms or use cases (e.g., kitchen assistant vs security assistant) | Medium |
| Guest Mode | Restricted conversation profile for guests. Limits available tools (no locks, alarms, notifications). Configurable entity/domain allowlist. Auto-expires. Builds on multi-user identity system (v1.6.0). | Medium |
| Privacy Mode | Voice command to temporarily disable LLM processing. "Stop listening" disables agent, "Start listening" re-enables. Visual indicator in dashboard. | Low |
| Config Export/Import | Export Smart Assist configuration (agents, tools, memory, prompts) as portable JSON. Import on new installation for HA migrations. | Low |
| Smart Notification Routing | Automatically choose best notification channel based on context. At home: TTS via voice satellite. Away: push notification. Sleeping: queue for morning briefing. Configurable routing rules per user. | Medium |

---

## Contributing Ideas

Have a feature idea? Open an issue on [GitHub](https://github.com/mainzerp/smart-assist/issues) with the `feature-request` label.
