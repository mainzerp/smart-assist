"""Prompt building and message construction for Smart Assist conversation."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any, TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .const import (
    CONF_ASK_FOLLOWUP,
    CONF_CALENDAR_CONTEXT,
    CONF_CONFIRM_CRITICAL,
    CONF_ENABLE_AGENT_MEMORY,
    CONF_ENABLE_CANCEL_HANDLER,
    CONF_ENTITY_DISCOVERY_MODE,
    CONF_EXPOSED_ONLY,
    CONF_LANGUAGE,
    CONF_MAX_HISTORY,
    CONF_USER_SYSTEM_PROMPT,
    DEFAULT_ASK_FOLLOWUP,
    DEFAULT_CALENDAR_CONTEXT,
    DEFAULT_ENABLE_AGENT_MEMORY,
    DEFAULT_ENABLE_CANCEL_HANDLER,
    DEFAULT_ENTITY_DISCOVERY_MODE,
    DEFAULT_MAX_HISTORY,
    DEFAULT_USER_SYSTEM_PROMPT,
    LOCALE_TO_LANGUAGE,
)
from .llm.models import ChatMessage, MessageRole, ToolCall

if TYPE_CHECKING:
    from homeassistant.components.conversation import ChatLog
    from .conversation import SmartAssistConversationEntity

_LOGGER = logging.getLogger(__name__)


async def build_system_prompt(entity: SmartAssistConversationEntity) -> str:
    """Build or return cached system prompt based on configuration.

    System prompt is always in English (best LLM performance).
    Only the response language instruction is configurable.

    The prompt is cached after first build since config rarely changes.
    If config is updated, the entity is reloaded anyway.
    """
    # Return cached prompt if available
    if entity._cached_system_prompt is not None:
        return entity._cached_system_prompt

    language = entity._get_config(CONF_LANGUAGE, "")

    # Determine language instruction for response
    if not language or language == "auto":
        # Auto-detect: use Home Assistant's configured language
        ha_language = entity.hass.config.language  # e.g., "de-DE", "en-US"
        locale_prefix = ha_language.split("-")[0].lower()  # "de", "en", etc.

        if locale_prefix in LOCALE_TO_LANGUAGE:
            english_name, native_name = LOCALE_TO_LANGUAGE[locale_prefix]
            language_instruction = f"Always respond in {english_name} ({native_name})."
        else:
            # Fallback: use the locale as-is
            language_instruction = f"Always respond in the language with code '{ha_language}'."
    else:
        # User-specified language - use directly
        language_instruction = f"Always respond in {language}."

    confirm_critical = entity._get_config(CONF_CONFIRM_CRITICAL, True)
    exposed_only = entity._get_config(CONF_EXPOSED_ONLY, True)
    ask_followup = entity._get_config(CONF_ASK_FOLLOWUP, DEFAULT_ASK_FOLLOWUP)

    parts = []

    # Base prompt - minimal, role defined in user prompt
    # Language instruction is emphasized and placed prominently
    parts.append(f"""You are a smart home assistant.

## LANGUAGE REQUIREMENT [CRITICAL]
{language_instruction} This applies to ALL responses including follow-up questions, confirmations, and error messages. Never mix languages.""")

    # Entity discovery strategy (placed early for maximum LLM attention)
    discovery_mode = entity._get_config(CONF_ENTITY_DISCOVERY_MODE, DEFAULT_ENTITY_DISCOVERY_MODE)
    if discovery_mode == "smart_discovery":
        parts.append("""
## MANDATORY WORKFLOW -- Entity Discovery [HIGHEST PRIORITY]
You have NO entity information. You do NOT know any entity IDs.
For ANY request involving devices, lights, switches, sensors, or any home entity:

STEP 1: Call get_entities(domain=...) to discover entities
  - Infer domain from intent: "light"/"lamp" -> domain="light"; "turn off kitchen" -> try "light", then "switch"
  - Use area parameter for room context: use the EXACT area name from the AVAILABLE AREAS list below
  - Use name_filter for specific devices: "desk lamp" -> domain="light", name_filter="desk"
