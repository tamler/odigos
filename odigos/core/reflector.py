import uuid

from odigos.db import Database
from odigos.providers.base import LLMResponse


class Reflector:
    """Evaluates results and stores learnings.

    Phase 0: Just stores the assistant message.
    Phase 1+: Will extract learnings, corrections, entities, etc.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    async def reflect(self, conversation_id: str, response: LLMResponse) -> None:
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, model_used, "
            "tokens_in, tokens_out, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                conversation_id,
                "assistant",
                response.content,
                response.model,
                response.tokens_in,
                response.tokens_out,
                response.cost_usd,
            ),
        )
