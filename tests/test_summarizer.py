import uuid
from unittest.mock import AsyncMock

import pytest

from odigos.db import Database
from odigos.memory.summarizer import ConversationSummarizer
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
    embedder.embed.return_value = [0.1] * 1536
    return embedder


@pytest.fixture
async def vector_memory(db: Database, mock_embedder) -> VectorMemory:
    vm = VectorMemory(db=db, embedder=mock_embedder)
    await vm.initialize()
    return vm


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.complete.return_value = LLMResponse(
        content="Summary: discussed project architecture and SQLite choice.",
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
        assert "Summary" in summaries[0]["summary"]
        mock_provider.complete.assert_called_once()

    async def test_does_not_resummarize(self, summarizer, db, mock_provider):
        """Already-summarized messages are not re-summarized."""
        await _insert_messages(db, "conv-1", 8)

        await summarizer.summarize_if_needed("conv-1")
        mock_provider.complete.reset_mock()

        # Call again - should not summarize again since no new messages fell out
        await summarizer.summarize_if_needed("conv-1")
        mock_provider.complete.assert_not_called()
