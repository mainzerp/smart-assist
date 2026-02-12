# Smart Assist - Version History

## Current Version

| Component    | Version | Date       |
| ------------ | ------- | ---------- |
| Smart Assist | 1.13.8  | 2026-02-11 |

## Version History

### v1.13.8 (2026-02-11) - Prompt Simplification & Hallucination Fix

**Bug Fixes:**
- Fix: Severe LLM hallucinations (garbled/repetitive output after tool calls) caused by prompt complexity and destabilizing patterns
- Removed [CANCEL] prefix mechanism from system prompt -- replaced with nevermind tool for cleaner cancel detection
- Replaced all markdown headings in system prompt with plain-text labels to avoid format conflicts
- Removed all emphasis markers (CRITICAL, MANDATORY, IMPORTANT, bold) from system prompt
- Condensed 6 instruction sections (Entity Discovery, Entity Control, Calendar, Music, User Memory, Agent Memory) -- ~380 token reduction
- Added "5-15 words max" response constraint after tool execution
- Shortened tool descriptions (unified_control, timer command) to reduce token overhead

**Internal:**
- New NevermindTool in conversation_tools.py for cancel/abort signaling via tool call
- streaming.py handles nevermind tool calls (similar to await_response pattern)
- conversation.py: `_detect_cancel_prefix()` replaced with `_detect_nevermind_from_tool_calls()`

- Files modified: prompt_builder.py, conversation.py, streaming.py, conversation_tools.py, tools/__init__.py, timer_tools.py, unified_control.py

### v1.13.7 (2026-02-11) - Group vs Area Prompt Fix

**Improvements:**
- Prompt: Area/room requests now always batch-control individual entities instead of substituting a group
- Prompt: Groups treated as regular entities -- no special handling, HA manages member propagation
- Entity tool: Removed aggressive group-only hint, replaced with neutral batch tip

- Files modified: prompt_builder.py, entity_tools.py

### v1.13.6 (2026-02-11) - Dashboard Stability & Cancel Detection

**Bug Fixes:**
- Fix: Dashboard no longer goes blank after extended use (WS reconnection, connection change detection, subscription retry, concurrent fetch guards)
- Cancel intent detection now LLM-based via [CANCEL] prefix instead of exact-match phrase list

**UI:**
- History tab: "Cancel" and "System" badges in Status column
- History tab: Tools column wider with 50-char truncation
- Dashboard always refreshes data when tab becomes visible (even with auto-refresh disabled)

**Internal:**
- `is_nevermind` and `is_system_call` fields tracked in request history
- `_resubscribe()` method for clean subscription teardown and re-creation
- Concurrent fetch guards for `_fetchData()`, `_loadHistory()`, `_loadPrompt()`

- Files modified: conversation.py, prompt_builder.py, request_history.py, smart-assist-panel.js

### v1.13.5 (2026-02-11) - History Tab Improvements *[superseded by v1.13.6]*

**UI:**
- History tab: Tools column wider (min-width 180px, truncation increased to 50 chars)
- History tab: "Cancel" badge shown for nevermind/cancel intents
- History tab: "System" badge shown for system-triggered actions (timer callbacks)

**Internal:**
- New `is_nevermind` and `is_system_call` fields tracked in request history entries
- Cancel intent detection via `_is_cancel_intent()` static method (EN + DE phrases)

- Files modified: request_history.py, conversation.py, smart-assist-panel.js

### v1.13.4 (2026-02-11) - Timer Reminder Quality Fix

**Bug Fixes:**
- Fix: Timer reminders now deliver a friendly, reformulated announcement instead of echoing the original request verbatim
- Timer tool `command` description updated to instruct LLM to use direct statements for reminders
- Timer callbacks detected early in conversation pipeline and wrapped with context for proper LLM handling

- Files modified: conversation.py, timer_tools.py

### v1.13.3 (2026-02-11) - Timer Announcement Fix

**Bug Fixes:**
- Fix: Timer command responses are now announced on the originating satellite via `assist_satellite.announce` (HA Core discards the `ConversationResult` from timer callbacks, so Smart Assist now detects silent calls and proactively announces)

- Files modified: conversation.py

### v1.13.2 (2026-02-11) - Timer Fix & Dashboard Scroll Fix

**Bug Fixes:**
- Fix: Timer commands now execute correctly when timer expires (was routing to built-in Assist agent instead of Smart Assist due to missing `conversation_agent_id`)
- Fix: Dashboard scroll position properly preserved during auto-refresh (uses actual scroll container instead of `window`, skips loading renders during refresh)

**UI:**
- Prompt tab metric cards now show estimated token counts alongside character counts

**Docs:**
- README and info.md updated with History/Prompt tabs, Ollama provider, Entity Discovery Mode
- Roadmap overhauled with v1.12.0-v1.13.1 completed features and new future feature proposals

- Files modified: tools/base.py, tools/timer_tools.py, conversation.py, www/smart-assist-panel.js, README.md, info.md, ROADMAP.md

### v1.13.1 (2026-02-11) - Prompt & Tool Token Optimization

**Performance:**
- System prompt condensed ~38% (~700-800 tokens saved per request)
- Tool definitions condensed across 13 tools (~1120 tokens saved per request)
- Total: ~1800-1920 fewer prompt tokens per request with identical behavior

**Bug Fixes:**
- Dashboard scroll position preserved during auto-refresh (no more jump-to-top)

**Code Quality:**
- Removed dead GetTimeTool class from search_tools.py

