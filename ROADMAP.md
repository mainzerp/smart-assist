# Smart Assist - Roadmap

> Last updated: 2026-02-15 (v1.17.0)

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
| Batch Entity Control | v1.12.0 | Batch `entity_ids` parameter on `control` tool for multi-entity control in a single call. Enhanced entity discovery with live state and group indicators. |
| Code Review Fixes Phase 1-3 | v1.12.5 | Token tracking fix, deprecated API replacements, datetime consistency, entity index caching (30s TTL), ~340 lines dead code removed. |
| Code Review v2 Fixes Phase 5-8 | v1.12.6 | Memory access_count fix, LLM client stream dedup (~360 lines removed), conversation.py split into 3 files, shared EntityManager, Ollama AI Task provider. |
| Prompt Preview Tab | v1.13.0 | Dashboard "Prompt" tab showing full system prompt and custom instructions per agent. WebSocket `smart_assist/system_prompt` command. |
| Prompt & Tool Token Optimization | v1.13.1 | System prompt condensed ~38% (~700-800 tokens saved), tool definitions condensed (~1120 tokens saved), ~1800-1920 fewer tokens per request total. |
| Reliability & Safety Gate | v1.13.18 | Per-agent retry/latency controls, explicit confirmation for critical control actions, dashboard failure/timeout rates, and user-facing error sanitization. |
| AI Task Control Opt-In + Lock Guard | v1.14.0 | Added AI Task control safety switches (`task_allow_control`, `task_allow_lock_control`) with runtime enforcement and lock-domain guardrails. |
| Structured Output for `ai_task` | v1.15.0 | Added schema-constrained `ai_task.generate_data` output with local validation, native structured-mode fallback retry, localized concise failures, and automation examples. |
| AI Task Structured Output Follow-up Fixes | v1.15.1 | Fixed tool-loop compatibility regressions, hardened async chat-call compatibility, and restored robust tool execution fallback behavior. |
| Persistent Alarms | v1.16.0 | Added restart-safe absolute-time alarms via dedicated `alarm` tool, storage-backed alarm manager, lifecycle reconciliation, and fired-alarm event emission. |
| Alarm Governance + Dashboard Management | v1.17.0 | Added human-readable alarm `display_id`, post-fire conversational snooze resolution, alarms dashboard tab/actions, lifecycle `smart_assist_alarm_updated` contracts, and explicit no-mutation safety stance for user automations. |

---

## Planned Features

### Near-Term (P0/P1)

Governance note: No autonomous critical control in MVP phases without explicit user confirmation.

Alarm governance note: Smart Assist remains event-driven for alarms and does not modify user-created HA automations; a future opt-in managed-automation namespace remains out of scope for this release.

| Feature | Priority | Why now | Dependencies | Acceptance Criteria |
| ------- | -------- | ------- | ------------ | ------------------- |
| Proactive Monitoring MVP (Notify-Only) | P1 | High user value with constrained risk; formalizes existing proactive concepts into a safe MVP slice. | Entity state watcher design, notification routing baseline, rate limiting/cooldown state | 1) Watched-entity config includes entity picker and cooldown interval. 2) At most one proactive notification per watched entity per cooldown window. 3) Global per-agent disable switch exists. 4) End-to-end flow works: threshold event -> LLM analysis -> notification sent. |
| Natural Language Automations MVP | P1 | Core assistant capability with strong value, but needs a constrained template-backed first phase. | Trigger type catalog, automation schema validation, preview/confirmation flow | 1) Generated automations pass HA validation before save. 2) Assistant shows human-readable trigger/condition/action preview before apply. 3) User can cancel at preview stage without side effects. 4) At least three safe starter templates are supported. |

### Long-Term (P2)

| Feature | Priority | Description |
| ------- | -------- | ----------- |
| Camera Image Analysis | P2 | "Who is at the door?" Analyze doorbell/camera snapshots with vision-capable LLM. |
| Object Detection | P2 | "Is my car in the driveway?" Check specific objects in camera view. |
| Motion Summary | P2 | "What happened in the garage?" Summarize recent camera activity. |
| Todo / Shopping List Integration | P2 | Voice-driven todo/shopping list flows using HA `todo` platform and supported providers. |
| MCP Server Mode | P2 | Expose selected Smart Assist tools through Model Context Protocol for external clients. |

---

## Backlog (Uncommitted)

These features are exploratory and not yet assigned to a target horizon.

### High Priority

| Feature | Description | Effort |
| ------- | ----------- | ------ |
| Dashboard Generation | Create HA dashboards via natural language ("Create an energy dashboard for the kitchen"). Requires v1.7.0 panel infrastructure. | Medium |
| RAG Integration | Search own documents, manuals, recipes with vector embeddings. Use device manuals for troubleshooting advice, recipe retrieval for kitchen assistants, or household rules/instructions. | High |
| LLM Fallback Chain | Try local LLM (Ollama) first, fallback to cloud provider if local model fails or is unavailable. Balances privacy, cost, and reliability. | Medium |
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
| Multi-Modal Input | Accept images in conversation (via Companion App or chat UI) for vision-capable LLM analysis. "What plant is this?", "Read this label." Separate from Camera Image Analysis which is security-focused. | High |

---

## Contributing Ideas

Have a feature idea? Open an issue on [GitHub](https://github.com/mainzerp/smart-assist/issues) with the `feature-request` label.
