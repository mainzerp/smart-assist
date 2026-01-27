# Calendar Integration - Feature Specification

## Overview

Enable Smart Assist to access Home Assistant calendar entities for context-aware conversations and proactive reminders.

**Target Version**: 1.6.0  
**Priority**: Medium  
**Status**: Implemented

## Use Cases

### 1. Query-Based Access
User asks about upcoming events:
- "Was steht heute an?"
- "Habe ich morgen Termine?"
- "Was ist diese Woche geplant?"

### 2. Contextual Reminders
Agent proactively mentions relevant events during conversation:
- "Laura, denk daran, du hast in einer Stunde einen Arzttermin."
- "Patric hat morgen um 10 Uhr das Meeting mit dem Team."

### 2.1 Multi-Person Household

Der Kalendername wird als Besitzer interpretiert:
- calendar.laura -> "Laura"
- calendar.patric -> "Patric"
- calendar.familie -> "Familie" (gemeinsamer Kalender)

### 3. Time-Aware Responses

Agent considers calendar when answering:
- User: "Weck mich morgen frueh"
- Agent: "Ich sehe du hast morgen um 8:30 einen Termin. Soll ich den Wecker auf 7:00 stellen?"

---

## Technical Design

### Phase 1: Read-Only Calendar Access

#### 1.1 Add Calendar to Supported Domains

```python
# const.py
SUPPORTED_DOMAINS: Final = {
    # ... existing domains ...
    "calendar",  # NEW
}
```

#### 1.2 New Calendar Tool

```python
# tools/calendar_tools.py

class CalendarTool(BaseTool):
    """Tool to query calendar events."""
    
    name = "get_calendar_events"
    description = "Get upcoming calendar events for a specific time range"
    
    parameters = {
        "type": "object",
        "properties": {
            "calendar_id": {
                "type": "string",
                "description": "Calendar entity ID (e.g., calendar.family). If empty, queries all calendars."
            },
            "time_range": {
                "type": "string",
                "enum": ["today", "tomorrow", "this_week", "next_7_days"],
                "description": "Time range for events"
            },
            "max_events": {
                "type": "integer",
                "description": "Maximum number of events to return",
                "default": 10
            }
        },
        "required": ["time_range"]
    }
```

#### 1.3 Implementation

```python
async def execute(self, **kwargs) -> ToolResult:
    calendar_id = kwargs.get("calendar_id")
    time_range = kwargs.get("time_range", "today")
    max_events = kwargs.get("max_events", 10)
    
    # Calculate time window
    now = dt_util.now()
    if time_range == "today":
        start = now.replace(hour=0, minute=0, second=0)
        end = now.replace(hour=23, minute=59, second=59)
    elif time_range == "tomorrow":
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0)
        end = (now + timedelta(days=1)).replace(hour=23, minute=59, second=59)
    elif time_range == "this_week":
        start = now
        end = now + timedelta(days=7)
    elif time_range == "next_7_days":
        start = now
        end = now + timedelta(days=7)
    
    # Get calendar entities
    calendars = []
    if calendar_id:
        calendars = [calendar_id]
    else:
        # Get all exposed calendar entities
        calendars = [
            e.entity_id for e in self.hass.states.async_all()
            if e.domain == "calendar" and self._is_exposed(e.entity_id)
        ]
    
    # Fetch events using HA's calendar service
    events = []
    for cal_id in calendars:
        try:
            result = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "entity_id": cal_id,
                    "start_date_time": start.isoformat(),
                    "end_date_time": end.isoformat(),
                },
                blocking=True,
                return_response=True,
            )
            if result and cal_id in result:
                # Extract owner name from calendar entity (e.g., calendar.laura -> "Laura")
                calendar_name = self._get_calendar_owner(cal_id)
                
                for event in result[cal_id].get("events", []):
                    events.append({
                        "calendar": cal_id,
                        "owner": calendar_name,  # NEW: Who owns this calendar
                        "summary": event.get("summary", "Untitled"),
                        "start": event.get("start"),
                        "end": event.get("end"),
                        "location": event.get("location"),
                        "description": event.get("description"),
                    })
        except Exception as e:
            _LOGGER.warning("Failed to get events from %s: %s", cal_id, e)
    
    # Sort by start time and limit
    events.sort(key=lambda x: x["start"])
    events = events[:max_events]
    
    if not events:
        return ToolResult(success=True, data={"message": "No events found", "events": []})
    
    return ToolResult(success=True, data={"events": events, "count": len(events)})

def _get_calendar_owner(self, entity_id: str) -> str:
    """Extract owner name from calendar entity.
    
    Examples:
        calendar.laura -> "Laura"
        calendar.patric_arbeit -> "Patric Arbeit"
        calendar.familie -> "Familie"
    """
    # Try friendly_name first (if user set custom name)
    state = self.hass.states.get(entity_id)
    if state and state.attributes.get("friendly_name"):
        return state.attributes["friendly_name"]
    
    # Fallback: Extract from entity_id
    # calendar.laura -> "laura" -> "Laura"
    name = entity_id.split(".", 1)[-1]  # Remove domain
    name = name.replace("_", " ")  # calendar.patric_arbeit -> "patric arbeit"
    return name.title()  # "Laura", "Patric Arbeit"
```