- Files modified: prompt_builder.py, all tools/*.py, www/smart-assist-panel.js

### v1.13.0 (2026-02-11) - Prompt Preview Tab & Music Prompt Fix

**New Features:**
- Dashboard: New "Prompt" tab shows the full system prompt and user custom instructions for each agent
- WebSocket: New `smart_assist/system_prompt` command to retrieve built prompts
- Prompt preview displays agent name, prompt lengths, and formatted sections with visual headers

**Improvements:**
- Prompt: Clarified music_assistant vs control tool usage for playback transport (stop/pause/resume/volume)

- Files modified: websocket.py, www/smart-assist-panel.js, prompt_builder.py

### v1.12.6 (2026-02-10) - Code Review v2 Fixes (Phase 5-8)

**Bug Fixes:**
- Fix: Memory access_count no longer inflated on every request (removed injection-time bump from get_injection_text/get_agent_injection_text)
- Fix: Remaining datetime.now() in memory.py injection methods replaced with dt_util.now()
- Fix: GetTimeTool in search_tools.py now uses dt_util.now() instead of datetime.now()
- Fix: ai_task.py get_entity_index() tuple unpacking corrected
- Fix: Empty-response retry nudge message removed from working_messages after successful iteration (prevents token waste)
- Fix: Cache warming data no longer overwritten on timer start (uses setdefault)

**Performance:**
- Perf: GetEntitiesTool now uses shared EntityManager from conversation entity (avoids redundant entity iteration per tool call)
- Perf: Entity index hash now includes friendly_name and area_name (renames invalidate cache correctly)

**Code Quality:**
- Refactor: OpenRouter chat_stream/chat_stream_full deduplicated into shared _stream_request() method (~190 lines removed)
- Refactor: Groq chat_stream/chat_stream_full deduplicated into shared _stream_request() method (~170 lines removed)
- Refactor: conversation.py split into 3 files: conversation.py (722 lines), prompt_builder.py (558 lines), streaming.py (353 lines)
- Removed: RunScriptTool dead code from scene_tools.py
- Removed: Unused CONF_ENABLE_PROMPT_CACHING constant from const.py
- Removed: Unused asyncio import from ai_task.py
- Added: execute_tools_parallel utility function in utils.py (used by ai_task.py)
- Added: Ollama as AI Task provider option in config_subentry_flows.py

- Files modified: conversation.py, prompt_builder.py (new), streaming.py (new), context/memory.py, context/entity_manager.py, tools/entity_tools.py, tools/__init__.py, tools/scene_tools.py, tools/search_tools.py, llm/openrouter_client.py, llm/groq_client.py, llm/ollama_client.py, ai_task.py, utils.py, const.py, config_subentry_flows.py, __init__.py

### v1.12.5 (2026-02-10) - Code Review Fixes (Phase 1-3)

- Fix: tokens_used in record_conversation now uses per-request tokens instead of hardcoded 0
- Fix: Replaced private auth API (_store._users) with async_get_user() in user_resolver.py
- Fix: Replaced deprecated asyncio.get_event_loop().run_in_executor() with hass.async_add_executor_job() in search_tools.py
- Fix: datetime.now() replaced with dt_util.now() for HA timezone consistency (conversation.py, memory.py)
- Fix: Hardcoded German strings replaced with English in calendar_tools.py and calendar_reminder.py
- Fix: Fragile duration string-parsing replaced with integer-based duration_mins in entity_tools.py
- Fix: WebSocket send_message wrapped in try/except for closed connections in websocket.py
- Perf: Entity index caching with 30s TTL in entity_manager.py (avoids rebuilding on every request)
- Quality: Removed ~340 lines of dead legacy tool classes from entity_tools.py
- Quality: Moved 5 inline imports to module level in conversation.py (re, time, timedelta, dt_util)
- Files modified: conversation.py, user_resolver.py, search_tools.py, memory.py, entity_tools.py, calendar_tools.py, calendar_reminder.py, entity_manager.py, websocket.py

### v1.12.4 (2026-02-10) - Prevent Redundant Domain Search

- Fix: LLM no longer searches additional domains (e.g. switch) when the first domain search (e.g. light) already returned results
- Prompt clarified: fallback domain search is ONLY for zero-result cases
- Reduces iterations from 3 to 2 for room commands like "Kueche ausschalten"
- Files modified: `conversation.py`

### v1.12.3 (2026-02-10) - Group Entity Priority in Tool Hints

- Fix: When get_entities finds a GROUP entity, only show group control tip (not batch tip with all IDs)
- Previously: batch tip included group+members, causing LLM to batch-control individual entities instead of using the group
- Now: GROUP entity hint says "use control(entity_id=group) - do NOT control individual members separately"
- Batch tip (entity_ids) only shown when NO group entity exists
- Files modified: `tools/entity_tools.py`

### v1.12.2 (2026-02-10) - Dynamic Area List in Prompt

- Reverted v1.12.1 hardcoded language in prompt examples (language-neutral again)
- Reverted hardcoded English->German translation fallback in get_entities
- New: System prompt now includes dynamic AVAILABLE AREAS list from Home Assistant area registry
- LLM sees exact area names and matches user intent to correct area - works for any language
- Minimal token cost (~20-30 tokens for typical setups)
- Files modified: `conversation.py`, `tools/entity_tools.py`

### v1.12.1 (2026-02-10) - Area Name Language Fix (reverted in v1.12.2)

- Fix: LLM no longer translates area names to English (e.g. "kitchen" instead of "Kueche") when calling get_entities
- Fix: Prompt examples now use local language area names to correctly prime the LLM
- Added: Translation fallback in get_entities area matching (English->German) as safety net
- Impact: Room commands now resolve in 2 iterations instead of 4 (no wasted retry)
- Files modified: `conversation.py`, `tools/entity_tools.py`

### v1.12.0 (2026-02-10) - Batch Control and Smart Entity Discovery

**Feature: Batch Entity Control**
- New `entity_ids` (array) parameter on `control` tool for controlling multiple entities in a single call
- Room-level commands ("Kueche ausschalten") now complete in 2 LLM iterations instead of N+1
- Prevents LLM from forgetting entities during sequential tool calls
- Backward compatible: `entity_id` (singular) continues to work for single-entity commands

**Feature: Enhanced Entity Discovery**
- `get_entities` now includes current state (`[on]`/`[off]`) and group indicator (`[GROUP, N members]`) in results
- Smart control hints: group-aware tip and batch control suggestion with entity IDs
- Area matching improved: exact match first, substring fallback

**Enhanced: Group-Aware Decision Logic**
- System prompt teaches LLM 3-tier decision: GROUP entity (preferred) > batch entity_ids > single entity_id
- Entity Control section updated with GROUP ENTITIES and BATCH CONTROL rules
- Entity tracking updated to handle both `entity_id` and `entity_ids` from tool calls

- Files modified: `tools/base.py`, `tools/unified_control.py`, `tools/entity_tools.py`, `conversation.py`

### v1.11.10 (2026-02-10) - Smart Discovery Reliability

- Fix: LLM no longer returns empty responses in smart_discovery mode (e.g. "Kueche ausschalten")
- Enhanced: Entity Discovery prompt moved to position #2 (HIGHEST PRIORITY) with step-by-step workflow and concrete example
- Enhanced: Entity Control section now includes discovery reminder in smart_discovery mode
- Added: Empty-response retry mechanism -- if LLM returns empty on first iteration, a nudge message triggers re-evaluation
- Added: Discovery mode hint injected into user message context for additional priming
- Files modified: `conversation.py`

### v1.11.9 (2026-02-10) - Prompt Improvements

- Improved: Response confirmations now encourage natural, varied phrasing instead of rigid examples
- Fix: Calendar reminder transition phrase no longer hardcoded in German ("Uebrigens") -- now language-neutral with variation hint
- Removed: Pre-injected entity states (`[States: ...]`) from user message context -- LLM now uses `get_entities` tool for all state lookups
- Files modified: `conversation.py`

### v1.11.8 (2026-02-10) - Group Entity LLM Tool Call Fix

- Fix: LLM now always calls the control tool for group entities, even when context shows "on" state
- Fix: Group entities display member breakdown (e.g., "GROUP(5 members: 3 on, 2 off)") so LLM understands mixed states
- Enhanced: System prompt strengthened with [CRITICAL] rules to prevent tool call skipping based on context states
- Enhanced: Context states now explicitly labeled as "info only - always use control tool for actions"
- Impact: Eliminates cases where LLM says "already on/off" without actually calling the tool
- Files modified: `context/entity_manager.py`, `conversation.py`, `tools/entity_tools.py`, `VERSION.md`

### v1.11.7 (2026-02-09) - Dashboard Button Layout

- Manual Refresh button moved left, icon-only with border
- Auto-Refresh button icon-only (no text label), pulse dot indicator when active
- Both buttons now visually consistent with outlined style
- Files modified: `www/smart-assist-panel.js`, `VERSION.md`

### v1.11.6 (2026-02-09) - Dashboard UI Polish

- Fix: Added consistent spacing (margin-bottom) between all dashboard cards
- Improved: Auto-Refresh button redesigned with reload icon, active interval display, and tooltip
- Files modified: `www/smart-assist-panel.js`, `VERSION.md`

### v1.11.5 (2026-02-09) - Dashboard Auto-Refresh

- Feature: Dashboard now auto-refreshes data on a configurable interval (default: 30 seconds, ON by default)
- Toggle button ("Auto") with pulsing green dot indicator when active
- Interval dropdown: 5s, 10s, 30s, 60s
- Settings persisted in localStorage (smart_assist_auto_refresh, smart_assist_auto_refresh_interval)
- Auto-refresh pauses when browser tab is hidden and resumes (with immediate fetch) on return
- Intervals properly cleaned up on component disconnect
- Files modified: `www/smart-assist-panel.js`, `VERSION.md`

### v1.11.4 (2026-02-09) - Group Entity Handling Fix

- Fix: Group entities (e.g., light groups) no longer incorrectly report "already on/off" when only some members are in the desired state
- The "already on" early-return optimization now detects group entities and always forwards the service call to Home Assistant
- `get_entity_state` now includes individual member states for group entities, giving the LLM full visibility
- System prompt updated with group entity handling guidance
- Files modified: `tools/unified_control.py`, `tools/entity_tools.py`, `conversation.py`

### v1.11.3 (2026-02-08) - History Tab Refresh Fix

- Fix: Refresh button now also reloads History tab data (request history + tool analytics)
- Previously, Refresh only reloaded main dashboard data; History tab required switching away and back
- Files modified: `www/smart-assist-panel.js`

### v1.11.2 (2026-02-08) - Full Index Mode Fix

- Fix: NameError (`caching_enabled` undefined) in `_build_system_prompt` when Entity Discovery mode is set to "full index"
- The `caching_enabled` variable was a leftover from v1.9.2 when the prompt caching toggle was removed
- Now always uses the "check ENTITY INDEX first" instruction for full index mode
- Files modified: `conversation.py`

### v1.11.1 (2026-02-08) - Pipeline Trace Fix

- Fix: Tool calls in non-streaming LLM iterations (iteration 2+) now appear in HA pipeline traces
- Previously only iteration 1 (streaming) tool calls were visible in pipeline events; subsequent tool calls like `control` were invisible despite executing correctly
- Added `_wrap_response_as_delta_stream()` helper to report non-streaming tool calls via `chat_log.async_add_delta_content_stream()`
- Files modified: `conversation.py`

### v1.11.0 (2026-02-08) - Request History and Tool Analytics

**Feature: Per-Request History Log**

- Track individual request metrics: timestamp, tokens (prompt/completion/cached), response time, tools used, success/error status
- Persistent storage via HA Storage API (FIFO eviction at 500 entries)
- Paginated history browser in dashboard History tab
- Per-agent filtering support
- Debounced saves (30s) with forced flush on shutdown

**Feature: Tool Usage Analytics**

- Track tool call frequency, success rates, and average execution times
- Analytics computed on-demand from request history (no dual storage)
- Summary cards: logged requests, avg response time, avg tokens/request, total tool calls
- Tool analytics table: name, calls, success rate, avg time, last used
- Clear history button with optional agent filter

**Technical Changes**

- New module: `context/request_history.py` (RequestHistoryStore, RequestHistoryEntry, ToolCallRecord, ToolAnalytics)
- Per-request token tracking via `_last_prompt_tokens`, `_last_completion_tokens`, `_last_cached_tokens` on LLMMetrics
- Tool execution timing injected via `ToolRegistry.execute()` wrapper
- `_call_llm_streaming_with_tools()` now returns 4-tuple (content, await_response, iterations, tool_records)
- History recorded in `_build_result()` after response delivery (no latency impact)
- 3 new WebSocket commands: `smart_assist/request_history`, `smart_assist/tool_analytics`, `smart_assist/request_history_clear`
- Dashboard: new History tab with tool analytics table, request history table, pagination, clear
- Files modified: `const.py`, `tools/base.py`, `llm/base_client.py`, `llm/openrouter_client.py`, `llm/groq_client.py`, `llm/ollama_client.py`, `conversation.py`, `websocket.py`, `__init__.py`, `www/smart-assist-panel.js`
- Files created: `context/request_history.py`

### v1.10.1 (2026-02-08) - Cancel Handler Agent Selection

- Feature: Per-agent "Use as cancel intent handler" toggle in conversation agent settings
- Cancel intent handler now prefers the explicitly selected agent instead of picking the first available
- Falls back to first available agent if no agent is explicitly selected
- Updated README.md and info.md with cancel intent handler documentation
- Files modified: `__init__.py`, `const.py`, `config_subentry_flows.py`, `manifest.json`, `strings.json`, `en.json`, `de.json`, `README.md`, `info.md`

### v1.10.0 (2026-02-08) - Cancel Intent Handler

**Feature: Cancel Intent Handler (LLM-powered)**

- New custom `HassNevermind` intent handler that returns a spoken TTS confirmation
- Fixes HA Core bug where the built-in handler returns empty speech, causing voice satellites to hang
- Layer 1: Intent handler intercepts hassil-matched cancels ("Cancel", "Abbrechen", "Nevermind") and uses the LLM to generate a brief, natural acknowledgment in the correct language
- Layer 2: System prompt instruction teaches the LLM to recognize cancel intent for phrases hassil does not match (e.g. "vergiss es", "lass mal", "schon gut") -- prevents the LLM from asking "What should I cancel?"
- Falls back to "OK" when no LLM client is available
- Toggleable via global options (Settings > Integrations > Smart Assist > Configure)
- Enabled by default
- No hardcoded translations or phrase lists -- the LLM handles all languages
- Files modified: `__init__.py`, `const.py`, `config_flow.py`, `conversation.py`, `strings.json`, `en.json`, `de.json`

### v1.9.3 (2026-02-08) - Config UI Polish

- Fix: Added descriptions to all switch/toggle entries in config UI (settings + reconfigure)
- Fix: Grouped related config fields logically: LLM, Response, Entities, Features, Memory, Performance
- All 4 config forms updated (Conversation settings/reconfigure, AI Task settings/reconfigure)
- Translations updated (strings.json, en.json, de.json)

### v1.9.2 (2026-02-07) - UI Simplification

- Fix: Language field now defaults to `auto` instead of empty string (description: 'auto' = uses HA language)
- Fix: Removed `Enable prompt caching` switch -- caching is now always active (auto-detected per provider)
- Fix: Removed `Extended cache TTL` switch -- auto-enabled for Anthropic models (detected from model name prefix)
- Fix: Removed `Enable prompt caching` switch from AI Task settings -- always active
- Reduced caching UI from 3 switches to 1 (`Enable cache warming` only)
- Backend auto-detection: Groq always caches, OpenRouter per model, Anthropic extended TTL from model prefix
- Old config values preserved in const.py for backward compatibility (existing installs unaffected)

### v1.9.1 (2026-02-07) - Agent Memory Refinements

- Fix: Removed `entity_mapping` category from agent memory to preserve discovery-first principle
- Fix: Agent memory ranking changed to recency-first (newest memories injected first)
- Fix: Eliminated access_count feedback loop that locked old memories at top
- Feature: Auto-expire agent memories older than 30 days with access_count < 3
- Prompt now explicitly forbids saving entity mappings or entity IDs in agent memory
- access_count still tracked for auto-expire decisions, but no longer determines injection order

### v1.9.0 (2026-02-07) - Agent Memory (Auto-Learning)

**Feature: Agent Auto-Learning**

- New agent-level memory: LLM saves its own observations and patterns
- Agent memory injected as `[AGENT MEMORY]` block in every conversation (independent of user)
- New memory category: `observation` (in addition to existing ones)
- Memory tool supports new `scope: "agent"` for agent-specific memories
- LLM instructed to save only surprising/non-obvious discoveries
- Max 50 agent memories, 15 injected per request
- Configurable via `enable_agent_memory` toggle (default: on when memory is active)
- German and English translations

### v1.8.2 (2026-02-07) - Smart Discovery Fixes

- Fix: Recent Entities context no longer used as entity discovery shortcut (only for pronoun resolution)
- Fix: Control tool now checks state internally and returns "already on/off" - no extra get_entity_state call needed
- Removed get_entity_state pre-check requirement from all Entity Lookup prompts
- Saves 1 tool call per control action (~200-500ms faster)

### v1.8.1 (2026-02-07) - Smart Discovery Prompt Fix

- Fix: LLM now broadens search when initial domain yields no results (e.g. lights registered as `switch`)
- Added domain fallback map: `light->switch`, `fan->switch`, `cover->switch`, `lock->switch`
- LLM instructed to relax area/name filters on empty results
- Added hallucination guard: LLM must not claim actions without calling `control` tool

### v1.8.0 (2026-02-08) - Token-Efficient Entity Discovery

**Feature: Smart Discovery Mode**

- New "Entity Discovery Mode" setting in agent configuration
- **Full Index** (default): All entities listed in system prompt (current behavior)
- **Smart Discovery**: No entity index in prompt -- entities discovered on-demand via `get_entities` tool
- LLM uses domain, area, and name context from user requests to narrow entity searches
- System prompt instructs LLM to always discover entities before controlling them
- `get_entities` tool description adapts based on selected mode
- 100% token savings on entity index (0 tokens vs. 400-4500+ tokens depending on installation size)
- Trade-off: 1-2 extra tool calls per request (~200-500ms) for entity discovery

**Configuration**

- Available in conversation agent Settings and Reconfigure flows
- SelectSelector with dropdown: "Full Index" or "Smart Discovery"
- German and English translations

### v1.7.2 (2026-02-08) - Dashboard Calendar Fix

**Fix: Calendar Tab Resetting to "Disabled"**

- Calendar tab no longer resets to "Calendar context is disabled" after each conversation
- Root cause: WebSocket subscription updates only sent agents/tasks/memory data, omitting calendar
- `forward_update` now includes calendar data via async task
- Frontend merges subscription data (`Object.assign`) instead of replacing `_data` entirely

### v1.7.1 (2026-02-08) - Memory Management UI

**Feature: Memory User Management**

- Rename users: Change display name directly from the dashboard Memory tab
- Merge users: Move all memories from one user profile to another (deduplication, stats merge)
- Delete individual memories from the expanded memory details view
- Added `rename_user()` and `merge_users()` methods to MemoryManager
- Added WebSocket commands: `smart_assist/memory_rename_user`, `smart_assist/memory_merge_users`, `smart_assist/memory_delete`

**Bug Fix: Cache Warming Calendar Announcements**

- Cache warming no longer marks calendar reminders as "announced"
- Added `peek_reminders()` read-only method to CalendarReminderTracker
- Cache warming uses `dry_run=True` to prevent premature reminder consumption

**Bug Fix: First Seen Not Populated in Dashboard**

- `record_conversation()` was defined but never called
- Added call in `_build_result()` so first interaction date is now tracked per user

**Bug Fix: Calendar Reminder Placement**

- Proactive reminders no longer appear at the start of LLM responses
- LLM now answers the user's question first, then appends the reminder at the end

**Feature: Persistent Calendar Reminder State**

- Calendar reminder tracker now uses HA Storage API (`.storage/smart_assist.calendar_reminders`)
- Announced/completed reminder stages survive HA restarts
- Prevents duplicate reminders after reboot

### v1.7.0 (2026-02-08) - Dashboard & UI

**Feature: Custom Sidebar Panel**

- Added `frontend.py` - Registers a custom sidebar panel in HA using `async_register_built_in_panel`
- Panel appears in HA sidebar with "Smart Assist" title and `mdi:brain` icon
- Static path `/api/smart_assist/panel/` serves the panel JS from `www/` directory
- Panel requires admin access, auto-removed on integration unload
- Uses vanilla HTMLElement + Shadow DOM for maximum HA compatibility

**Feature: WebSocket API**

- Added `websocket.py` - Real-time data API for the dashboard frontend
- `smart_assist/dashboard_data` - Returns all agents, tasks, metrics, cache warming data, memory summary, and calendar events
- `smart_assist/memory_details` - Returns detailed memory entries for a specific user (expandable in UI)
- `smart_assist/subscribe` - Real-time subscription for metric updates via HA dispatcher signals
- All commands require admin authentication
- Iterates config subentries to build per-agent and per-task data

**Feature: Dashboard Panel (Web Component)**

- Added `www/smart-assist-panel.js` - Vanilla Web Component with Shadow DOM (~680 lines)
- Three tabs: Overview, Memory, Calendar
- Overview Cards: Total requests, success rate, avg response time, total tokens, cache hit rate
- Token Usage: Horizontal bar chart comparing prompt, completion, and cached tokens
- Cache Performance: Hit/miss counters, hit rate gauge, cache warming status display
- Registered Tools: Visual tag grid showing all tools per agent
- Memory Browser: User table with expandable rows showing individual memories by category
- Calendar Tab: Upcoming events table with reminder status badges (upcoming/pending/announced/passed)
  - Summary cards: event count, calendar entities, pending reminders, announced reminders
  - Events fetched from all HA calendar entities for next 28 hours
  - Status derived from `CalendarReminderTracker` completed stages
- Agent Selector: Tab bar to switch between agents when multiple exist
- Auto-refresh via WebSocket subscription + manual refresh button
- Full HA theme integration via CSS custom properties (dark/light mode)
- Responsive design with narrow mode breakpoints

**Integration Changes**

- `__init__.py`: Registers WebSocket commands and frontend panel on setup, removes panel on unload
- `manifest.json`: Added `frontend` dependency, version bumped to 1.7.0

### v1.6.1 (2026-02-07) - Memory Tool Registration Fix

**Fix: Memory tool not registering despite being enabled in UI**

- `create_tool_registry` was reading `enable_memory` and `enable_web_search` from the parent `ConfigEntry`, but these settings are stored in `ConfigSubentry.data`
- Since `DEFAULT_ENABLE_MEMORY = False` and the parent entry never had the key, the memory tool was never registered
- Added `subentry_data` parameter to `_get_config()` and `create_tool_registry()`
- `_get_config` now checks `subentry_data` first, then `entry.options`, then `entry.data`
- `conversation.py` passes `self._subentry.data` when creating tool registry
- Debug log now also shows `memory_enabled` status for easier diagnostics

### v1.6.0 (2026-02-07) - Memory & Personalization

**Feature: Persistent User Memory**

- Added `MemoryManager` class for long-term memory storage via HA Storage API
- Memories persist across restarts in `.storage/smart_assist_memory`
- 5 memory categories: preference, named_entity, pattern, instruction, fact
- Per-user (max 100) and global (max 50) memory scopes
- LRU eviction when limits are reached, deduplication on save
- Debounced async save (30s) to minimize disk writes
- Memory injection: Top 20 memories injected into system prompt per request
- Hybrid model: injected memories for context + `memory` tool for CRUD

**Feature: Multi-User Identity Resolution**

- Added `UserResolver` with 5-layer identification strategy:
  1. HA authenticated user (Companion App)
  2. Session identity switch ("This is Anna" via `switch_user` action)
  3. Satellite-to-user mapping (configured per satellite)
  4. Presence heuristic (single person home -> auto-identify)
  5. Fallback to `default` profile
- `ConversationSession` tracks `active_user_id` per conversation
- User identity displayed in dynamic context block as `[Current User: Name]`

**Feature: Memory Tool (LLM-facing)**

- New `memory` tool with 6 actions: save, list, update, delete, search, switch_user
- LLM can save new preferences, recall existing memories, and manage profiles
- `switch_user` action updates session identity and loads correct memory profile
- Tool registered conditionally when memory is enabled

**Config: Memory Settings**

- Added `enable_memory` toggle to conversation agent settings (new + reconfigure)
- Added `enable_presence_heuristic` toggle for presence-based user detection (default: off)
- Default memory: disabled (opt-in)
- Added constants: `CONF_ENABLE_MEMORY`, `CONF_ENABLE_PRESENCE_HEURISTIC`, `CONF_USER_MAPPINGS`
- Storage constants: `MEMORY_STORAGE_KEY`, `MEMORY_STORAGE_VERSION`, `MEMORY_MAX_PER_USER` (100), `MEMORY_MAX_GLOBAL` (50), `MEMORY_MAX_CONTENT_LENGTH` (100), `MEMORY_MAX_INJECTION` (20)
- German and English translations added

### v1.5.2 (2026-02-06) - Timer Fix & Roadmap

**Fix: Timer intents failing with device_id=None**

- Added `_device_id` attribute to `BaseTool` for conversation context propagation
- Added `set_device_id()` method to `ToolRegistry` to propagate device_id to all tools
- Conversation handler now sets device_id on tools before execution
- All `ha_intent.async_handle` calls in `TimerTool` now pass `device_id`
- Fixes `Device does not support timers: device_id=None` error when using voice satellites
- Timers now correctly associate with the satellite device that initiated the request

**Documentation: Roadmap Extraction**

- Moved Roadmap section from VERSION.md into dedicated [ROADMAP.md](ROADMAP.md)
- Reorganized completed milestones (v1.1-v1.5) into clean summary
- Added new feature ideas from research (MCP Server, Token-Efficient Discovery, RAG, etc.)
- Renumbered planned versions: v1.6-v1.10

### v1.5.1 (2026-02-06) - Hassfest Fix

**Fix: Missing `intent` dependency in manifest.json**

- Added `intent` to `dependencies` in `manifest.json`
- Required because `timer_tools.py` imports from `homeassistant.helpers.intent`
- Fixes hassfest validation error in HACS CI pipeline

### v1.5.0 (2026-02-04) - Code Quality Refactoring

**Architecture: BaseLLMClient Inheritance**

- All 3 LLM clients (OpenRouter, Groq, Ollama) now extend `BaseLLMClient`
- Eliminated ~340 lines of duplicated code across clients
- Shared session management, retry logic, metrics tracking, and lifecycle methods
- `GroqClient` uses custom `_get_session_timeout()` for provider-specific timeouts
- `OllamaClient` uses `OllamaMetrics(LLMMetrics)` for extended metrics
- Removed phantom `GroqMetrics` import from `__init__.py`
- `LLMClient` type alias now points to `BaseLLMClient` instead of `Union`
- `LLMClientError` now extends `LLMError` for consistent exception hierarchy
- `api_key` parameter now optional (default `""`) for Ollama compatibility
- Added `_get_session_timeout()` overridable method in base class
- OpenRouter debug logging now guarded with `isEnabledFor(DEBUG)` check
- Replaced `hashlib.md5` with `hashlib.sha256` in debug hash computation

**Refactoring: Config Flow Module Split**

- Split `config_flow.py` (1521 lines) into 3 focused modules:
  - `config_flow.py` (357 lines): Main flow handler and entry point
  - `config_validators.py` (300 lines): API validation and model fetching
  - `config_subentry_flows.py` (827 lines): Subentry flow handlers

**Fix: Timer Tools Compatibility**

- Fixed `AttributeError: module 'intent' has no attribute 'IntentNotRegistered'`
- Replaced direct exception import with runtime class name check
- Compatible with all HA versions (pre/post timer intent changes)

**Code Quality Improvements**

- Replaced magic numbers with named constants (`TTS_STREAM_MIN_CHARS`, `MAX_TOOL_ITERATIONS`, `SESSION_MAX_MESSAGES`, `SESSION_RECENT_ENTITIES_MAX`, `SESSION_EXPIRY_MINUTES`)
- Extracted `_is_german()` helper to prevent false positives in language detection
- Fixed `ToolResult(error=...)` to use correct `message` parameter
- Removed unused `ControlCoverTool` (covered by `UnifiedControlTool`)
- Removed unused `ToolParameterType` enum from `tools/base.py`
- Removed unused `Enum` import from `tools/base.py`
- Fixed `hass.data` nested dict initialization with `setdefault()` chain
- Fixed tool error messages using correct `tool_call_id` and `name` instead of `"error"`
- Replaced `hashlib.md5` with `hashlib.sha256` in entity_manager and calendar_reminder
- Moved `datetime` import to module level in `conversation.py`
- Added `test_utils.py` with 35 test cases for utility functions

### v1.4.11 (2026-02-03) - Documentation Update

**Documentation: Ollama Limitations**

- Updated README.md and info.md to document Ollama as third provider
- Added note that Ollama cache metrics are not available (API limitation)
- Updated provider comparison table to include Ollama
- Added Ollama settings section with num_ctx, keep_alive, timeout explanations

### v1.4.10 (2026-02-03) - Always Send Tools to Ollama

**Improvement: Tools Always Sent to Ollama**

- Tools are now always sent to Ollama regardless of model
- Ollama handles model capabilities internally
- Removed blocking `supports_tools()` check
- Known model list now only used for debug logging
- Any Ollama model can now potentially use tool calling

### v1.4.9 (2026-02-03) - Expanded Tool-Capable Models

**Feature: Added More Models to Tool-Calling List**

- Added `gpt-oss` (OpenAI open-weight reasoning models)
- Added `qwen3` (Alibaba Qwen 3)
- Added `granite3` (IBM Granite)
- Added `phi4` (Microsoft Phi-4)
- Added `deepseek-r1` (DeepSeek reasoning models)
- Added `gemma3` (Google Gemma 3)
- These models now get native tool calling support in Ollama

### v1.4.8 (2026-02-03) - Improved Reconfigure UI

**Improvement: Better Field Grouping in Reconfigure**

- Ollama settings now prefixed with "Ollama:" for clear grouping
- Improved description with status list format
- Clearer field labels

### v1.4.7 (2026-02-03) - Fix Reconfigure Error

**Fix: 500 Internal Server Error in Reconfigure**

- Fixed SelectOptionDict not imported error
- Reconfigure flow now works correctly

### v1.4.6 (2026-02-03) - Ollama Settings in Reconfigure

**Feature: Ollama Settings Configurable via Reconfigure**

- Added Context Window Size (num_ctx) to reconfigure form
- Added Keep Model Loaded (keep_alive) dropdown to reconfigure form
- Added Request Timeout to reconfigure form
- Users can now adjust Ollama settings without removing and re-adding the integration

### v1.4.5 (2026-02-03) - Tool Call Compatibility Fix

**Fix: UnifiedControlTool 'state' Parameter Alias**

- Added `state` as an alias for `action` parameter in UnifiedControlTool
- Some models (especially local/non-native tool calling) pass `state` instead of `action`
- Maps `state: "on"/"off"` to `action: "turn_on"/"turn_off"` automatically
- Improves compatibility with models that don't strictly follow tool schemas

### v1.4.4 (2026-02-03) - Reconfigure Flow Ollama Support

**Fix: Ollama Not Showing in Reconfigure Dropdown**

- Added Ollama to the LLM provider options in reconfigure flow
- Users can now switch to Ollama when reconfiguring conversation agents
- Added validation to ensure Ollama is configured before selection
- Added `ollama_not_configured` error message to all translation files

### v1.4.3 (2026-02-03) - Ollama Cache Warming Fix

**Fix: Cache Warming Error**

- Added optional `cached_prefix_length` parameter to `chat_stream()` method
- Parameter is ignored (Ollama handles caching via KV cache)
- Fixes `unexpected keyword argument 'cached_prefix_length'` error during cache warming

### v1.4.2 (2026-02-03) - Ollama Bug Fixes

**Fix: Ollama keep_alive Duration Parsing Error**

- Fixed `time: missing unit in duration "-1"` error
- Added `_format_keep_alive()` helper to send -1 as integer instead of string
- Ollama API now correctly receives keep_alive values

**Fix: Missing chat_stream_full Method**

- Added `chat_stream_full()` method to OllamaClient
- Required for TTS streaming in conversation system
- Returns structured delta events compatible with Groq/OpenRouter clients

### v1.4.1 (2026-02-03) - Reasoning Model Output Cleanup

**Fix: Filter `<think>` Tags from Reasoning Models**

- Added `THINKING_BLOCK_PATTERN` to filter `<think>...</think>` reasoning blocks
- Affects DeepSeek-R1, QwQ, Qwen with thinking, and other Chain-of-Thought models
- TTS output now clean without internal reasoning steps being spoken
- Regex is case-insensitive and handles multi-line content

### v1.4.0 (2026-02-03) - Ollama Integration

**Feature: Local LLM Support with Ollama**

- Added Ollama as third LLM provider for local, private inference
- No API key required - runs entirely on your hardware
- Full tool calling support (llama3.1+, mistral, qwen2.5, command-r)
- Automatic model discovery from local Ollama installation
- Configurable context window size (num_ctx)
- Model persistence with keep_alive setting (-1 = stay loaded)
- KV cache optimization for faster repeated queries

**Configuration Options**

- Ollama server URL (default: http://localhost:11434)
- Model selection with size information
- Keep-alive duration for model persistence
- Context window size (1024-131072 tokens)
- Request timeout (30-600 seconds)

**Privacy Benefits**

- All data stays local - no cloud transmission
- No API costs - only electricity
- 100% availability - no service dependencies
- Full control over model versions

### v1.3.1 (2026-02-03) - Async Fix

**Fix: SyntaxError in conversation.py**

- Fixed `await` outside async function error
- Made `_build_messages_for_llm` async to support thread-safe tool registry
- No changes to prompt caching behavior or static-to-dynamic message order

### v1.3.0 (2026-02-03) - OpenRouter Integration

**Feature: Dual LLM Provider Support**

- Added OpenRouter as alternative LLM provider alongside Groq
- Access to 200+ models (Claude, GPT-4, Llama, Mistral, Gemini, etc.)
- Provider selection in Conversation Agent and AI Task configuration
- Dynamic model list fetched from provider APIs
- OpenRouter-specific provider routing (choose specific cloud providers)
- Automatic provider detection based on configured API keys

**Code Quality Improvements**

- Added asyncio.Lock for thread-safe tool registry initialization
- Created BaseLLMClient abstract class for LLM client code reuse
- Centralized LLM constants (retry logic, timeouts)
- Added ToolParameterType enum for type-safe tool definitions
- Added async context manager support for LLM clients
- Unified logging with exc_info=True pattern
- Fixed mutable default argument anti-pattern
- Created test infrastructure (pytest fixtures, unit tests)
- Fixed 63 markdown linting errors in documentation

### v1.2.9 (2026-02-01) - TTS Delta Listener Fix

**Fix: TTS Streaming After Non-Streaming Iterations**

- Non-streaming responses now notify ChatLog's delta_listener
- TTS stream receives content even when using non-streaming fallback
- Fixes TTS hanging on Companion App after tool calls (web_search + send)

### v1.2.8 (2026-02-01) - TTS Companion App Fix

**Fix: TTS Hanging on Companion App After Tool Calls**

- Only use streaming in the first LLM iteration
- Subsequent iterations (after tool calls) use non-streaming
- Prevents TTS pipeline issues when ChatLog receives multiple streams
- Companion App now correctly plays TTS after web_search + send

### v1.2.7 (2026-02-01) - TTS Fallback Fix

**Fix: TTS Not Working After Non-Streaming Fallback**

- Fixed TTS not playing when streaming falls back to non-streaming
- Fallback response is now properly added to ChatLog for TTS
- Ensures voice confirmation after multi-tool execution (web_search + send)

### v1.2.6 (2026-02-01) - Streaming State Fix

**Fix: "Invalid State" Error After Multi-Tool Execution**

- Fixed error when LLM performs multiple tool calls (e.g., web_search then send)
- ChatLog streaming now falls back to non-streaming on subsequent iterations
- Prevents "invalid state" exception from HA ChatLog API
- Ensures user gets confirmation after successful tool execution

### v1.2.5 (2026-01-31) - Language Consistency Fix

**Fix: LLM No Longer Mixes Languages in Responses**

- Strengthened language instruction in system prompt with [CRITICAL] marker
- Removed English examples from follow-up behavior section that LLM was copying
- Language instruction now explicitly covers follow-ups, confirmations, and errors
- Added instruction to never mix languages in responses

### v1.2.4 (2026-01-31) - Concise Send Responses

**Improvement: LLM Responds Briefly After Sending**

- Updated system prompt to instruct LLM to respond briefly after send actions
- Example: "Sent to your Pixel" instead of repeating the sent content
- User will see the content on their device, no need to read it aloud

### v1.2.3 (2026-01-31) - TTS URL Removal

**Improvement: URLs Always Removed from TTS Output**

- URLs are now always removed from spoken responses, regardless of clean_responses setting
- Prevents TTS from reading out long URLs like "https colon slash slash..."
- Added `remove_urls_for_tts()` utility function

### v1.2.2 (2026-01-31) - Chat History Fix for Tool Results

**Fix: Tool Results Now Included in Conversation History**

- Fixed issue where tool call results (e.g., web search results) were lost between conversation turns
- LLM now receives full context including previous tool calls and their results
- Enables proper follow-up conversations after tool executions (e.g., "send me the link" after a web search)
- Added debug logging for chat history entry types

### v1.2.1 (2026-01-31) - Send Tool Debug Logging

**Improvement: Debug Logging for Send Tool**

- Added debug logging for available notification targets (mobile apps, other services)
- Logs target resolution when send tool is called
- Helps troubleshoot device matching issues

### v1.2.0 (2026-01-31) - Send Tool for Notifications

**New Feature: Universal Send Tool**

Added `send` tool for sending content (links, messages) to notification targets:
- Dynamically discovers all `notify.*` services (mobile apps, Telegram, email, groups, etc.)
- LLM sees available targets in tool description
- Can send links, reminders, or any text content
- Supports single and multiple URLs with actionable notifications

Example flow:
1. LLM has useful information or links to share
2. LLM offers: "Soll ich dir die Links schicken?"
3. User responds: "Ja, auf Patrics Handy" or "Schick es an Telegram"
4. LLM calls `send` tool with content and target
5. User receives notification with clickable links

Features:
- Automatic URL extraction from content
- Single URL: notification clickable to open link
- Multiple URLs: action buttons for up to 3 links
- Fuzzy matching for target names (e.g., "patrics_handy" matches "mobile_app_patrics_iphone")
- Works with any HA notify service (mobile_app, telegram, email, groups, etc.)

### v1.1.3 (2026-01-30) - Follow-up Loop Protection

**Fix: Prevent Infinite Follow-up Loops**

Added protection against endless clarification loops when satellite is triggered by false positive (e.g., TV audio):
- Tracks consecutive follow-up questions per conversation session
- After 3 consecutive follow-ups without meaningful action, conversation aborts
- Returns "I did not understand. Please try again." instead of another question
- Counter resets after any successful tool execution

How it works:
1. Satellite triggered by TV audio (false positive wake word)
2. LLM receives unintelligible input, asks for clarification (followup #1)
3. Satellite listens again, captures more TV audio (followup #2)
4. After 3rd failed attempt, Smart Assist aborts and stops listening

This prevents the satellite from getting stuck in an infinite loop of questions when triggered accidentally.

### v1.1.2 (2026-01-30) - Entity History Periods Aggregation

**Improvement: Better History Output for Binary Entities**

Added `periods` aggregation option to `get_entity_history` tool:
- Calculates on/off time ranges for switches, lights, locks, etc.
- Returns human-readable periods: "from 15:18 to 19:45 (4h 27min)"
- Includes total on-time calculation
- Supports states: on, playing, home, open, unlocked, active, heating, cooling

Example output:
```
switch.keller was on during 24h:
  from 15:18 to 19:45 (4h 27min)
  from 20:01 to 20:03 (2min)
  Total on time: 4h 29min
```

LLM can now say "Das Licht war von 15:18 bis 19:45 Uhr an" instead of just listing state changes.

### v1.1.1 (2026-01-30) - Recorder Dependency Fix

**Bugfix: Missing Recorder Dependency**

- Added `recorder` to manifest.json dependencies
- Required for `get_entity_history` tool to access historical states
- Fixes GitHub Actions CI validation error

### v1.1.0 (2026-01-30) - Entity History Queries & Multi-Turn Context

**New Feature: Entity History Queries**

New `get_entity_history` tool allows querying historical entity states:
- Time periods: 1h, 6h, 12h, 24h, 48h, 7d
- Aggregation modes: raw (all changes), summary (min/max/avg), last_change
- Supports numeric sensors (temperature, humidity) with statistics
- Supports discrete state entities (lights, switches) with occurrence counts

Example queries:
- "How was the temperature yesterday?"
- "When was the light last on?"
- "What was the average humidity in the last 6 hours?"

**New Feature: Multi-Turn Context Improvements**

Enhanced pronoun resolution for natural conversations:
- Tracks last 5 entities interacted with per conversation
- Injects `[Recent Entities]` context for LLM pronoun resolution
- System prompt instructs LLM to use context for "it", "that", "the same one"

Example conversation:
1. User: "Turn on the kitchen light" -> Tracks light.kitchen
2. User: "Make it brighter" -> LLM resolves "it" = light.kitchen
3. User: "What's the temperature?" -> Tracks sensor.kitchen_temp
4. User: "Turn that off" -> LLM resolves "that" = light.kitchen (most recent controllable)

**Implementation Details:**
- `GetEntityHistoryTool` in entity_tools.py - Uses HA recorder/history API
- `RecentEntity` dataclass in context/conversation.py - Tracks entity_id, friendly_name, action, timestamp
- `ConversationSession.recent_entities` - deque with maxlen=5
- Context placed in dynamic section to preserve prompt caching

### v1.0.30 (2026-01-30) - Auto-Detect Questions for Conversation Continuation

**Improvement: Question Detection Fallback**

- Auto-detects when LLM response ends with `?` but forgot to call `await_response` tool
- Automatically enables `continue_conversation` for questions
- Ensures user can always respond to questions, even if LLM doesn't follow instructions perfectly

### v1.0.29 (2026-01-30) - Fix Duplicate Tool Calls

**Fix: Duplicate Tool Call Execution**

- Added deduplication of tool calls by ID before execution
- LLM sometimes sends duplicate tool calls (same ID), now only one is executed
- Changed Music Assistant `play_media` to non-blocking to prevent hanging
- Prevents processing loop getting stuck when Music Assistant takes too long

### v1.0.28 (2026-01-30) - Conditional Music Instructions

**Improvement: Dynamic Prompt Injection Based on Tool Availability**

- Music/Radio Playback instructions now only appear in system prompt when `music_assistant` tool is registered
- Simpler, clearer instructions without conditional logic for the LLM
- Added `has_tool()` method to ToolRegistry for checking tool availability
- Fixed duplicate MusicAssistantTool registration bug

### v1.0.27 (2026-01-30) - Clearer Music Assistant Instructions

**Improvement: Explicit Tool Selection for Music**

- System prompt now explicitly tells LLM to check available tools
- Clear priority: 1) music_assistant tool if available, 2) control tool as fallback
- Clearer separation: control for lights/switches/etc, music_assistant for music/radio
- Improved satellite-to-player mapping reference

### v1.0.26 (2026-01-30) - Music Assistant Detection & System Prompt

**Fix: Music Assistant Tool Detection**

- Improved detection logic with 3 methods:
  1. Check `hass.data` for music_assistant key
  2. Check for MA player attributes (mass_player_id, mass_player_type)
  3. Check if `music_assistant.play_media` service exists
- Added debug logging for detection method
- Added fallback logging when not detected

**New: Music/Radio Playback Instructions in System Prompt**

- Added instructions for when to use `music_assistant` tool
- LLM now knows to use music_assistant for songs, artists, albums, playlists, radio
- References satellite-to-player mapping from user system prompt

### v1.0.25 (2026-01-30) - Satellite Context for Media Playback

**New Feature: Current Assist Satellite in Context**

- Satellite entity_id is now included in the dynamic context
- LLM knows which Assist satellite initiated the request
- Enables automatic media player mapping based on user system prompt

How it works:
- ConversationInput.satellite_id is passed through to message builder
- Added `[Current Assist Satellite: assist_satellite.xxx]` to dynamic context
- User can define mappings in system prompt (satellite -> media_player)

Example user system prompt:
```
Satellite to Media Player Mappings:
- assist_satellite.satellite_kuche_assist_satellit -> media_player.ma_satellite_kuche
- assist_satellite.satellite_flur_assist_satellit -> media_player.ma_satellite_flur
```

Now "play music" without specifying player will use the correct mapped player.

### v1.0.24 (2026-01-30) - Music Assistant Integration

**New Feature: MusicAssistantTool**

- New `music_assistant` tool for advanced music control
- Uses Music Assistant integration for multi-provider support
- Actions: play, search, queue_add

Features:
- Play music from any provider (Spotify, YouTube Music, local files, etc.)
- Internet radio support (TuneIn, Radio Browser, etc.)
- Radio mode for endless dynamic playlists based on seed track/artist
- Queue management (play, replace, next, add)
- Search across all configured providers

Parameters:
- `action`: play, search, queue_add
- `query`: Search term (song, artist, album, playlist, radio station)
- `media_type`: track, album, artist, playlist, radio
- `artist`, `album`: Optional filters
- `player`: Target media player entity_id
- `enqueue`: play, replace, next, add
- `radio_mode`: Enable endless similar music

Examples:
- Play song: `action=play, query="Bohemian Rhapsody", media_type=track`
- Play radio: `action=play, query="SWR3", media_type=radio`
- Radio mode: `action=play, query="Queen", media_type=artist, radio_mode=true`
- Add to queue: `action=queue_add, query="Another One Bites the Dust"`

Tool is automatically available when Music Assistant is installed.

### v1.0.23 (2026-01-30) - Timer Reminders and Delayed Commands

**New Feature: conversation_command Support**

- Timer tool now supports `command` parameter for delayed actions
- Execute any voice command when timer finishes
- Enables voice reminders without separate reminder system
- Uses native Assist `conversation_command` slot

Examples:
- Reminder: `timer(action=start, minutes=30, command="Remind me to drink water")`
- Delayed action: `timer(action=start, hours=1, command="Turn off the lights")`
- Combined: `timer(action=start, minutes=10, name="Pizza", command="Check the oven")`

### v1.0.22 (2026-01-30) - Unified Timer Tool with Native Intents

**Improvement: Simplified Timer Management**

- Single `timer` tool now uses native Assist intents (HassStartTimer, etc.)
- No Timer Helper entities required - uses built-in Assist voice timers
- Removed separate voice_timer tool - one unified timer tool
- Actions: start, cancel, pause, resume, status
- Parameters: hours, minutes, seconds, name

### v1.0.21 (2026-01-30) - Native Voice Timer Support

**New Feature: VoiceTimerTool**

- New `voice_timer` tool using native Assist intents
- Uses HassStartTimer, HassCancelTimer, HassPauseTimer, etc.
- Does NOT require Timer Helper entities - uses built-in Assist voice timers
- Actions: start, cancel, pause, resume, status, add_time, remove_time
- Parameters: hours, minutes, seconds, name, area
- Always available (not domain-dependent)

**Two Timer Options:**
1. `voice_timer` - Native Assist voice timers (satellite-specific, no entities)
2. `timer` - Timer Helper entities (for automations, requires timer domain)

### v1.0.20 (2026-01-30) - Timer Tool

- New `timer` tool for managing HA timer helpers
- Actions: start, cancel, pause, finish, change
- Auto-finds available timer if not specified
- Duration format: HH:MM:SS (e.g., "00:05:00" for 5 minutes)
- Requires timer helper to be configured in HA

### v1.0.19 (2026-01-30) - Calendar: Only Show Upcoming Events

- Fixed: "What's on my calendar today?" no longer returns past events
- get_calendar_events now starts from current time, not midnight
- Past events from today are filtered out

### v1.0.18 (2026-01-30) - Double Cache Warming at Startup

**Improvement: Faster Initial Response**

- Cache warming now runs TWICE at startup
- First warmup creates the cache, second warmup uses it
- Immediate benefit from prompt caching on first user request
- warmup_count sensor now reflects both warmups

### v1.0.17 (2026-01-30) - TTS Response Format Rules

**Improvement: TTS-Optimized Output**

- Added rule: Use plain text only - no markdown, no bullet points, no formatting
- Added rule: Responses are spoken aloud (TTS) - avoid URLs, special characters, abbreviations
- Cleaner audio output from voice assistants

### v1.0.16 (2026-01-30) - English System Prompt Examples

**Improvement: Consistent Language**

- Changed examples in system prompt from German to English
- LLMs understand English instructions better
- Example now uses "Is there anything else I can help with?" instead of German

### v1.0.15 (2026-01-30) - Mandatory await_response for Questions

**Improvement: Stronger System Prompt**

- Added explicit rule: EVERY question MUST use await_response tool
- Clear WRONG vs CORRECT examples in system prompt
- Rule: If response ends with "?", must call await_response
- LLM should no longer ask questions without tool call

### v1.0.14 (2026-01-30) - await_response with Message Parameter

**Improvement: Tool Redesign**

- Added required `message` parameter to await_response tool
- LLM now passes the question text directly in the tool call
- Conversation handler extracts message from tool arguments
- No more reliance on LLM outputting text before tool call
- System prompt updated with new tool usage examples

Example: `await_response(message="Which room?", reason="clarification")`

### v1.0.13 (2026-01-30) - Simplified await_response Tool

**Improvement: Tool Definition**

- Simplified await_response tool description to match other working tools
- Changed reason parameter from optional to required
- Removed verbose instructions from tool description
- Cleaner system prompt with example flow
- Removed text fallback workaround (pure tool-based solution)

### v1.0.12 (2026-01-30) - Text Fallback for await_response

**Bugfix: Model Compatibility**

- Fixed issue where some models (e.g., gpt-oss-120b) output `await_response({...})` as text instead of a proper tool call
- Added regex detection to extract await_response from text output
- Text is cleaned (await_response removed) and conversation continuation is properly set
- Satellites now correctly enter listening mode even when model uses text syntax

### v1.0.11 (2026-01-30) - await_response Fix for Satellites

**Bugfix: Voice Assistant Satellites**

- Fixed issue where satellites (e.g., ESP32-S3) would not enter listening mode after `await_response`
- Root cause: LLM called `await_response` tool without providing speech text first
- Speech was empty, so no audio was played, and satellite never transitioned to listening mode

**Improvements:**

- Updated system prompt with explicit instruction to ALWAYS include text BEFORE calling `await_response`
- Enhanced `await_response` tool description with clear examples of correct/incorrect usage
- Added warning log when `await_response` is called without response text

### v1.0.10 (2026-01-29) - await_response Tool

**Refactor: Conversation Continuation**

- Replaced text marker `[AWAIT_RESPONSE]` with `await_response` tool
- LLM now calls a tool to signal "keep microphone open" instead of adding text markers
- Prevents LLM from inventing markers like `[Keine weitere Aktion nötig]` or `[No action needed]`
- Deterministic, debuggable (tool calls visible in logs)
- System prompt updated with clear tool usage instructions
- Proactive follow-up: LLM can now ask "Is there anything else I can help with?"

**Benefits:**
- No more random action status tags in TTS output
- Cleaner, more predictable conversation flow
- Better for AI Tasks that need user confirmation

### v1.0.9 (2026-01-29) - TTS Cleanup for Action Tags

- Removed action status tags from TTS output (e.g., [Keine weitere Aktion nötig], [No action needed])
- These LLM action indicators are now stripped before speech synthesis

### v1.0.8 (2026-01-29) - Cache Warming Sensor Update Fix

- Fixed sensors not updating after cache warming (missing dispatcher signal)
- Fixed Groq client double-counting usage metrics (usage sent twice in stream)
- Cache warming requests now correctly contribute to all metric sensors

### v1.0.7 (2026-01-29) - Cached Tokens Tracking Fix

- Fixed cached_tokens metric not being tracked in OpenRouter client
- Cache warming now correctly contributes to average cached tokens sensor
- Note: For device grouping issues, please remove and re-add the Smart Assist integration

### v1.0.6 (2026-01-29) - Per-Agent Metrics (Bugfix)

**Bugfixes**

- Fixed sensor subentry grouping: sensors now correctly appear only under their respective agent/task device
- Fixed Cache Warming sensor state class (string status, not measurement)

### v1.0.5 (2026-01-29) - Per-Agent Metrics

**Improvements**

- **Per-Agent Sensors**: Metrics are now tracked per Conversation Agent and AI Task instead of aggregated
  - Each agent/task now has its own set of sensors (response time, requests, tokens, cache hits, etc.)
  - Sensors are grouped under the respective device in Home Assistant
- **Average Cached Tokens Sensor**: New sensor showing average cached tokens per request
  - Formula: `cached_tokens / successful_requests`
  - Helps track caching efficiency per agent
- **Cache Warming Status Sensor**: New sensor for agents with cache warming enabled
  - Shows warming status: "active", "warming", "inactive"
  - Attributes: last_warmup, next_warmup, warmup_count, warmup_failures, interval_minutes
- **AI Task Metrics**: AI Task entities now also have their own metric sensors
  - Average Response Time, Total Requests, Success Rate, Total Tokens
- Cache warming now tracks success/failure counts and timestamps
- Dispatcher signals changed from entry-level to subentry-level for better isolation

### v1.0.4 (2026-01-28) - API Key Reconfigure

**New Feature**

- Added reconfigure flow for parent entry to update API keys
- Go to Settings -> Integrations -> Smart Assist -> Configure to change API keys
- Both Groq and OpenRouter API keys can be updated without removing the integration

### v1.0.3 (2026-01-28) - API Key Storage Fix

**Bugfix**

- Fixed API key incorrectly being copied to subentry data during reconfigure
- This caused "Invalid API Key" errors after reconfiguring a conversation agent
- API keys are now correctly read from parent entry only

### v1.0.2 (2026-01-28) - Reliability Improvements

**HTTP Client Reliability Enhancements**

- Added granular timeouts (connect=10s, sock_connect=10s, sock_read=30s)
- Session auto-renewal after 4 minutes to prevent stale HTTP connections
- Explicit timeout error handling with separate exception handler
- Improved error logging: all failures now logged with attempt count
- Final failure always logged at ERROR level with full context

### v1.0.1 (2026-01-28) - Bugfixes

**Bugfixes**

- Fixed Media Player select_source for devices without SELECT_SOURCE feature
- Added legacy API key location fallback for config migrations
- Reduced 401 log level to DEBUG when fetching Groq models (expected behavior)
- Restored info.md for HACS repository description

### v1.0.0 (2026-01-28) - Initial Release

**Smart Assist** is a fast, LLM-powered smart home assistant for Home Assistant with automatic prompt caching.

#### Core Features

- **Groq Integration**: Direct Groq API with automatic prompt caching (2-hour TTL)
- **Natural Language Control**: Control your smart home with natural language
- **Unified Control Tool**: Single efficient tool for all entity types (lights, switches, climate, covers, media players, fans)
- **Parallel Tool Execution**: Execute multiple tool calls concurrently for faster responses
- **Full Streaming**: Real-time token streaming to TTS, even during tool execution
- **Prompt Caching**: ~90% cache hit rate with Groq for faster responses

#### Calendar Integration

- **Read Events**: Query upcoming events from all calendars
- **Create Events**: Create timed or all-day events with fuzzy calendar matching
- **Proactive Reminders**: Staged context injection (24h, 4h, 1h before events)

#### AI Task Platform

- **Automation Integration**: Use LLM in automations via ai_task.generate_data service
- **Background Tasks**: Summarize data, generate reports without user interaction
- **Full Tool Support**: All tools available in automation context

#### Performance and Telemetry

- **Cache Warming**: Optional periodic cache refresh for instant responses
- **Metrics Sensors**: Track token usage, response times, cache hit rates
  - Average Response Time (ms)
  - Request Count
  - Success Rate (%)
  - Token Usage
  - Cache Hits
  - Cache Hit Rate (%)

#### Additional Features

- **Web Search**: DuckDuckGo integration for real-time information
- **Multi-Language**: Supports any language (auto-detect from HA or custom)
- **Debug Logging**: Detailed logging for troubleshooting

#### Available Tools

| Tool                    | Description                                |
| ----------------------- | ------------------------------------------ |
| get_entities            | Query available entities by domain/area    |
| get_entity_state        | Get detailed entity state with attributes  |
| control                 | Unified control for all entity types       |
| run_scene               | Activate scenes                            |
| trigger_automation      | Trigger automations                        |
| get_calendar_events     | Query upcoming calendar events             |
| create_calendar_event   | Create new calendar events                 |
| get_weather             | Current weather information                |
| web_search              | DuckDuckGo web search                      |

#### Supported Models

| Model                             | Description                 |
| --------------------------------- | --------------------------- |
| llama-3.3-70b-versatile           | Llama 3.3 70B (Recommended) |
| openai/gpt-oss-120b               | GPT-OSS 120B                |
| openai/gpt-oss-20b                | GPT-OSS 20B (Faster)        |
| moonshotai/kimi-k2-instruct-0905  | Kimi K2                     |

#### Requirements

- Home Assistant 2024.1 or newer
- Python 3.12+
- Groq API key

---

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full feature roadmap.

---

## Technology Stack

| Technology       | Version  | Purpose                    |
| ---------------- | -------- | -------------------------- |
| Python           | 3.12+    | Core language              |
| Home Assistant   | 2024.1+  | Smart home platform        |
| aiohttp          | 3.8.0+   | Async HTTP client          |
| Groq API         | latest   | LLM inference              |
| DuckDuckGo ddgs  | 7.0.0+   | Web search integration     |

## License

MIT License - see LICENSE for details.