STEP 2: Use the entity_id(s) from the results to call control() or get_entity_state()

You MUST call get_entities BEFORE any control action. You do NOT know any entity IDs without it.
ONLY if get_entities returns ZERO results, try a related domain (light->switch, fan->switch, cover->switch). Do NOT search additional domains if you already found matching entities.

EXAMPLE - Room command with group entity (PREFERRED):
  User: "turn off kitchen"
  -> get_entities(domain="light", area="<matching area from AVAILABLE AREAS>")
  -> Result includes light.kitchen [GROUP, 5 members] + individual members
  -> control(entity_id="light.kitchen", action="turn_off")  // Group controls all members!
  -> Response: (confirm in configured language)

EXAMPLE - Room command without group entity (use batch):
  User: "turn off bedroom"
  -> get_entities(domain="light", area="<matching area from AVAILABLE AREAS>")
  -> Result: light.bedroom_ceiling, light.bedroom_lamp (no GROUP entity)
  -> control(entity_ids=["light.bedroom_ceiling", "light.bedroom_lamp"], action="turn_off")

EXAMPLE - Specific device:
  User: "turn on desk lamp"
  -> get_entities(domain="light", name_filter="desk")
  -> Result: light.desk_lamp
  -> control(entity_id="light.desk_lamp", action="turn_on")

DECISION LOGIC:
1. If a GROUP entity matches the user's room/area intent -> control just the group (it handles members internally)
2. If no group entity but user wants all entities in area -> use entity_ids to batch-control all
3. If user names a specific device -> use entity_id for that one entity

NEVER respond without calling tools when the user asks about devices.
NEVER fabricate entity IDs. NEVER say "I don't have access to entities."
- NEVER use entity_ids from [Recent Entities] for new requests - those are ONLY for resolving pronouns ("it", "that", "the same one")""")

        # Inject available area names so LLM uses correct names
        from homeassistant.helpers import area_registry as ar
        area_reg = ar.async_get(entity.hass)
        area_names = sorted(area.name for area in area_reg.async_list_areas())
        if area_names:
            parts.append(f"""
