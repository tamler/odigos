from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.planner import Planner
from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMProvider

if TYPE_CHECKING:
    from odigos.memory.manager import MemoryManager
    from odigos.tools.registry import ToolRegistry


class Agent:
    """Main agent: receives messages, runs plan->execute->reflect loop."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        agent_name: str = "Odigos",
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
        personality_path: str = "data/personality.yaml",
        planner_provider: LLMProvider | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.db = db
        self.planner = Planner(provider=planner_provider or provider)
        self.context_assembler = ContextAssembler(
            db,
            agent_name,
            history_limit,
            memory_manager=memory_manager,
            personality_path=personality_path,
        )
        self.executor = Executor(
            provider, self.context_assembler, tool_registry=tool_registry
        )
        self.reflector = Reflector(db, memory_manager=memory_manager)

    async def handle_message(self, message: UniversalMessage) -> str:
        """Process an incoming message and return a response string."""
        conversation_id = await self._get_or_create_conversation(message)

        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (message.id, conversation_id, "user", message.content),
        )

        # Plan -> Execute -> Reflect
        plan = await self.planner.plan(message.content)
        response = await self.executor.execute(
            conversation_id, message.content, plan=plan
        )
        await self.reflector.reflect(
            conversation_id, response, user_message=message.content
        )

        await self.db.execute(
            "UPDATE conversations SET last_message_at = datetime('now'), "
            "message_count = message_count + 2 WHERE id = ?",
            (conversation_id,),
        )

        return response.content

    async def _get_or_create_conversation(self, message: UniversalMessage) -> str:
        """Get existing conversation for this chat, or create a new one.

        Uses chat_id from metadata for Telegram (one conversation per chat).
        """
        chat_id = message.metadata.get("chat_id", message.sender)
        lookup_id = f"{message.channel}:{chat_id}"

        existing = await self.db.fetch_one(
            "SELECT id FROM conversations WHERE id = ?", (lookup_id,)
        )
        if existing:
            return existing["id"]

        await self.db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (lookup_id, message.channel),
        )
        return lookup_id