### Phase 2: Contextual Calendar Injection (Optional)

Automatically include upcoming events in system prompt for proactive mentions.

**Dieses Feature ist in der UI ein-/ausschaltbar** (standardmaessig deaktiviert wegen Token-Kosten).

#### 2.1 UI-Konfiguration

```yaml
# config_flow.py - Options Flow
CONF_CALENDAR_CONTEXT: Toggle (Ein/Aus)
  Label: "Proaktive Kalender-Erinnerungen"
  Description: "Automatisch auf anstehende Termine hinweisen (erhoehter Token-Verbrauch)"
  Default: False (Aus)
```

**UI-Darstellung:**

```
[x] Proaktive Kalender-Erinnerungen
    Automatisch auf anstehende Termine hinweisen.
    Hinweis: Erhoehter Token-Verbrauch bei aktivierter Option.
```

#### 2.2 Calendar Context in System Prompt

```python
# conversation.py - _build_system_prompt()

async def _get_calendar_context(self) -> str:
    """Get upcoming events for context injection."""
    # Only fetch if calendar integration enabled
    if not self._get_config(CONF_CALENDAR_CONTEXT, False):
        return ""
    
    now = dt_util.now()
    # Get events in next 24 hours
    events = await self._fetch_upcoming_events(hours=24)
    
    if not events:
        return ""
    
    lines = ["## Upcoming Calendar Events (next 24h)"]
    for event in events[:5]:  # Limit to 5 for token efficiency
        start = parse_datetime(event["start"])
        if start:
            time_str = start.strftime("%H:%M")
            delta = start - now
            if delta.total_seconds() < 3600:
                relative = f"in {int(delta.total_seconds() / 60)} Minuten"
            elif delta.total_seconds() < 86400:
                hours = int(delta.total_seconds() / 3600)
                relative = f"in {hours} Stunden"
            else:
                relative = f"morgen um {time_str}"
            
            owner = event.get('owner', 'Kalender')
            lines.append(f"- [{owner}] {event['summary']} ({relative})")
    
    return "\n".join(lines)
```

#### 2.2 Configuration Option

```python
# const.py
CONF_CALENDAR_CONTEXT: Final = "calendar_context"
DEFAULT_CALENDAR_CONTEXT: Final = False  # Disabled by default (token cost)
```

---

## Entity Index Integration

Calendar entities will appear in the entity index:

```
calendar.family - Family Calendar (calendar) [Area: Home]
calendar.work - Work Calendar (calendar) [Area: Office]
```

The LLM can then use `get_calendar_events` tool to query specific calendars.

---

## Example Conversations

### Example 1: Direct Query

**User**: "Was habe ich heute noch vor?"

**Agent** (uses `get_calendar_events` with `time_range: "today"`):
"Heute stehen noch 2 Termine an:
- 14:00: Meeting mit Team
- 18:30: Arzttermin

Kann ich dir sonst noch helfen?"

### Example 2: Contextual Mention (Phase 2)

**User**: "Mach das Licht im Buero an"

