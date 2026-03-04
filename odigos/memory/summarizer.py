import logging
import uuid

from odigos.db import Database
from odigos.memory.vectors import VectorMemory
from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

SUMMARIZE_PROMPT = (
    "Summarize this conversation segment in 2-3 sentences. "
    "Focus on key facts, decisions, and entities mentioned."
)


class ConversationSummarizer:
    """Summarizes conversation segments that fall out of the context window."""

    def __init__(
        self,
        db: Database,
        vector_memory: VectorMemory,
        llm_provider: LLMProvider,
        context_window: int = 20,
    ) -> None:
        self.db = db
        self.vector_memory = vector_memory
        self.llm_provider = llm_provider
        self.context_window = context_window

    async def summarize_if_needed(self, conversation_id: str) -> None:
        """Check if there are messages beyond the context window that need summarizing."""
        # Get total message count
        row = await self.db.fetch_one(
            "SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        total = row["cnt"] if row else 0

        if total <= self.context_window:
            return

        # Find the highest end_message_idx already summarized
        last_summary = await self.db.fetch_one(
            "SELECT MAX(end_message_idx) as max_idx FROM conversation_summaries "
            "WHERE conversation_id = ?",
            (conversation_id,),
        )
        already_summarized = (
            last_summary["max_idx"] if last_summary and last_summary["max_idx"] else 0
        )

        # Messages to summarize: from already_summarized to (total - context_window)
        cutoff = total - self.context_window

        if cutoff <= already_summarized:
            return

        # Fetch the unsummarized messages that need to be summarized
        messages = await self.db.fetch_all(
            "SELECT role, content FROM messages WHERE conversation_id = ? "
            "ORDER BY timestamp ASC LIMIT ? OFFSET ?",
            (conversation_id, cutoff - already_summarized, already_summarized),
        )

        if not messages:
            return

        # Build the text to summarize
        text_parts = []
        for msg in messages:
            text_parts.append(f"{msg['role']}: {msg['content']}")
        conversation_text = "\n".join(text_parts)

        # Call LLM to summarize
        summary_response = await self.llm_provider.complete(
            messages=[
                {"role": "system", "content": SUMMARIZE_PROMPT},
                {"role": "user", "content": conversation_text},
            ]
        )

        summary_text = summary_response.content

        # Store the summary
        summary_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO conversation_summaries "
            "(id, conversation_id, start_message_idx, end_message_idx, summary) "
            "VALUES (?, ?, ?, ?, ?)",
            (summary_id, conversation_id, already_summarized, cutoff, summary_text),
        )

        # Embed the summary for vector search
        await self.vector_memory.store(
            text=summary_text,
            source_type="conversation_summary",
            source_id=summary_id,
        )

        logger.info(
            "Summarized messages %d-%d for conversation %s",
            already_summarized,
            cutoff,
            conversation_id,
        )
