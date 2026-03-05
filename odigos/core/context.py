from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.db import Database
from odigos.personality.loader import load_personality
from odigos.personality.prompt_builder import build_system_prompt

if TYPE_CHECKING:
    from odigos.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Estimate token count from text. Rough: ~4 chars per token."""
    return len(text) // 4


class ContextAssembler:
    """Builds the messages list for an LLM call from conversation history."""

    def __init__(
        self,
        db: Database,
        agent_name: str,
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
        personality_path: str = "data/personality.yaml",
    ) -> None:
        self.db = db
        self.agent_name = agent_name
        self.history_limit = history_limit
        self.memory_manager = memory_manager
        self.personality_path = personality_path

    async def build(
        self, conversation_id: str, current_message: str, tool_context: str = "", max_tokens: int = 0
    ) -> list[dict]:
        """Assemble the full messages list: system + history + current."""
        messages: list[dict] = []

        # Load personality (hot reload -- re-read on every call)
        personality = load_personality(self.personality_path)

        # Get memory context if available
        memory_context = ""
        if self.memory_manager:
            memory_context = await self.memory_manager.recall(current_message)

        # Build system prompt via structured prompt builder
        system_prompt = build_system_prompt(
            personality=personality,
            memory_context=memory_context,
            tool_context=tool_context,
        )

        messages.append({"role": "system", "content": system_prompt})

        # Conversation history
        history = await self.db.fetch_all(
            "SELECT role, content FROM messages "
            "WHERE conversation_id = ? "
            "ORDER BY timestamp ASC "
            "LIMIT ?",
            (conversation_id, self.history_limit),
        )
        for row in history:
            messages.append({"role": row["role"], "content": row["content"]})

        # Current message
        messages.append({"role": "user", "content": current_message})

        if max_tokens > 0:
            messages = self._trim_to_budget(messages, max_tokens)

        return messages

    def _trim_to_budget(
        self, messages: list[dict], max_tokens: int
    ) -> list[dict]:
        """Trim history messages (oldest first) to fit within token budget."""
        total = sum(estimate_tokens(m["content"]) for m in messages)

        if total <= max_tokens:
            return messages

        # messages[0] = system, messages[-1] = current, middle = history
        while total > max_tokens and len(messages) > 2:
            removed = messages.pop(1)
            total -= estimate_tokens(removed["content"])
            logger.debug("Trimmed history message to fit context budget")

        if total > max_tokens:
            logger.warning(
                "Context still over budget after trimming all history "
                "(%d > %d tokens)", total, max_tokens,
            )

        return messages