**Agent** (sees upcoming event in context):
"Licht im Buero ist an. Uebrigens, in 45 Minuten hast du das Team-Meeting."

### Example 3: Time-Aware Planning

**User**: "Stelle einen Wecker fuer morgen frueh"

**Agent** (checks calendar first):
"Morgen hast du um 9:00 einen Termin. Soll ich den Wecker auf 7:30 stellen?"

---

## Implementation Plan

### Step 1: Basic Calendar Tool (v1.6.0)

| Task | Effort | Files |
| ---- | ------ | ----- |
| Add `calendar` to SUPPORTED_DOMAINS | 5 min | const.py |
| Create CalendarTool class | 1 hour | tools/calendar_tools.py |
| Register tool in ToolRegistry | 10 min | tools/__init__.py |
| Add tool to schemas | 10 min | tools/__init__.py |
| Test with real calendar | 30 min | - |

**Total**: ~2 hours

### Step 2: Calendar Context Injection (v1.7.0, optional)

| Task | Effort | Files |
| ---- | ------ | ----- |
| Add CONF_CALENDAR_CONTEXT | 10 min | const.py |
| Implement _get_calendar_context() | 1 hour | conversation.py |
| Add config option to UI | 30 min | config_flow.py, translations |
| Token optimization (caching) | 1 hour | conversation.py |

**Total**: ~3 hours

---

## Token Considerations

### Phase 1 (Tool-based)
- No additional tokens in prompt
- Only adds tokens when tool is called
- Efficient: LLM decides when to query

### Phase 2 (Context injection)

- Adds ~50-100 tokens per request (if events exist)
- Can be cached for prompt caching efficiency
- Should be optional due to cost impact

---

## Reminder-Deduplizierung

### Problem

Ohne Deduplizierung wuerde der Agent bei jeder Konversation auf denselben anstehenden Termin hinweisen:

- 14:00 User: "Licht an" -> "Licht ist an. In 1 Stunde hast du einen Termin."
- 14:15 User: "Wie warm ist es?" -> "22 Grad. In 45 Minuten hast du einen Termin."
- 14:30 User: "Musik an" -> "Musik laeuft. In 30 Minuten hast du einen Termin."

Das ist nervig und verschwendet Tokens.

### Loesung: Gestaffelte Erinnerungen

Wie bei klassischen Kalender-Apps: Feste Erinnerungszeitpunkte statt staendiger Wiederholung.

#### Erinnerungs-Zeitfenster

Jede Stufe hat ein Zeitfenster. Wird das Fenster verpasst (keine Interaktion), wird die Erinnerung **nicht nachgeholt**.

| Stufe | Zielzeit | Fenster | Beschreibung |
| ----- | -------- | ------- | ------------ |
| **1 Tag vorher** | 24h | 20h - 28h | +-4h Toleranz |
| **4 Stunden vorher** | 4h | 3h - 5h | +-1h Toleranz |
| **1 Stunde vorher** | 1h | 30min - 90min | +-30min Toleranz |

#### Ablauf-Beispiel (mit Zeitfenstern)

Termin: "Arzttermin" am 28.01. um 15:00

| Zeitpunkt | Zeit bis Event | Fenster aktiv? | Aktion |
| --------- | -------------- | -------------- | ------ |
| 27.01. 10:00 | 29h | Nein (>28h) | (keine Erwaehnung) |
| 27.01. 12:00 | 27h | 24h-Fenster (20-28h) | "Morgen um 15:00 hast du einen Arzttermin" |
| 27.01. 18:00 | 21h | 24h-Fenster | (bereits erinnert) |
| 28.01. 09:00 | 6h | Nein (zwischen Fenstern) | (keine Erwaehnung) |
| 28.01. 10:30 | 4.5h | 4h-Fenster (3-5h) | "In etwa 4 Stunden hast du den Arzttermin" |
| 28.01. 12:00 | 3h | 4h-Fenster | (bereits erinnert) |
| 28.01. 13:00 | 2h | Nein (zwischen Fenstern) | (keine Erwaehnung) |
| 28.01. 14:00 | 1h | 1h-Fenster (30-90min) | "In einer Stunde ist dein Arzttermin" |
| 28.01. 14:45 | 15min | Nein (<30min) | (keine Erwaehnung) |

