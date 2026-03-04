from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.db import Database

if TYPE_CHECKING:
    from odigos.memory.manager import MemoryManager

SYSTEM_PROMPT_TEMPLATE = """You are {agent_name}, a personal AI assistant.

You are helpful, direct, and concise. You remember past conversations and provide thoughtful responses.
When you don't know something, say so honestly rather than guessing."""

ENTITY_EXTRACTION_INSTRUCTION = """
After your response, on a new line, include extracted entities in this exact format:
<!--entities
[{{"name": "...", "type": "person|project|preference|concept", "relationship": "...", "detail": "..."}}]
-->
Only include entities if the conversation mentions specific people, projects, preferences, or important concepts.
If none are relevant, omit the block entirely."""


class ContextAssembler:
    """Builds the messages list for an LLM call from conversation history."""

    def __init__(
        self,
        db: Database,
        agent_name: str,
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.db = db
        self.agent_name = agent_name
        self.history_limit = history_limit
        self.memory_manager = memory_manager

    async def build(self, conversation_id: str, current_message: str) -> list[dict]:
        """Assemble the full messages list: system + memories + history + current."""
        messages: list[dict] = []

        # Build system prompt
        system_parts = [SYSTEM_PROMPT_TEMPLATE.format(agent_name=self.agent_name)]

        # Inject relevant memories
        if self.memory_manager:
            memory_context = await self.memory_manager.recall(current_message)
            if memory_context:
                system_parts.append(memory_context)

        # Add entity extraction instruction
        system_parts.append(ENTITY_EXTRACTION_INSTRUCTION)

        messages.append({"role": "system", "content": "\n\n".join(system_parts)})

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

        return messages
