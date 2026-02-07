"""Persistent memory manager for Smart Assist.

Provides long-term memory storage for user preferences, named entities,
and instructions. Uses Home Assistant's Storage API for persistence
across restarts.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import (
    MEMORY_MAX_CONTENT_LENGTH,
    MEMORY_MAX_GLOBAL,
    MEMORY_MAX_AGENT,
    MEMORY_MAX_INJECTION,
    MEMORY_MAX_AGENT_INJECTION,
    MEMORY_MAX_PER_USER,
    MEMORY_STORAGE_KEY,
    MEMORY_STORAGE_VERSION,
    MEMORY_AGENT_USER_ID,
)

_LOGGER = logging.getLogger(__name__)


class MemoryCategory(str, Enum):
    """Categories for memory entries."""

    PREFERENCE = "preference"
    NAMED_ENTITY = "named_entity"
    PATTERN = "pattern"
    INSTRUCTION = "instruction"
    FACT = "fact"
    OBSERVATION = "observation"


def _empty_user_data(display_name: str | None = None) -> dict[str, Any]:
    """Create empty user profile data."""
    return {
        "display_name": display_name,
        "memories": [],
        "stats": {
            "total_conversations": 0,
            "total_tokens_used": 0,
            "first_interaction": None,
        },
    }


def _empty_store_data() -> dict[str, Any]:
    """Create empty store data structure."""
    return {
        "version": MEMORY_STORAGE_VERSION,
        "users": {
            "default": _empty_user_data(),
            MEMORY_AGENT_USER_ID: _empty_user_data("Smart Assist Agent"),
        },
        "global_memories": [],
    }


class MemoryManager:
    """Manages persistent memory storage for Smart Assist.

    Uses HA Storage API to persist memories across restarts.
    Provides CRUD operations and prompt injection formatting.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the memory manager."""
        self._hass = hass
        self._store: Store = Store(hass, MEMORY_STORAGE_VERSION, MEMORY_STORAGE_KEY)
        self._data: dict[str, Any] = _empty_store_data()
        self._dirty = False
        self._last_save: float = 0.0
        self._save_debounce_seconds = 30.0

    async def async_load(self) -> None:
        """Load memory from storage. Call once at startup."""
        stored = await self._store.async_load()
        if stored is not None:
            self._data = stored
            # Ensure structure integrity
            self._data.setdefault("version", MEMORY_STORAGE_VERSION)
            self._data.setdefault("users", {"default": _empty_user_data()})
            self._data.setdefault("global_memories", [])
            if "default" not in self._data["users"]:
                self._data["users"]["default"] = _empty_user_data()
            if MEMORY_AGENT_USER_ID not in self._data["users"]:
                self._data["users"][MEMORY_AGENT_USER_ID] = _empty_user_data("Smart Assist Agent")
            _LOGGER.info(
                "Loaded memory: %d users, %d global memories",
                len(self._data["users"]),
                len(self._data["global_memories"]),
            )
        else:
            self._data = _empty_store_data()
            _LOGGER.info("No existing memory found, starting fresh")

    async def async_save(self) -> None:
        """Save memory to storage (debounced)."""
        if not self._dirty:
            return

        now = time.monotonic()
        if now - self._last_save < self._save_debounce_seconds:
            return

        await self._force_save()

    async def _force_save(self) -> None:
        """Force save memory to storage immediately."""
        try:
            await self._store.async_save(self._data)
            self._dirty = False
            self._last_save = time.monotonic()
            _LOGGER.debug("Memory saved to storage")
        except Exception as err:
            _LOGGER.error("Failed to save memory: %s", err)

    async def async_shutdown(self) -> None:
        """Save any pending changes on shutdown."""
        if self._dirty:
            await self._force_save()

    def _ensure_user(self, user_id: str) -> dict[str, Any]:
        """Ensure user profile exists, creating if needed."""
        if user_id not in self._data["users"]:
            display_name = user_id.capitalize() if user_id != "default" else None
            self._data["users"][user_id] = _empty_user_data(display_name)
            self._dirty = True
            _LOGGER.debug("Created user profile: %s", user_id)
        return self._data["users"][user_id]

    def _generate_id(self) -> str:
        """Generate a unique memory ID."""
        ts = int(time.time())
        short = uuid.uuid4().hex[:8]
        return f"mem_{ts}_{short}"

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def add_memory(
        self,
        user_id: str,
        category: str,
        content: str,
        context: str = "",
        tags: list[str] | None = None,
        source: str = "auto",
        scope: str = "user",
    ) -> tuple[str, str]:
        """Add a new memory entry.

        Returns:
            Tuple of (memory_id, status_message).
        """
        # Validate category
        try:
            MemoryCategory(category)
        except ValueError:
            return ("", f"Invalid category: {category}")

        # Truncate content
        if len(content) > MEMORY_MAX_CONTENT_LENGTH:
            content = content[:MEMORY_MAX_CONTENT_LENGTH]

        # Determine target list
        if scope == "global":
            target_list = self._data["global_memories"]
            max_limit = MEMORY_MAX_GLOBAL
        elif scope == "agent":
            agent_data = self._ensure_user(MEMORY_AGENT_USER_ID)
            target_list = agent_data["memories"]
            max_limit = MEMORY_MAX_AGENT
        else:
            user_data = self._ensure_user(user_id)
            target_list = user_data["memories"]
            max_limit = MEMORY_MAX_PER_USER

        # Deduplication check
        content_lower = content.lower().strip()
        for existing in target_list:
            if existing["content"].lower().strip() == content_lower:
                return ("", f"Memory already exists (id: {existing['id']})")

        # Evict if over limit
        if len(target_list) >= max_limit:
            self._evict_memories(target_list, max_limit - 1)

        now = datetime.now().isoformat()
        memory_id = self._generate_id()
        entry = {
            "id": memory_id,
            "category": category,
            "content": content,
            "context": context,
            "created_at": now,
            "updated_at": now,
            "access_count": 0,
            "last_accessed": now,
            "tags": tags or [],
            "source": source,
        }
        target_list.append(entry)
        self._dirty = True

        scope_label = "global" if scope == "global" else f"user:{user_id}"
        _LOGGER.debug("Added memory %s (%s) [%s]", memory_id, category, scope_label)
        return (memory_id, f"Saved: {content}")

    def update_memory(
        self,
        user_id: str,
        memory_id: str,
        content: str,
    ) -> str:
        """Update an existing memory entry. Returns status message."""
        if len(content) > MEMORY_MAX_CONTENT_LENGTH:
            content = content[:MEMORY_MAX_CONTENT_LENGTH]

        memory = self._find_memory(user_id, memory_id)
        if not memory:
            return f"Memory not found: {memory_id}"

        memory["content"] = content
        memory["updated_at"] = datetime.now().isoformat()
        self._dirty = True
        return f"Updated memory {memory_id}"

    def delete_memory(self, user_id: str, memory_id: str) -> str:
        """Delete a memory entry by ID. Returns status message."""
        # Check user memories
        user_data = self._ensure_user(user_id)
        for i, mem in enumerate(user_data["memories"]):
            if mem["id"] == memory_id:
                user_data["memories"].pop(i)
                self._dirty = True
                return f"Deleted memory {memory_id}"

        # Check agent memories
        agent_data = self._ensure_user(MEMORY_AGENT_USER_ID)
        for i, mem in enumerate(agent_data["memories"]):
            if mem["id"] == memory_id:
                agent_data["memories"].pop(i)
                self._dirty = True
                return f"Deleted agent memory {memory_id}"

        # Check global memories
        for i, mem in enumerate(self._data["global_memories"]):
            if mem["id"] == memory_id:
                self._data["global_memories"].pop(i)
                self._dirty = True
                return f"Deleted global memory {memory_id}"

        return f"Memory not found: {memory_id}"

    def get_memories(
        self,
        user_id: str,
        category: str | None = None,
        include_global: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get memories for a user, optionally filtered by category."""
        user_data = self._ensure_user(user_id)
        memories = list(user_data["memories"])

        if include_global:
            memories.extend(self._data["global_memories"])

        if category:
            memories = [m for m in memories if m["category"] == category]

        # Sort by access_count desc, then last_accessed desc
        memories.sort(
            key=lambda m: (m.get("access_count", 0), m.get("last_accessed", "")),
            reverse=True,
        )

        return memories[:limit]

    def search_memories(
        self,
        user_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Simple keyword search across memory content and tags."""
        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        user_data = self._ensure_user(user_id)
        all_memories = list(user_data["memories"]) + list(
            self._data["global_memories"]
        )

        for mem in all_memories:
            content_match = query_lower in mem["content"].lower()
            tag_match = any(query_lower in t.lower() for t in mem.get("tags", []))
            if content_match or tag_match:
                results.append(mem)

        return results

    # =========================================================================
    # Prompt Injection
    # =========================================================================

    def get_injection_text(self, user_id: str) -> str:
        """Build the memory injection block for the system prompt.

        Returns formatted text ready for injection. Prioritizes instructions
        first, then by access_count. Stays within MEMORY_MAX_INJECTION limit.
        Returns empty string if no memories exist.
        """
        user_data = self._ensure_user(user_id)
        all_memories = list(user_data["memories"]) + list(
            self._data["global_memories"]
        )

        if not all_memories:
            return ""

        # Sort: instructions first, then by access_count desc, then recency
        def sort_key(m: dict) -> tuple:
            is_instruction = 1 if m.get("category") == "instruction" else 0
            return (is_instruction, m.get("access_count", 0), m.get("last_accessed", ""))

        all_memories.sort(key=sort_key, reverse=True)
        selected = all_memories[:MEMORY_MAX_INJECTION]

        # Bump access counts for injected memories
        now = datetime.now().isoformat()
        for mem in selected:
            mem["access_count"] = mem.get("access_count", 0) + 1
            mem["last_accessed"] = now
        self._dirty = True

        # Group by category for readability
        groups: dict[str, list[str]] = {}
        category_order = ["instruction", "preference", "named_entity", "pattern", "fact"]

        for mem in selected:
            cat = mem.get("category", "fact")
            groups.setdefault(cat, []).append(mem["content"])

        # Build formatted text
        category_labels = {
            "instruction": "Instructions",
            "preference": "Preferences",
            "named_entity": "Named Entities",
            "pattern": "Patterns",
            "fact": "Facts",
        }

        parts = ["[USER MEMORY]"]
        for cat in category_order:
            items = groups.get(cat)
            if items:
                label = category_labels.get(cat, cat.title())
                parts.append(f"{label}:")
                for item in items:
                    parts.append(f"- {item}")

        return "\n".join(parts)

    def get_agent_injection_text(self) -> str:
        """Build the agent memory injection block for the system prompt.

        Returns formatted text with agent-level observations, patterns,
        and entity mappings. Independent of user identity.
        Returns empty string if no agent memories exist.
        """
        agent_data = self._ensure_user(MEMORY_AGENT_USER_ID)
        memories = list(agent_data["memories"])

        if not memories:
            return ""

        # Sort: newest first (most recently created)
        memories.sort(
            key=lambda m: m.get("created_at", ""),
            reverse=True,
        )
        selected = memories[:MEMORY_MAX_AGENT_INJECTION]

        # Group by category
        groups: dict[str, list[str]] = {}
        category_order = ["pattern", "observation", "instruction", "preference", "fact"]

        for mem in selected:
            cat = mem.get("category", "observation")
            groups.setdefault(cat, []).append(mem["content"])

        category_labels = {
            "pattern": "Patterns",
            "observation": "Observations",
            "instruction": "Instructions",
            "preference": "Preferences",
            "fact": "Facts",
        }

        parts = ["[AGENT MEMORY]"]
        for cat in category_order:
            items = groups.get(cat)
            if items:
                label = category_labels.get(cat, cat.title())
                parts.append(f"{label}:")
                for item in items:
                    parts.append(f"- {item}")

        return "\n".join(parts)

    def get_user_display_name(self, user_id: str) -> str | None:
        """Get user display name for personalized greetings."""
        user_data = self._data["users"].get(user_id)
        if user_data:
            return user_data.get("display_name")
        return None

    def get_known_users(self) -> list[str]:
        """Get list of known user IDs."""
        return list(self._data["users"].keys())

    def rename_user(self, user_id: str, new_display_name: str) -> str:
        """Change a user's display name.

        Args:
            user_id: The user ID to rename.
            new_display_name: The new display name.

        Returns:
            Status message.
        """
        if user_id not in self._data["users"]:
            return f"User not found: {user_id}"

        old_name = self._data["users"][user_id].get("display_name", user_id)
        self._data["users"][user_id]["display_name"] = new_display_name
        self._dirty = True
        _LOGGER.info("Renamed user %s: '%s' -> '%s'", user_id, old_name, new_display_name)
        return f"Renamed '{old_name}' to '{new_display_name}'"

    def merge_users(self, source_user_id: str, target_user_id: str) -> str:
        """Merge all memories from source user into target user.

        Moves all memories from source to target, avoiding duplicates.
        Merges stats (totals). Deletes the source user profile.

        Args:
            source_user_id: User ID to merge from (will be deleted).
            target_user_id: User ID to merge into (will receive memories).

        Returns:
            Status message.
        """
        if source_user_id not in self._data["users"]:
            return f"Source user not found: {source_user_id}"
        if target_user_id not in self._data["users"]:
            return f"Target user not found: {target_user_id}"
        if source_user_id == target_user_id:
            return "Source and target are the same user"

        source = self._data["users"][source_user_id]
        target = self._data["users"][target_user_id]

        # Deduplicate by content
        existing_contents = {
            m["content"].lower().strip() for m in target["memories"]
        }

        moved = 0
        skipped = 0
        for mem in source["memories"]:
            if mem["content"].lower().strip() in existing_contents:
                skipped += 1
            else:
                target["memories"].append(mem)
                existing_contents.add(mem["content"].lower().strip())
                moved += 1

        # Merge stats
        target_stats = target["stats"]
        source_stats = source["stats"]
        target_stats["total_conversations"] = (
            target_stats.get("total_conversations", 0)
            + source_stats.get("total_conversations", 0)
        )
        target_stats["total_tokens_used"] = (
            target_stats.get("total_tokens_used", 0)
            + source_stats.get("total_tokens_used", 0)
        )
        # Keep earliest first_interaction
        if source_stats.get("first_interaction"):
            if not target_stats.get("first_interaction") or (
                source_stats["first_interaction"] < target_stats["first_interaction"]
            ):
                target_stats["first_interaction"] = source_stats["first_interaction"]

        # Delete source user
        del self._data["users"][source_user_id]
        self._dirty = True

        source_name = source.get("display_name", source_user_id)
        target_name = target.get("display_name", target_user_id)
        _LOGGER.info(
            "Merged user '%s' into '%s': %d moved, %d skipped (duplicates)",
            source_name, target_name, moved, skipped,
        )
        return f"Merged '{source_name}' into '{target_name}': {moved} memories moved, {skipped} duplicates skipped"

    # =========================================================================
    # Stats
    # =========================================================================

    def record_conversation(self, user_id: str, tokens_used: int = 0) -> None:
        """Record a conversation for stats."""
        user_data = self._ensure_user(user_id)
        stats = user_data["stats"]
        stats["total_conversations"] = stats.get("total_conversations", 0) + 1
        stats["total_tokens_used"] = stats.get("total_tokens_used", 0) + tokens_used
        if not stats.get("first_interaction"):
            stats["first_interaction"] = datetime.now().isoformat()
        self._dirty = True

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _find_memory(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        """Find a memory by ID in user, agent, or global memories."""
        user_data = self._ensure_user(user_id)
        for mem in user_data["memories"]:
            if mem["id"] == memory_id:
                return mem
        # Check agent memories
        agent_data = self._ensure_user(MEMORY_AGENT_USER_ID)
        for mem in agent_data["memories"]:
            if mem["id"] == memory_id:
                return mem
        for mem in self._data["global_memories"]:
            if mem["id"] == memory_id:
                return mem
        return None

    def _evict_memories(self, memory_list: list, target_size: int) -> None:
        """Remove least-accessed memories to reach target size."""
        if len(memory_list) <= target_size:
            return

        # Sort by access_count asc, last_accessed asc (least accessed first)
        memory_list.sort(
            key=lambda m: (m.get("access_count", 0), m.get("last_accessed", ""))
        )

        evict_count = len(memory_list) - target_size
        evicted = memory_list[:evict_count]
        del memory_list[:evict_count]

        for mem in evicted:
            _LOGGER.debug("Evicted memory: %s (%s)", mem["id"], mem["content"][:40])