## AVAILABLE AREAS
Use these EXACT area names for get_entities(area=...): {', '.join(area_names)}
Match the user's spoken room/area to the closest name from this list.""")

    # Response format guidelines
    parts.append("""
## Response Format
- Keep responses brief (1-2 sentences for actions, 2-3 for information)
- Confirm actions naturally and concisely - vary your wording, be creative but short (e.g. "Done!", "Light's on.", "All set.", "Living room light is on now.")
- ALWAYS use tools to check states - never guess or assume values
- Use plain text only - no markdown, no bullet points, no formatting
- Responses are spoken aloud (TTS) - avoid URLs, special characters, abbreviations""")

    # Response rules with conversation continuation marker
    if ask_followup:
        parts.append("""
## Follow-up Behavior
- Offer follow-up when useful (ambiguous request, multiple options)
- Do NOT offer follow-up for every simple action
- For simple completed actions, just confirm briefly without asking follow-up

## MANDATORY: Questions Require await_response Tool
If you need to ask the user something, you MUST use the await_response tool.
Without it, the user CANNOT respond to your question.

Example (note: always use the configured response language, not English):
await_response(message="[your question in user's language]", reason="follow_up")

If your response ends with a question mark (?), you MUST call await_response.""")
    else:
        parts.append("""
## Response Rules
- Do NOT ask follow-up questions
- Keep responses action-focused
- If uncertain about entity, ask for clarification""")

    # Entity lookup strategy (smart_discovery handled above, near top of prompt)
    if discovery_mode != "smart_discovery":
        parts.append("""
## Entity Lookup
1. Check ENTITY INDEX first to find entity_ids
2. Only use get_entities tool if not found in index""")

    # Pronoun resolution hint
    parts.append("""
## Pronoun Resolution
When user says "it", "that", "the same one", check [Recent Entities] in context to identify the referenced entity.""")

    # Calendar reminders instruction (if enabled) - compact version
    calendar_enabled = entity._get_config(CONF_CALENDAR_CONTEXT, DEFAULT_CALENDAR_CONTEXT)
    if calendar_enabled:
        parts.append("""
## Calendar Reminders [MANDATORY]
When CURRENT CONTEXT contains '## Calendar Reminders [ACTION REQUIRED]':
- FIRST answer the user's actual question/request completely
- THEN append the reminder at the END of your response as a natural, separate sentence
- Use a casual transition phrase in the response language (e.g. "By the way", "Oh, just so you know", "Also") - vary the phrasing each time, do not repeat the same transition
- Format: "[your complete answer]. [transition phrase], [reminder text]."
- NEVER start your response with the reminder or weave it into unrelated answers""")

    # Control instructions - compact
    # In smart_discovery mode, add reminder that get_entities comes first
    control_preamble = ""
    if discovery_mode == "smart_discovery":
        control_preamble = "\nREMINDER: You must call get_entities() first to discover entity IDs before using control.\n"

    parts.append(f"""
## Entity Control [CRITICAL]{control_preamble}
Use 'control' tool for lights, switches, covers, fans, climate, locks, etc.
Domain auto-detected from entity_id.

MANDATORY RULES:
- ALWAYS call the 'control' tool for ANY on/off/toggle request. NEVER skip the tool call.
- Do NOT say "already on" or "already off" based on context states - the tool handles idempotency.
- Group entities (marked GROUP in states): state 'on' means ANY member is on, NOT all. Always call the tool.
- Context states are informational ONLY. The tool decides whether action is needed.
- If user says "turn on X" → call control(entity_id, action=turn_on). Always. No exceptions.

GROUP ENTITIES: If search results include a GROUP entity for the target area, prefer controlling the group.
A group entity controls all its members in one call. Do NOT control individual members separately.

BATCH CONTROL (when no group exists):
- Use entity_ids (array) to control multiple entities: control(entity_ids=[...], action="turn_off")
- Use entity_ids when: user wants all entities in a room AND no group entity covers them
- Use entity_id (singular) when: user names a specific device OR a group entity covers the room""")

    # Music/Radio instructions - only if music_assistant tool is registered
    if (await entity._get_tool_registry()).has_tool("music_assistant"):
        parts.append("""
## Music/Radio Playback [IMPORTANT]
For starting or searching music, radio, or media, use the 'music_assistant' tool:
- action='play', query='[song/artist/radio station]', media_type='track/album/artist/playlist/radio'
- action='search' to find music without playing
- action='queue_add' to add to current queue
- For player selection: Check [Current Assist Satellite] context and use your satellite-to-player mapping from your instructions
- Do NOT use 'control' tool to START music/radio - it cannot search or stream content

For TRANSPORT CONTROLS (stop, pause, resume, next, previous, volume), use the 'control' tool with the media_player entity:
- control(entity_id="media_player.xxx", action="media_stop") to stop
- control(entity_id="media_player.xxx", action="media_pause") to pause
- control(entity_id="media_player.xxx", action="media_play") to resume
- control(entity_id="media_player.xxx", action="volume_set", value=0.5) for volume""")

    # Send/notification instructions - only if send tool is registered
    if (await entity._get_tool_registry()).has_tool("send"):
        parts.append("""
## Sending Content
You can send content (links, text, messages) to devices using the 'send' tool.
- Offer when you have useful links or information to share
- User specifies target device (e.g., "Patrics Handy", "my phone", "Telegram")
- IMPORTANT: After sending, respond briefly: "Sent to [device]." or "I've sent it to your [device]."
- Do NOT repeat the content in your spoken response - the user will see it on the device""")

    # Critical actions confirmation
    if confirm_critical:
        parts.append("""
## Critical Actions
Ask for confirmation before: locking doors, arming alarms, disabling security.""")

    # Memory instructions (if enabled)
    if entity._memory_enabled:
        parts.append("""
## User Memory [IMPORTANT]
Known user memories are injected as [USER MEMORY] in context. Use them to personalize responses.
- SAVE new preferences, names, patterns, and instructions via the 'memory' tool
- DO NOT re-save information already in [USER MEMORY]
- When user says "I am [Name]" or "This is [Name]", use memory(action='switch_user', content='[name]')
- Keep memory content concise (max 100 chars)
- Use appropriate categories: preference, named_entity, pattern, instruction, fact""")

    # Agent Memory auto-learning instructions (if enabled)
    agent_memory_enabled = entity._memory_enabled and entity._get_config(
        CONF_ENABLE_AGENT_MEMORY, DEFAULT_ENABLE_AGENT_MEMORY
    )
    if agent_memory_enabled:
        parts.append("""
## Agent Memory [AUTO-LEARNING]
Your own observations are injected as [AGENT MEMORY]. Use them to work more efficiently.
- Save ONLY surprising or non-obvious discoveries via memory(action='save', scope='agent')
- Use category 'observation' for system-level insights (e.g. "Covers use position 0-100, not open/close")
- Use category 'pattern' for recurring user habits (e.g. "Patric asks for weather every morning")
- Do NOT save entity mappings or entity IDs - always use get_entities to discover entities
- Do NOT re-save information already in [AGENT MEMORY]
- Max 100 chars per memory entry""")

    # Exposed only notice
    if exposed_only:
        parts.append("""
## Notice
Only exposed entities are available.""")

    # Cancel/abort handling instruction (if enabled globally)
    cancel_enabled = entity._get_global_config(
        CONF_ENABLE_CANCEL_HANDLER, DEFAULT_ENABLE_CANCEL_HANDLER
    )
    if cancel_enabled:
        parts.append("""
## Cancel/Abort Handling [IMPORTANT]
If the user says something that clearly means they want to cancel, abort, or dismiss
the current interaction (e.g. "cancel", "never mind", "abbrechen", "vergiss es",
"lass mal", "schon gut", "forget it"), respond with a VERY brief acknowledgment
(1-3 words) and do NOT ask follow-up questions.
CRITICAL: Do NOT interpret these phrases as requests to cancel specific devices,
timers, or automations. They mean "I don't need anything anymore."
Do NOT ask "What should I cancel?" -- just confirm briefly.""")

    # Error handling - compact
    parts.append("""
## Errors
If action fails or entity not found, explain briefly and suggest alternatives.""")

    # Cache the built prompt for subsequent calls
    entity._cached_system_prompt = "\n".join(parts)
    _LOGGER.debug("System prompt cached (length: %d chars)", len(entity._cached_system_prompt))

    return entity._cached_system_prompt


