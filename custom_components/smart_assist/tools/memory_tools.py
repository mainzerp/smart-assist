"""Memory management tool for Smart Assist.

Provides persistent memory CRUD operations and user identity switching
for the LLM to save and recall user preferences, named entities, and
instructions.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)


class MemoryTool(BaseTool):
    """Tool for managing persistent user memories.

    Allows the LLM to save, list, update, delete, and search user memories.
    Also supports switching the active user profile for the current session.
    """

    name = "memory"
    description = (
        "Save, recall, update, or delete user memories and preferences. "
        "Use this to remember user preferences, named entities (people, pets), "
        "and instructions. Also use 'switch_user' when a user identifies themselves."
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description=(
                "Action to perform: "
                "save (new memory), "
                "list (show memories), "
                "update (modify existing), "
                "delete (remove), "
                "search (find by keyword), "
                "switch_user (change active user profile for this session)"
            ),
            required=True,
            enum=["save", "list", "update", "delete", "search", "switch_user"],
        ),
        ToolParameter(
            name="content",
            type="string",
            description=(
                "Memory content to save, updated content, or user name for switch_user. "
                "Keep concise (max 100 chars)."
            ),
            required=False,
        ),
        ToolParameter(
            name="category",
            type="string",
            description="Memory category for organization",
            required=False,
            enum=["preference", "named_entity", "pattern", "instruction", "fact", "observation"],
        ),
        ToolParameter(
            name="memory_id",
            type="string",
            description="Memory ID for update/delete operations",
            required=False,
        ),
        ToolParameter(
            name="query",
            type="string",
            description="Search query text (for search action)",
            required=False,
        ),
        ToolParameter(
            name="tags",
            type="string",
            description="Comma-separated tags (e.g., 'light,evening,bedroom')",
            required=False,
        ),
        ToolParameter(
            name="scope",
            type="string",
            description="Memory scope: user (personal), global (household-wide), or agent (LLM's own observations and learnings)",
            required=False,
            enum=["user", "global", "agent"],
            default="user",
        ),
    ]

    def __init__(self, hass: HomeAssistant, memory_manager: Any) -> None:
        """Initialize the memory tool.

        Args:
            hass: Home Assistant instance
            memory_manager: MemoryManager instance for storage operations
        """
        super().__init__(hass)
        self._memory_manager = memory_manager
        # Set by conversation handler per-request
        self._current_user_id: str = "default"
        # Callback for switch_user action (set by conversation handler)
        self._switch_user_callback: Any = None

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the memory tool."""
        action = kwargs.get("action", "")

        if action == "save":
            return await self._action_save(kwargs)
        elif action == "list":
            return await self._action_list(kwargs)
        elif action == "update":
            return await self._action_update(kwargs)
        elif action == "delete":
            return await self._action_delete(kwargs)
        elif action == "search":
            return await self._action_search(kwargs)
        elif action == "switch_user":
            return await self._action_switch_user(kwargs)
        else:
            return ToolResult(
                success=False,
                message=f"Unknown action: {action}. Use: save, list, update, delete, search, switch_user",
            )

    async def _action_save(self, kwargs: dict) -> ToolResult:
        """Save a new memory."""
        content = kwargs.get("content", "").strip()
        if not content:
            return ToolResult(success=False, message="Content is required for save action")

        category = kwargs.get("category", "fact")
        tags_str = kwargs.get("tags", "")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
        scope = kwargs.get("scope", "user")

        memory_id, message = self._memory_manager.add_memory(
            user_id=self._current_user_id,
            category=category,
            content=content,
            tags=tags,
            source="auto",
            scope=scope,
        )

        # Trigger async save
        await self._memory_manager.async_save()

        if memory_id:
            return ToolResult(success=True, message=message, data={"memory_id": memory_id})
        else:
            return ToolResult(success=False, message=message)

    async def _action_list(self, kwargs: dict) -> ToolResult:
        """List memories for the current user, including agent memories."""
        category = kwargs.get("category")
        memories = self._memory_manager.get_memories(
            user_id=self._current_user_id,
            category=category,
            include_global=True,
        )

        # Also include agent memories
        from ..const import MEMORY_AGENT_USER_ID
        agent_memories = self._memory_manager.get_memories(
            user_id=MEMORY_AGENT_USER_ID,
            category=category,
            include_global=False,
        )

        all_memories = memories + agent_memories

        if not all_memories:
            return ToolResult(success=True, message="No memories stored yet.")

        # Format for LLM
        lines = []
        agent_ids = {m["id"] for m in agent_memories}
        for mem in all_memories:
            cat_label = mem.get("category", "").upper()
            tags = ", ".join(mem.get("tags", []))
            tag_str = f" [{tags}]" if tags else ""
            scope_tag = " [AGENT]" if mem["id"] in agent_ids else ""
            lines.append(f"- [{mem['id']}] ({cat_label}{tag_str}{scope_tag}) {mem['content']}")

        return ToolResult(
            success=True,
            message=f"Found {len(all_memories)} memories:\n" + "\n".join(lines),
            data={"count": len(all_memories)},
        )

    async def _action_update(self, kwargs: dict) -> ToolResult:
        """Update an existing memory."""
        memory_id = kwargs.get("memory_id", "").strip()
        content = kwargs.get("content", "").strip()

        if not memory_id:
            return ToolResult(success=False, message="memory_id is required for update action")
        if not content:
            return ToolResult(success=False, message="content is required for update action")

        message = self._memory_manager.update_memory(
            user_id=self._current_user_id,
            memory_id=memory_id,
            content=content,
        )

        await self._memory_manager.async_save()

        success = "Updated" in message
        return ToolResult(success=success, message=message)

    async def _action_delete(self, kwargs: dict) -> ToolResult:
        """Delete a memory."""
        memory_id = kwargs.get("memory_id", "").strip()

        if not memory_id:
            return ToolResult(success=False, message="memory_id is required for delete action")

        message = self._memory_manager.delete_memory(
            user_id=self._current_user_id,
            memory_id=memory_id,
        )

        await self._memory_manager.async_save()

        success = "Deleted" in message
        return ToolResult(success=success, message=message)

    async def _action_search(self, kwargs: dict) -> ToolResult:
        """Search memories by keyword."""
        query = kwargs.get("query", "").strip()

        if not query:
            return ToolResult(success=False, message="query is required for search action")

        results = self._memory_manager.search_memories(
            user_id=self._current_user_id,
            query=query,
        )

        if not results:
            return ToolResult(success=True, message=f"No memories found matching '{query}'")

        lines = []
        for mem in results:
            lines.append(f"- [{mem['id']}] ({mem['category']}) {mem['content']}")

        return ToolResult(
            success=True,
            message=f"Found {len(results)} memories matching '{query}':\n" + "\n".join(lines),
            data={"count": len(results)},
        )

    async def _action_switch_user(self, kwargs: dict) -> ToolResult:
        """Switch active user profile for the current session."""
        user_name = kwargs.get("content", "").strip().lower()

        if not user_name:
            return ToolResult(
                success=False,
                message="User name is required. Example: memory(action='switch_user', content='anna')",
            )

        # Update session identity via callback
        if self._switch_user_callback:
            self._switch_user_callback(user_name)

        # Ensure user profile exists
        self._memory_manager._ensure_user(user_name)
        self._current_user_id = user_name

        display_name = user_name.capitalize()
        return ToolResult(
            success=True,
            message=f"Switched to {display_name}'s profile. Memories and preferences are now personalized.",
            data={"user_id": user_name, "display_name": display_name},
        )