**Wichtig**: Wenn keine Interaktion im Fenster stattfindet, wird die Erinnerung NICHT nachgeholt.

### Implementierung

```python
# calendar_reminder.py

from datetime import datetime, timedelta
from enum import Enum
from typing import Final
import hashlib

class ReminderStage(Enum):
    """Reminder stages for an event."""
    DAY_BEFORE = "day_before"    # 24h before
    HOURS_BEFORE = "hours_before"  # 4h before  
    HOUR_BEFORE = "hour_before"   # 1h before
    PASSED = "passed"             # Event started

# Reminder thresholds with time windows (min, max)
# Reminder only triggers if time_until is within window
REMINDER_WINDOWS: Final = {
    ReminderStage.DAY_BEFORE: (timedelta(hours=20), timedelta(hours=28)),    # 24h +-4h
    ReminderStage.HOURS_BEFORE: (timedelta(hours=3), timedelta(hours=5)),    # 4h +-1h
    ReminderStage.HOUR_BEFORE: (timedelta(minutes=30), timedelta(minutes=90)),  # 1h +-30min
}

class CalendarReminderTracker:
    """Tracks calendar reminders with staged notification."""
    
    def __init__(self):
        # {event_hash: set of completed ReminderStages}
        self._completed_stages: dict[str, set[ReminderStage]] = {}
    
    def _event_hash(self, event: dict) -> str:
        """Create unique hash for event."""
        key = f"{event['summary']}_{event['start']}"
        return hashlib.md5(key.encode()).hexdigest()[:12]
    
    def _get_current_stage(self, event: dict, now: datetime) -> ReminderStage | None:
        """Determine which reminder stage applies based on time window."""
        event_start = self._parse_event_time(event["start"])
        if not event_start:
            return None
        
        time_until = event_start - now
        
        if time_until <= timedelta(0):
            return ReminderStage.PASSED
        
        # Check each window - order matters (smallest window first)
        for stage in [ReminderStage.HOUR_BEFORE, ReminderStage.HOURS_BEFORE, ReminderStage.DAY_BEFORE]:
            window_min, window_max = REMINDER_WINDOWS[stage]
            if window_min <= time_until <= window_max:
                return stage
        
        return None  # Not in any reminder window
    
    def should_remind(self, event: dict, now: datetime | None = None) -> tuple[bool, str]:
        """
        Check if event should trigger a reminder.
        
        Returns:
            (should_remind, reminder_text)
            - (True, "morgen um 15:00") if reminder should be shown
            - (False, "") if already reminded or not in reminder window
        """
        if now is None:
            now = datetime.now()
        
        event_hash = self._event_hash(event)
        current_stage = self._get_current_stage(event, now)
        
        # Not in any reminder window
        if current_stage is None or current_stage == ReminderStage.PASSED:
            return False, ""
        
        # Check if this stage was already completed
        completed = self._completed_stages.get(event_hash, set())
        if current_stage in completed:
            return False, ""
        
        # Generate reminder text based on stage
        event_start = self._parse_event_time(event["start"])
        if current_stage == ReminderStage.DAY_BEFORE:
            reminder_text = f"morgen um {event_start.strftime('%H:%M')}"
        elif current_stage == ReminderStage.HOURS_BEFORE:
            hours = int((event_start - now).total_seconds() / 3600)
            reminder_text = f"in {hours} Stunden"
        elif current_stage == ReminderStage.HOUR_BEFORE:
            minutes = int((event_start - now).total_seconds() / 60)
            if minutes <= 60:
                reminder_text = f"in {minutes} Minuten"
            else:
                reminder_text = "in einer Stunde"
        else:
            reminder_text = ""
        
        return True, reminder_text
    
    def mark_reminded(self, event: dict, now: datetime | None = None) -> None:
        """Mark current reminder stage as completed."""
        if now is None:
            now = datetime.now()
        
        event_hash = self._event_hash(event)
        current_stage = self._get_current_stage(event, now)
        
        if current_stage and current_stage != ReminderStage.PASSED:
            if event_hash not in self._completed_stages:
                self._completed_stages[event_hash] = set()
            self._completed_stages[event_hash].add(current_stage)
    
    def cleanup_past_events(self, events: list[dict], now: datetime | None = None) -> None:
        """Remove tracking data for past events."""
        if now is None:
            now = datetime.now()
        
        current_hashes = {self._event_hash(e) for e in events}
        self._completed_stages = {
            h: stages for h, stages in self._completed_stages.items()
            if h in current_hashes
        }
    
    def _parse_event_time(self, time_str: str) -> datetime | None:
        """Parse event time string to datetime."""
        try:
            # Handle ISO format
            return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
```