async def get_calendar_context(entity: SmartAssistConversationEntity, dry_run: bool = False) -> str:
    """Get upcoming calendar events for context injection.

    Returns reminders for events in appropriate reminder windows.
    Only fetches if calendar_context is enabled in config.

    Args:
        dry_run: If True, don't mark reminders as completed (for cache warming).

    Returns:
        Formatted string with calendar reminders, or empty string if none.
    """
    calendar_enabled = entity._get_config(CONF_CALENDAR_CONTEXT, DEFAULT_CALENDAR_CONTEXT)
    _LOGGER.debug("Calendar context enabled: %s", calendar_enabled)
    if not calendar_enabled:
        return ""

    try:
        now = dt_util.now()
        # Get events for next 28 hours to cover day-before reminders
        end = now + timedelta(hours=28)

        # Get all calendar entities
        calendars = [
            state.entity_id
            for state in entity.hass.states.async_all()
            if state.entity_id.startswith("calendar.")
        ]

        _LOGGER.debug("Found %d calendar entities: %s", len(calendars), calendars)

        if not calendars:
            return ""

        # Fetch events from all calendars
        all_events: list[dict] = []
        for cal_id in calendars:
            try:
                result = await entity.hass.services.async_call(
                    "calendar",
                    "get_events",
                    {
                        "entity_id": cal_id,
                        "start_date_time": now.isoformat(),
                        "end_date_time": end.isoformat(),
                    },
                    blocking=True,
                    return_response=True,
                )

                _LOGGER.debug("Calendar %s result: %s", cal_id, result)

                if result and cal_id in result:
                    # Extract owner from calendar entity
                    state = entity.hass.states.get(cal_id)
                    if state and state.attributes.get("friendly_name"):
                        owner = state.attributes["friendly_name"]
                    else:
                        name = cal_id.split(".", 1)[-1]
                        owner = name.replace("_", " ").title()

                    for event in result[cal_id].get("events", []):
                        all_events.append({
                            "summary": event.get("summary", "Termin"),
                            "start": event.get("start"),
                            "owner": owner,
                        })
            except Exception as err:
                _LOGGER.debug("Failed to fetch calendar events from %s: %s", cal_id, err)

        _LOGGER.debug("Found %d events total: %s", len(all_events), all_events)

        if not all_events:
            return ""

        # Get reminders that should be shown
        if dry_run:
            reminders = entity._calendar_reminder_tracker.peek_reminders(all_events, now)
        else:
            reminders = entity._calendar_reminder_tracker.get_reminders(all_events, now)
            # Persist state after marking reminders
            await entity._calendar_reminder_tracker.async_save()

        _LOGGER.debug("Reminders to show: %s", reminders)

        if not reminders:
            return ""

        # Format with emphasis markers for LLM attention
        reminder_text = "\n".join(f"- {r}" for r in reminders)
        return f"\n## Calendar Reminders [ACTION REQUIRED]\n{reminder_text}"

    except Exception as err:
        _LOGGER.warning("Failed to get calendar context: %s", err)
        return ""


