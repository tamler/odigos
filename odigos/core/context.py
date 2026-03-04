from odigos.db import Database

SYSTEM_PROMPT_TEMPLATE = """You are {agent_name}, a personal AI assistant.

You are helpful, direct, and concise. You remember past conversations and provide thoughtful responses.
When you don't know something, say so honestly rather than guessing."""


class ContextAssembler:
    """Builds the messages list for an LLM call from conversation history."""

    def __init__(self, db: Database, agent_name: str, history_limit: int = 20) -> None:
        self.db = db
        self.agent_name = agent_name
        self.history_limit = history_limit

    async def build(self, conversation_id: str, current_message: str) -> list[dict]:
        """Assemble the full messages list: system + history + current."""
        messages: list[dict] = []

        # System prompt
        messages.append({
            "role": "system",
            "content": SYSTEM_PROMPT_TEMPLATE.format(agent_name=self.agent_name),
        })

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