### Integration in Kontext-Injektion

```python
async def _get_calendar_context(self) -> str:
    """Get upcoming events that need reminders."""
    events = await self._fetch_upcoming_events(hours=48)  # Look ahead 48h
    now = datetime.now()
    
    reminders = []
    for event in events:
        should_remind, reminder_text = self._reminder_tracker.should_remind(event, now)
        if should_remind:
            reminders.append({
                "event": event,
                "text": reminder_text,
            })
            # Mark as reminded (will be stored)
            self._reminder_tracker.mark_reminded(event, now)
    
    if not reminders:
        return ""
    
    lines = ["## Anstehende Erinnerungen"]
    for r in reminders[:3]:  # Max 3 reminders
        lines.append(f"- {r['event']['summary']} ({r['text']})")
    
    return "\n".join(lines)
```

### Konfigurierbare Zeitpunkte (optional)

```python
# const.py
CONF_REMINDER_DAY_BEFORE: Final = "reminder_day_before"      # Default: True
CONF_REMINDER_HOURS_BEFORE: Final = "reminder_hours_before"  # Default: 4
CONF_REMINDER_HOUR_BEFORE: Final = "reminder_hour_before"    # Default: True
```

UI-Option: "Erinnere mich X Stunden vorher" (Slider 1-12)

---

## Phase 3: Write Access (Kalendereintraege erstellen)

### 3.1 Use Cases

- "Setze morgen um 15 Uhr Zahnarzt auf Lauras Kalender"
- "Trag am Freitag um 18 Uhr Dinner mit Freunden ein"
- "Erstelle einen Termin: Team-Meeting am Montag 10-11 Uhr"

### 3.2 Home Assistant Service

```python
# calendar.create_event - verfuegbar seit HA 2022.x
await hass.services.async_call(
    "calendar",
    "create_event",
    {
        "entity_id": "calendar.laura",
        "summary": "Zahnarzt",
        "start_date_time": "2026-01-28T15:00:00",
        "end_date_time": "2026-01-28T16:00:00",  # Default: 1 Stunde
        "description": "Erstellt via Smart Assist",  # Optional
        "location": "",  # Optional
    },
    blocking=True,
)
```

### 3.3 Create Event Tool

```python
# tools/calendar_tools.py

class CreateCalendarEventTool(BaseTool):
    """Tool to create calendar events."""
    
    name = "create_calendar_event"
    description = "Create a new calendar event for a specific person/calendar"
    
    parameters = {
        "type": "object",
        "properties": {
            "calendar_id": {
                "type": "string",
                "description": "Calendar entity ID (e.g., calendar.laura, calendar.patric)"
            },
            "summary": {
                "type": "string",
                "description": "Event title/summary (e.g., 'Zahnarzt', 'Team-Meeting')"
            },
            "start_datetime": {
                "type": "string",
                "description": "Start date and time in ISO format (e.g., '2026-01-28T15:00:00')"
            },
            "end_datetime": {
                "type": "string",
                "description": "End date and time in ISO format. If not provided, defaults to 1 hour after start."
            },
            "description": {
                "type": "string",
                "description": "Optional event description/notes"
            },
            "location": {
                "type": "string",
                "description": "Optional event location"
            }
        },
        "required": ["calendar_id", "summary", "start_datetime"]
    }
    
    async def execute(self, **kwargs) -> ToolResult:
        calendar_id = kwargs["calendar_id"]
        summary = kwargs["summary"]
        start = kwargs["start_datetime"]
        
        # Default end time: 1 hour after start
        end = kwargs.get("end_datetime")
        if not end:
            start_dt = datetime.fromisoformat(start)
            end_dt = start_dt + timedelta(hours=1)
            end = end_dt.isoformat()
        
        service_data = {
            "entity_id": calendar_id,
            "summary": summary,
            "start_date_time": start,
            "end_date_time": end,
        }
        
        if kwargs.get("description"):
            service_data["description"] = kwargs["description"]
        if kwargs.get("location"):
            service_data["location"] = kwargs["location"]
        
        try:
            await self.hass.services.async_call(
                "calendar",
                "create_event",
                service_data,
                blocking=True,
            )
            
            # Extract owner name for confirmation
            owner = self._get_calendar_owner(calendar_id)
            
            return ToolResult(
                success=True,
                data={
                    "message": f"Termin '{summary}' wurde in {owner}s Kalender eingetragen.",
                    "calendar": calendar_id,
                    "summary": summary,
                    "start": start,
                    "end": end,
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Fehler beim Erstellen des Termins: {str(e)}"
            )
```