async def build_messages_for_llm_async(
    entity: SmartAssistConversationEntity,
    user_text: str,
    chat_log: ChatLog | None = None,
    satellite_id: str | None = None,
    device_id: str | None = None,
    conversation_id: str | None = None,
    user_id: str = "default",
    dry_run: bool = False,
) -> tuple[list[ChatMessage], int]:
    """Build the message list for LLM request (async version with calendar context).

    Args:
        user_text: The current user message
        chat_log: Optional ChatLog containing conversation history
        satellite_id: Optional satellite entity_id that initiated the request
        device_id: Optional device_id that initiated the request
        conversation_id: Optional conversation ID for recent entity context
        user_id: Resolved user identifier for memory personalization
        dry_run: If True, don't mark calendar reminders as completed

    Returns:
        Tuple of (messages, cached_prefix_length)
    """
    # Get calendar context asynchronously
    calendar_context = await get_calendar_context(entity, dry_run=dry_run)
    _LOGGER.debug("Calendar context from _get_calendar_context: len=%d", len(calendar_context) if calendar_context else 0)

    # Get recent entities context for pronoun resolution
    recent_entities_context = ""
    if conversation_id:
        recent_entities_context = entity._conversation_manager.get_recent_entities_context(
            conversation_id
        )
        if recent_entities_context:
            _LOGGER.debug("Recent entities context: %s", recent_entities_context)

    # Build base messages (now async due to tool registry access)
    return await build_messages_for_llm(
        entity, user_text, chat_log, calendar_context, satellite_id, device_id,
        recent_entities_context, user_id=user_id,
    )


