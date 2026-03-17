import json
import logging
import uuid

from odigos.core.json_utils import parse_json_response
from odigos.core.prompt_loader import load_prompt
from odigos.db import Database
from odigos.memory.vectors import VectorMemory
from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

STRUCTURED_COMPACTION_PROMPT = """\
Summarize this conversation segment. Return ONLY valid JSON with this structure:

{{"summary": "A structured summary of the conversation with Goal, Progress, Decisions, Next Steps, and Key Facts sections as relevant.", "tags": ["topic-tag-1", "topic-tag-2"], "key_facts": ["Factual statement 1", "Factual statement 2"], "action_items": ["Pending action 1"]}}\
"""


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
                {"role": "system", "content": load_prompt("summarizer.md", STRUCTURED_COMPACTION_PROMPT)},
                {"role": "user", "content": conversation_text},
            ]
        )

        raw_content = summary_response.content

        # Parse structured JSON response; fall back to plain text summary
        parsed = parse_json_response(raw_content)
        if parsed and isinstance(parsed, dict) and "summary" in parsed:
            summary_text = parsed["summary"]
            tags = parsed.get("tags", [])
            key_facts = parsed.get("key_facts", [])
            action_items = parsed.get("action_items", [])
        else:
            summary_text = raw_content
            tags = []
            key_facts = []
            action_items = []

        # Append action items to summary text if present
        if action_items and isinstance(action_items, list):
            items_text = "\n".join(f"- {item}" for item in action_items if isinstance(item, str))
            if items_text:
                summary_text += f"\n\n## Action Items\n{items_text}"

        tags_str = json.dumps(tags) if tags and isinstance(tags, list) else ""

        # Store the summary
        summary_id = str(uuid.uuid4())
        try:
            await self.db.execute(
                "INSERT INTO conversation_summaries "
                "(id, conversation_id, start_message_idx, end_message_idx, summary, tags) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (summary_id, conversation_id, already_summarized, cutoff, summary_text, tags_str),
            )
        except Exception:
            # tags column may not exist yet; fall back without it
            await self.db.execute(
                "INSERT INTO conversation_summaries "
                "(id, conversation_id, start_message_idx, end_message_idx, summary) "
                "VALUES (?, ?, ?, ?, ?)",
                (summary_id, conversation_id, already_summarized, cutoff, summary_text),
            )

        # Store key facts in user_facts table
        if key_facts and isinstance(key_facts, list):
            for fact_text in key_facts:
                if not isinstance(fact_text, str) or not fact_text.strip():
                    continue
                existing = await self.db.fetch_one(
                    "SELECT id FROM user_facts WHERE fact = ?", (fact_text.strip(),)
                )
                if existing:
                    continue
                try:
                    fact_id = str(uuid.uuid4())
                    await self.db.execute(
                        "INSERT INTO user_facts (id, fact, category, source, confidence, created_at, updated_at) "
                        "VALUES (?, ?, 'general', 'summarizer', 0.7, datetime('now'), datetime('now'))",
                        (fact_id, fact_text.strip()),
                    )
                except Exception:
                    logger.debug("Failed to store summarizer fact: %s", fact_text[:80])

        # Embed the summary for vector search
        await self.vector_memory.store(
            text=summary_text,
            source_type="conversation_summary",
            source_id=summary_id,
            memory_type="summary",
            when_to_use=f"when recalling context from conversation {conversation_id}",
        )

        logger.info(
            "Summarized messages %d-%d for conversation %s (tags: %s)",
            already_summarized,
            cutoff,
            conversation_id,
            tags_str[:100],
        )
