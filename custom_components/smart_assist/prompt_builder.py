"""Prompt building and message construction for Smart Assist conversation."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any, TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .const import (
    CALENDAR_SHARED_MARKER,
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
    from homeassistant.core import HomeAssistant
    from homeassistant.components.conversation import ChatLog
    from .conversation import SmartAssistConversationEntity

_LOGGER = logging.getLogger(__name__)


def parse_calendar_mappings(user_system_prompt: str | None) -> dict[str, str] | None:
    """Parse calendar-to-user mappings from the user system prompt.

    Looks for a block starting with 'Calendar Mappings:' followed by
    lines like '- calendar.anna -> Anna' or '- calendar.family -> shared'.

    Args:
        user_system_prompt: The user system prompt text.

    Returns:
        Dict mapping calendar entity_id/name -> user_name (lowercase) or 'shared'.
        Returns None if no Calendar Mappings block is found (= feature not configured).
    """
    if not user_system_prompt:
        return None

    mappings: dict[str, str] = {}
    in_block = False

    for line in user_system_prompt.splitlines():
        stripped = line.strip()

        # Detect start of Calendar Mappings block
        if stripped.lower().startswith("calendar mappings:"):
            in_block = True
            continue

        # End block on empty line or new section header
        if in_block:
            if not stripped or (not stripped.startswith("-") and ":" in stripped and "->" not in stripped):
                break

            if stripped.startswith("-") and "->" in stripped:
                parts = stripped.lstrip("- ").split("->", 1)
                if len(parts) == 2:
                    cal_key = parts[0].strip().lower()
                    user_name = parts[1].strip().lower()
                    mappings[cal_key] = user_name

    return mappings if mappings else None


def parse_satellite_player_mappings(user_system_prompt: str | None) -> dict[str, str] | None:
    """Parse satellite-to-media-player mappings from the user system prompt.

    Looks for a block starting with 'Satellite to Media Player Mappings:' followed by
    lines like '- assist_satellite.satellite_kitchen -> media_player.kitchen_speaker'.

    Args:
        user_system_prompt: The user system prompt text.

    Returns:
        Dict mapping satellite entity_id -> media_player entity_id.
        Returns None if no mappings block is found.
    """
    if not user_system_prompt:
        return None

    mappings: dict[str, str] = {}
    in_block = False

    for line in user_system_prompt.splitlines():
        stripped = line.strip()

        # Detect start of Satellite to Media Player Mappings block
        if stripped.lower().startswith("satellite to media player mappings:"):
            in_block = True
            continue

        if in_block:
            if not stripped or (not stripped.startswith("-") and ":" in stripped and "->" not in stripped):
                break

            if stripped.startswith("-") and "->" in stripped:
                parts = stripped.lstrip("- ").split("->", 1)
                if len(parts) == 2:
                    satellite_key = parts[0].strip().lower()
                    player_key = parts[1].strip()
                    mappings[satellite_key] = player_key

    return mappings if mappings else None


def filter_calendars_for_user(
    all_calendar_ids: list[str],
    hass: HomeAssistant,
    user_id: str,
    calendar_mappings: dict[str, str] | None,
) -> list[str]:
    """Filter calendar entity_ids based on user identity and mappings.

    Rules:
    - If calendar_mappings is None: return all calendars (feature not configured)
    - If user_id is 'default': return all calendars (user not identified)
    - Otherwise: return calendars mapped to user_id or 'shared',
      plus any calendars not explicitly listed in mappings (treated as shared)

    Args:
        all_calendar_ids: All available calendar entity_ids.
        hass: Home Assistant instance for fetching friendly_names.
        user_id: The resolved user identifier (lowercase).
        calendar_mappings: Parsed mappings from system prompt, or None.

    Returns:
        Filtered list of calendar entity_ids.
    """
    # No mappings configured -> show all (current behavior)
    if calendar_mappings is None:
        return all_calendar_ids

    # User not identified -> show all (fallback)
    if user_id == "default":
        return all_calendar_ids

    filtered: list[str] = []

    for cal_id in all_calendar_ids:
        cal_id_lower = cal_id.lower()

        # Get friendly_name for matching
        friendly_name = ""
        if hass:
            state = hass.states.get(cal_id)
            if state and state.attributes.get("friendly_name"):
                friendly_name = state.attributes["friendly_name"].lower()

        # Check if this calendar is in the mappings
        mapped_user = None
        if cal_id_lower in calendar_mappings:
            mapped_user = calendar_mappings[cal_id_lower]
        elif friendly_name and friendly_name in calendar_mappings:
            mapped_user = calendar_mappings[friendly_name]

        if mapped_user is not None:
            # Calendar is explicitly mapped
            if mapped_user == CALENDAR_SHARED_MARKER or mapped_user == user_id.lower():
                filtered.append(cal_id)
        else:
            # Calendar not in mappings -> treat as shared (include)
            filtered.append(cal_id)

    return filtered


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

Language:
{language_instruction} This applies to ALL responses -- confirmations, errors, questions. Never mix languages.""")

    # Global intent routing and entity discovery policy (single source of truth)
    discovery_mode = entity._get_config(CONF_ENTITY_DISCOVERY_MODE, DEFAULT_ENTITY_DISCOVERY_MODE)
    if discovery_mode == "smart_discovery":
        parts.append("""
Global Tool Routing Policy:
1. First classify intent: state_query, entity_control, media, calendar, timer, memory, send, or web_info.
2. For entity_control in smart_discovery mode: call get_entities first, then call control/get_entity_state with returned IDs.

Rules:
- Never fabricate entity IDs, targets, or capabilities.
- Recent Entities are for pronouns only ("it", "that"), not new requests.
- Area requests: use get_entities(area=...), then batch control with entity_ids.
- Only try a related domain (light -> switch) when first domain returns zero matches.""")

        # Inject available area names so LLM uses correct names
        from homeassistant.helpers import area_registry as ar
        area_reg = ar.async_get(entity.hass)
        area_names = sorted(area.name for area in area_reg.async_list_areas())
        if area_names:
            parts.append(f"""
Available Areas:
Use these EXACT area names for get_entities(area=...): {', '.join(area_names)}
Match the user's spoken room/area to the closest name from this list.""")
    else:
        parts.append("""
Global Tool Routing Policy:
1. First classify intent: state_query, entity_control, media, calendar, timer, memory, send, or web_info.
2. For entity_control in full_index mode: check ENTITY INDEX first. If unresolved, call get_entities. Then call control/get_entity_state.

Rules:
- Never fabricate entity IDs, targets, or capabilities.
- Recent Entities are for pronouns only ("it", "that"), not new requests.
- Area requests: use get_entities(area=...), then batch control with entity_ids.
- Only try a related domain (light -> switch) when first domain returns zero matches.""")

    # Safety and confirmation policy
    parts.append("""
Safety and Confirmation:
- Never guess IDs/targets/actions when uncertain.
- Ask confirmation before risky actions (locks, alarms, security changes) if required by policy.""")

    # Conversation continuation contract
    if ask_followup:
        parts.append("""
Conversation Continuation:
- If your response contains a question, choices, or confirmation request, you MUST call await_response in the same turn.
- Optional follow-up questions are allowed only for ambiguity or multiple valid options.
- await_response format: await_response(message="[question in user's language]", reason="clarification|confirmation|choice|follow_up").""")
    else:
        parts.append("""
Conversation Continuation:
- Do NOT ask optional follow-up questions.
- If your response contains a question, choices, or confirmation request, you MUST call await_response in the same turn.
- Keep responses action-focused and concise.""")

    # Error recovery policy
    parts.append("""
Error Recovery:
- If a tool returns a recoverable error (not found, invalid target/player), try one corrective tool step.
- If still unresolved, ask one concise clarification using await_response.
- Never repeat the same failing tool call with identical arguments.""")

    # Pronoun resolution hint
    parts.append("""
Pronouns:
"it"/"that"/"the same one" -> check [Recent Entities] in context.""")

    # Calendar reminders instruction (if enabled) - compact version
    calendar_enabled = entity._get_config(CONF_CALENDAR_CONTEXT, DEFAULT_CALENDAR_CONTEXT)
    if calendar_enabled:
        parts.append("""
Calendar Reminders:
When context contains calendar reminders, answer the user's request first, then append the reminder at the end with a casual transition ("By the way...", "Also...").
Reminders are already filtered per user. The 'owner' field shows whose calendar it is.""")

    # Control instructions - compact
    # In smart_discovery mode, add reminder that get_entities comes first
    parts.append("""
Entity Control:
Use control tool for lights, switches, covers, fans, climate, locks. Domain auto-detected.
- Always call control() for on/off/toggle regardless of apparent state. Tool handles idempotency.
- Groups: control by entity_id. Area requests: batch with entity_ids from get_entities(area=...).""")

    # Music/Radio instructions - only if music_assistant tool is registered
    if (await entity._get_tool_registry()).has_tool("music_assistant"):
        parts.append("""
Music and Radio:
Use music_assistant tool to play/search media (not control tool).
- Player: Use the [Current Media Player] from context if it is a Music Assistant player. If none or unsure, omit the player param (auto-resolved).
- get_players: Use action='get_players' to list available Music Assistant players when the user asks what speakers/players are available, or when a play attempt fails due to invalid player.
- Search first: If unsure whether the exact track/album/artist exists, use action='search' first, then play from results.
- If search returns no results, tell the user the media was not found. Do NOT try to play it anyway.
- radio_mode: For vague requests ("play some jazz", "relaxing music"), use play with radio_mode=true.
- Radio stations: Use media_type='radio' for internet radio (e.g., "SWR3", "BBC Radio").
Transport controls (stop/pause/volume) use music_assistant tool with action='pause'/'resume'/'stop', or control tool on the media_player entity from [Current Media Player].""")

    # Send/notification instructions - only if send tool is registered
    if (await entity._get_tool_registry()).has_tool("send"):
        parts.append("""
Sending Content:
Use 'send' tool for links/text/messages to devices. Offer when you have useful content.
- After sending, confirm briefly ("Sent to [device].") -- do NOT repeat content in voice response.""")

    # Critical actions confirmation
    if confirm_critical:
        parts.append("""
Critical Actions:
Ask for confirmation before: locking doors, arming alarms, disabling security.""")

    # Memory instructions (if enabled)
    if entity._memory_enabled:
        parts.append("""
User Memory:
USER MEMORY in context contains known memories. Use to personalize responses.
Save new preferences via memory tool (max 100 chars). "I am [Name]" -> memory(action='switch_user', content='[name]').""")

    # Agent Memory auto-learning instructions (if enabled)
    agent_memory_enabled = entity._memory_enabled and entity._get_config(
        CONF_ENABLE_AGENT_MEMORY, DEFAULT_ENABLE_AGENT_MEMORY
    )
    if agent_memory_enabled:
        parts.append("""
Agent Memory:
AGENT MEMORY contains your observations. Save only surprising discoveries via memory(action='save', scope='agent'). Max 100 chars.""")

    # Exposed only notice
    if exposed_only:
        parts.append("""
Notice:
Only exposed entities are available.""")

    # Cancel/abort handling instruction (if enabled globally)
    cancel_enabled = entity._get_global_config(
        CONF_ENABLE_CANCEL_HANDLER, DEFAULT_ENABLE_CANCEL_HANDLER
    )
    # Cancel/abort handled by nevermind tool -- no prompt section needed

    # Response format guidelines (kept near end to prioritize policy-first routing)
    parts.append("""
Response Format:
- After executing a tool, confirm in 5-15 words max. No elaboration.
- Vary confirmations naturally (e.g. "Done!", "Light's on.", "All set.")
- For info questions, 2-3 sentences max.
- Always use tools to check states, never guess.
- Plain text only, no formatting. Responses are spoken via TTS.""")

    # Error handling fallback summary
    parts.append("""
Errors:
If action fails or entity not found, explain briefly and suggest alternatives.""")

    # Cache the built prompt for subsequent calls
    entity._cached_system_prompt = "\n".join(parts)
    _LOGGER.debug("System prompt cached (length: %d chars)", len(entity._cached_system_prompt))

    return entity._cached_system_prompt