### 3.4 Sicherheitsueberlegungen

| Risiko | Massnahme |
|--------|-----------|
| Versehentliche Termine | LLM fragt bei unklaren Angaben nach Bestaetigung |
| Falscher Kalender | Bei mehreren Kalendern: LLM fragt "Auf welchen Kalender?" |
| Doppelte Eintraege | Optional: Pruefen ob aehnlicher Termin bereits existiert |
| Loeschen/Aendern | Phase 4 - vorerst nur Erstellen |

### 3.5 LLM-Instruktion fuer Write Access

```
## Calendar Write Access
Du kannst Kalendereintraege erstellen mit create_calendar_event.
- Frage nach fehlenden Informationen (Datum, Uhrzeit, Kalender)
- Bei mehreren Kalendern: Frage welcher Kalender gemeint ist
- Bestaetigung nach Erstellung: "Ich habe [Termin] am [Datum] um [Uhrzeit] in [Name]s Kalender eingetragen."
```

### 3.6 Beispiel-Dialoge

**Benutzer**: "Setz morgen um 15 Uhr Zahnarzt auf Lauras Kalender"
**AI**: *ruft create_calendar_event auf*
**AI**: "Ich habe 'Zahnarzt' am 28. Januar um 15:00 Uhr in Lauras Kalender eingetragen."

---

**Benutzer**: "Trag Freitag Abendessen ein"
**AI**: "Um welche Uhrzeit soll das Abendessen sein, und auf welchen Kalender - Laura oder Patric?"
**Benutzer**: "19 Uhr, beide"
**AI**: *ruft create_calendar_event 2x auf*
**AI**: "Ich habe 'Abendessen' am Freitag um 19:00 Uhr in beide Kalender eingetragen."

---

## Open Questions

1. **Privacy**: Should calendar details (description, attendees) be included or just summary/time?
2. **Multi-Calendar**: Show all calendars or let user configure which ones?
3. **Proactive Triggers**: Should agent remind about events without being asked? (requires event-based triggers)
4. ~~**Write Access**: Allow creating/modifying events? (Phase 3, higher risk)~~ -> Spezifiziert

---

## Dependencies

- Home Assistant Calendar integration (core)
- `calendar.get_events` service (available since HA 2023.x)
- `calendar.create_event` service (available since HA 2022.x)
- Exposed calendar entities (respects exposed_only setting)

---

## Changelog

| Date | Change |
| ---- | ------ |
| 2026-01-27 | Added UI toggle for Phase 2 (proactive reminders on/off) |
| 2026-01-27 | Changed reminder stages to time windows (no catch-up if missed) |
| 2026-01-27 | Added Phase 3: Write Access (create_calendar_event tool) |
| 2026-01-27 | Added calendar owner name extraction (multi-person household support) |
| 2026-01-27 | Updated to staged reminder strategy (24h, 4h, 1h before event) |
| 2026-01-27 | Added Reminder-Deduplizierung section |
| 2026-01-27 | Initial specification created |
