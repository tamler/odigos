import uuid
from unittest.mock import AsyncMock

import pytest

from odigos.db import Database
from odigos.memory.summarizer import ConversationSummarizer, STRUCTURED_COMPACTION_PROMPT
from odigos.memory.vectors import VectorMemory
from odigos.providers.base import LLMResponse


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed.return_value = [0.1] * 768
    embedder.embed_query.return_value = [0.1] * 768
    return embedder


@pytest.fixture
def vector_memory(db, mock_embedder) -> VectorMemory:
    return VectorMemory(embedder=mock_embedder, db=db)


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.complete.return_value = LLMResponse(
        content="## Goal\nBuild a dashboard\n## Progress\n- Done: Auth\n## Decisions\n- Use Preact\n## Next Steps\n- Deploy\n## Key Facts\n- User prefers dark mode",
        model="test/model",
        tokens_in=100,
        tokens_out=20,
        cost_usd=0.0,
    )
    return provider


@pytest.fixture
def summarizer(db, vector_memory, mock_provider):
    return ConversationSummarizer(
        db=db,
        vector_memory=vector_memory,
        llm_provider=mock_provider,
        context_window=5,  # small window for testing
    )


async def _insert_messages(db: Database, conversation_id: str, count: int):
    """Helper: insert N alternating user/assistant messages."""
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conversation_id, "test"),
    )
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), conversation_id, role, f"Message {i}"),
        )


class TestConversationSummarizer:
    async def test_no_summarization_within_window(self, summarizer, db):
        """No summarization needed when messages fit in context window."""
        await _insert_messages(db, "conv-1", 4)  # under window of 5

        await summarizer.summarize_if_needed("conv-1")

        summaries = await db.fetch_all(
            "SELECT * FROM conversation_summaries WHERE conversation_id = 'conv-1'"
        )
        assert len(summaries) == 0

    async def test_summarizes_messages_beyond_window(self, summarizer, db, mock_provider):
        """Messages beyond the window get summarized."""
        await _insert_messages(db, "conv-1", 8)  # 3 beyond window of 5

        await summarizer.summarize_if_needed("conv-1")

        summaries = await db.fetch_all(
            "SELECT * FROM conversation_summaries WHERE conversation_id = 'conv-1'"
        )
        assert len(summaries) == 1
        assert "Goal" in summaries[0]["summary"]
        mock_provider.complete.assert_called_once()

    async def test_does_not_resummarize(self, summarizer, db, mock_provider):
        """Already-summarized messages are not re-summarized."""
        await _insert_messages(db, "conv-1", 8)

        await summarizer.summarize_if_needed("conv-1")
        mock_provider.complete.reset_mock()

        # Call again - should not summarize again since no new messages fell out
        await summarizer.summarize_if_needed("conv-1")
        mock_provider.complete.assert_not_called()


class TestStructuredCompaction:
    async def test_uses_structured_prompt(self, summarizer, db, mock_provider):
        """Summarizer uses the structured compaction prompt."""
        conv_id = "conv-structured"
        await db.execute(
            "INSERT INTO conversations (id, channel, started_at) VALUES (?, ?, datetime('now'))",
            (conv_id, "test"),
        )
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            await db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (f"msg-{i}", conv_id, role, f"Message {i}"),
            )

        await summarizer.summarize_if_needed(conv_id)

        # Check the system prompt used
        call_args = mock_provider.complete.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        system_msg = messages[0]
        assert "Goal" in system_msg["content"]
        assert "Progress" in system_msg["content"]
        assert "Decisions" in system_msg["content"]

    async def test_structured_prompt_constant_exists(self):
        """STRUCTURED_COMPACTION_PROMPT has required sections."""
        assert "Goal" in STRUCTURED_COMPACTION_PROMPT
        assert "Progress" in STRUCTURED_COMPACTION_PROMPT
        assert "Decisions" in STRUCTURED_COMPACTION_PROMPT
        assert "Next Steps" in STRUCTURED_COMPACTION_PROMPT
        assert "Key Facts" in STRUCTURED_COMPACTION_PROMPT

    async def test_summary_stored_with_when_to_use(self, summarizer, db, vector_memory, mock_embedder):
        """Summary is stored with memory_type='summary' and when_to_use."""
        conv_id = "conv-typed"
        await db.execute(
            "INSERT INTO conversations (id, channel, started_at) VALUES (?, ?, datetime('now'))",
            (conv_id, "test"),
        )
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            await db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (f"msg-t-{i}", conv_id, role, f"Message {i}"),
            )

        await summarizer.summarize_if_needed(conv_id)

        # Check the vector store call - embed is called with when_to_use text
        store_call = mock_embedder.embed.call_args
        embed_text = store_call[0][0]
        assert "recalling" in embed_text.lower() or "conversation" in embed_text.lower()