async def get_calendar_context(entity: SmartAssistConversationEntity, dry_run: bool = False, user_id: str = "default") -> str:
    """Get upcoming calendar events for context injection.

    Returns reminders for events in appropriate reminder windows.
    Only fetches if calendar_context is enabled in config.

    Args:
        dry_run: If True, don't mark reminders as completed (for cache warming).
        user_id: Resolved user identifier for calendar filtering.

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

        # Filter calendars based on user identity
        user_prompt = entity._get_config(CONF_USER_SYSTEM_PROMPT, DEFAULT_USER_SYSTEM_PROMPT)
        calendar_mappings = parse_calendar_mappings(user_prompt)
        if calendar_mappings is not None:
            calendars = filter_calendars_for_user(
                calendars, entity.hass, user_id, calendar_mappings
            )
            _LOGGER.debug(
                "Calendar filtering: user=%s, mappings=%d, filtered=%d calendars",
                user_id, len(calendar_mappings), len(calendars),
            )

        if not calendars:
            return ""

        semaphore = asyncio.Semaphore(4)

        async def _fetch_calendar_events(cal_id: str) -> list[dict[str, str]]:
            try:
                async with semaphore:
                    async with asyncio.timeout(8):
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

                if not result or cal_id not in result:
                    return []

                state = entity.hass.states.get(cal_id)
                if state and state.attributes.get("friendly_name"):
                    owner = state.attributes["friendly_name"]
                else:
                    name = cal_id.split(".", 1)[-1]
                    owner = name.replace("_", " ").title()

                events: list[dict[str, str]] = []
                for event in result[cal_id].get("events", []):
                    events.append({
                        "summary": event.get("summary", "Termin"),
                        "start": event.get("start"),
                        "owner": owner,
                    })
                return events
            except TimeoutError:
                _LOGGER.debug("Timeout while fetching calendar events from %s", cal_id)
            except Exception as err:
                _LOGGER.debug("Failed to fetch calendar events from %s: %s", cal_id, err)
            return []

        results = await asyncio.gather(
            *(_fetch_calendar_events(cal_id) for cal_id in calendars),
            return_exceptions=False,
        )

        all_events: list[dict] = []
        for events in results:
            all_events.extend(events)

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
        return f"\nCalendar Reminders (action required):\n{reminder_text}"

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
    calendar_context = await get_calendar_context(entity, dry_run=dry_run, user_id=user_id)
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
                content=f"[ENTITY INDEX]\nUse this index first for entity_control in full_index mode. If unresolved, use get_entities.\n{entity._cached_entity_index}",
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

        # Resolve satellite -> media_player mapping
        user_prompt = entity._get_config(CONF_USER_SYSTEM_PROMPT, DEFAULT_USER_SYSTEM_PROMPT)
        sat_mappings = parse_satellite_player_mappings(user_prompt)
        if sat_mappings:
            sat_key = satellite_id.lower()
            mapped_player = sat_mappings.get(sat_key)
            if mapped_player:
                context_parts.append(f"[Current Media Player: {mapped_player}]")

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