async def build_messages_for_llm(
    entity: SmartAssistConversationEntity,
    user_text: str,
    chat_log: ChatLog | None = None,
    calendar_context: str = "",
    satellite_id: str | None = None,
    device_id: str | None = None,
    recent_entities_context: str = "",
    user_id: str = "default",
) -> tuple[list[ChatMessage], int]:
    """Build the message list for LLM request.

    Message order optimized for prompt caching (static prefix first):
    1. System prompt (static/cached)
    2. User system prompt (static/cached)
    3. Entity index (static/cached - changes only when entities change)
    4. User memory injection (semi-static - changes when memories change)
    5. Conversation history (dynamic)
    6. Current context + user message (dynamic - time, states, calendar, recent entities)

    Args:
        user_text: The current user message
        chat_log: Optional ChatLog containing conversation history
        calendar_context: Optional calendar reminder context
        satellite_id: Optional satellite entity_id
        device_id: Optional device_id
        recent_entities_context: Optional recent entities for pronoun resolution
        user_id: Resolved user identifier for memory personalization

    Returns:
        Tuple of (messages, cached_prefix_length) where cached_prefix_length
        is the number of static messages that should be cached.
    """
    messages: list[ChatMessage] = []
    cached_prefix_length = 0  # Track how many messages are static/cacheable

    # 1. Technical system prompt (cached)
    system_prompt = await build_system_prompt(entity)
    messages.append(
        ChatMessage(role=MessageRole.SYSTEM, content=system_prompt)
    )
    cached_prefix_length += 1

    # 2. User system prompt (cached - optional)
    user_prompt = entity._get_config(
        CONF_USER_SYSTEM_PROMPT, DEFAULT_USER_SYSTEM_PROMPT
    )
    if user_prompt:
        messages.append(
            ChatMessage(role=MessageRole.SYSTEM, content=user_prompt)
        )
        cached_prefix_length += 1

    # 3. Entity index (cached - skip in smart_discovery mode)
    discovery_mode = entity._get_config(CONF_ENTITY_DISCOVERY_MODE, DEFAULT_ENTITY_DISCOVERY_MODE)

    if discovery_mode == "smart_discovery":
        # Smart Discovery: NO entity index injected -- LLM discovers via tool
        _LOGGER.debug("Smart Discovery mode: skipping entity index injection")
    else:
        entity_index, index_hash = entity._entity_manager.get_entity_index()

        # Only update cache if hash changed
        if index_hash != entity._cached_index_hash:
            entity._cached_entity_index = entity_index
            entity._cached_index_hash = index_hash
            _LOGGER.debug("Entity index updated (hash: %s)", index_hash)

        messages.append(
            ChatMessage(
                role=MessageRole.SYSTEM,
                content=f"[ENTITY INDEX]\nUse this index first to find entity IDs. Only use get_entities tool if entity not found here.\n{entity._cached_entity_index}",
            )
        )
        cached_prefix_length += 1

    # 4. User memory injection (semi-static - changes when memories change)
    if entity._memory_enabled and entity._memory_manager:
        memory_text = entity._memory_manager.get_injection_text(user_id)
        if memory_text:
            messages.append(
                ChatMessage(role=MessageRole.SYSTEM, content=memory_text)
            )
            cached_prefix_length += 1
            _LOGGER.debug("Injected memory block for user '%s'", user_id)

    # 4b. Agent memory injection (LLM's own observations and learnings)
    agent_memory_enabled = entity._memory_enabled and entity._get_config(
        CONF_ENABLE_AGENT_MEMORY, DEFAULT_ENABLE_AGENT_MEMORY
    )
    if agent_memory_enabled and entity._memory_manager:
        agent_text = entity._memory_manager.get_agent_injection_text()
        if agent_text:
            messages.append(
                ChatMessage(role=MessageRole.SYSTEM, content=agent_text)
            )
            cached_prefix_length += 1
            _LOGGER.debug("Injected agent memory block")

    # 5. Conversation history from ChatLog (if available)
    # Placed BEFORE dynamic context to maximize cache prefix length
    # IMPORTANT: Also include tool calls and results for context continuity
    if chat_log is not None:
        try:
            max_history = int(entity._get_config(CONF_MAX_HISTORY, DEFAULT_MAX_HISTORY))

            # Safely get content from chat_log
            content = getattr(chat_log, 'content', None)
            if content is None:
                _LOGGER.debug("ChatLog has no content attribute")
            else:
                try:
                    history_entries = list(content)
                except (TypeError, AttributeError) as e:
                    _LOGGER.debug("Could not iterate chat_log.content: %s", e)
                    history_entries = []

                # Limit history to max_history entries (most recent)
                if len(history_entries) > max_history:
                    history_entries = history_entries[-max_history:]

                # Debug: log history entry types
                entry_types = [type(e).__name__ for e in history_entries]
                _LOGGER.debug("ChatLog history types: %s", entry_types)

                for entry in history_entries:
                    entry_type = type(entry).__name__

                    if entry_type == "UserContent":
                        if hasattr(entry, 'content') and entry.content:
                            messages.append(ChatMessage(role=MessageRole.USER, content=entry.content))

                    elif entry_type == "AssistantContent":
                        # Process assistant content with potential tool calls
                        assistant_content = getattr(entry, 'content', '') or ''
                        tool_calls_list: list[ToolCall] = []

                        # Extract tool calls from history for context
                        if hasattr(entry, 'tool_calls') and entry.tool_calls:
                            for tc in entry.tool_calls:
                                tool_calls_list.append(ToolCall(
                                    id=getattr(tc, 'id', f"tc_{len(tool_calls_list)}"),
                                    name=getattr(tc, 'tool_name', 'unknown'),
                                    arguments=getattr(tc, 'tool_args', {}),
                                ))

                        if assistant_content or tool_calls_list:
                            messages.append(ChatMessage(
                                role=MessageRole.ASSISTANT,
                                content=assistant_content,
                                tool_calls=tool_calls_list if tool_calls_list else None,
                            ))

                    elif entry_type == "ToolResultContent":
                        # Include tool results so LLM knows what tools returned
                        tool_result = getattr(entry, 'tool_result', None)
                        tool_name = getattr(entry, 'tool_name', 'unknown')
                        tool_call_id = getattr(entry, 'id', 'unknown')

                        # Format tool result as string
                        result_content = ""
                        if tool_result is not None:
                            if isinstance(tool_result, str):
                                result_content = tool_result
                            elif isinstance(tool_result, dict):
                                result_content = json.dumps(tool_result, ensure_ascii=False)
                            else:
                                result_content = str(tool_result)

                        if result_content:
                            messages.append(ChatMessage(
                                role=MessageRole.TOOL,
                                content=result_content,
                                tool_call_id=tool_call_id,
                                name=tool_name,
                            ))

        except Exception as err:
            _LOGGER.warning("Failed to process chat history: %s", err)
            # Continue without history - don't fail the request

    # 6. Current context (dynamic - NOT cached) + user message
    # Combined into single user message to keep dynamic content at the end
    now = dt_util.now()
    time_context = f"Current time: {now.strftime('%H:%M')}, Date: {now.strftime('%A, %B %d, %Y')}"

    # Build context prefix for user message
    context_parts = [f"[Context: {time_context}]"]

    # In smart_discovery mode, add reminder in user context
    discovery_mode = entity._get_config(CONF_ENTITY_DISCOVERY_MODE, DEFAULT_ENTITY_DISCOVERY_MODE)
    if discovery_mode == "smart_discovery":
        context_parts.append("[Entity Discovery Mode: Use get_entities tool to find entities before controlling them]")

    if calendar_context:
        _LOGGER.debug("Injecting calendar context (len=%d): %s", len(calendar_context), calendar_context.replace('\n', ' ')[:80])
        context_parts.append(calendar_context)

    # Add current assist satellite info if available
    # This allows the LLM to know which device initiated the request
    if satellite_id:
        context_parts.append(f"[Current Assist Satellite: {satellite_id}]")

    # Add recent entities for pronoun resolution (e.g., "it", "that", "the same one")
    if recent_entities_context:
        context_parts.append(recent_entities_context)

    # Add current user identity for personalization
    if entity._memory_enabled and user_id != "default":
        display_name = user_id.capitalize()
        if entity._memory_manager:
            stored_name = entity._memory_manager.get_user_display_name(user_id)
            if stored_name:
                display_name = stored_name
        context_parts.append(f"[Current User: {display_name}]")

    # Combine context with user message
    context_prefix = " ".join(context_parts)
    user_message_with_context = f"{context_prefix}\n\nUser: {user_text}"

    messages.append(ChatMessage(role=MessageRole.USER, content=user_message_with_context))

    return messages, cached_prefix_length
