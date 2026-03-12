from unittest.mock import AsyncMock

import pytest

from odigos.db import Database
from odigos.memory.graph import EntityGraph
from odigos.memory.manager import MemoryManager
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.vectors import VectorMemory, MemoryResult
from odigos.providers.base import LLMResponse


@pytest.fixture
async def db(tmp_db_path):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    counter = {"n": 0}
    cache = {}

    def make_embed(text):
        if text in cache:
            return list(cache[text])
        counter["n"] += 1
        base = [0.0] * 768
        idx = counter["n"] % 768
        base[idx] = 1.0
        cache[text] = list(base)
        return list(base)

    embedder.embed.side_effect = make_embed
    embedder.embed_query.side_effect = make_embed
    return embedder


@pytest.fixture
def vector_memory(db, mock_embedder):
    return VectorMemory(embedder=mock_embedder, db=db)


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.complete.return_value = LLMResponse(
        content="Summary text", model="m", tokens_in=1, tokens_out=1, cost_usd=0.0
    )
    return provider


@pytest.fixture
def manager(vector_memory, db, mock_provider):
    graph = EntityGraph(db=db)
    resolver = EntityResolver(graph=graph, vector_memory=vector_memory)
    summarizer = ConversationSummarizer(
        db=db, vector_memory=vector_memory, llm_provider=mock_provider
    )
    return MemoryManager(
        vector_memory=vector_memory,
        graph=graph,
        resolver=resolver,
        summarizer=summarizer,
    )


class TestHybridSearch:
    async def test_hybrid_search_returns_results(self, manager, vector_memory):
        """Hybrid search finds memories via both vector and keyword paths."""
        await vector_memory.store(
            text="Python is great for data science",
            source_type="user_message",
            source_id="conv-1",
        )
        results = await manager._hybrid_search("Python data science", limit=5)
        assert len(results) >= 1

    async def test_hybrid_search_empty(self, manager):
        """Hybrid search on empty memory returns empty list."""
        results = await manager._hybrid_search("anything", limit=5)
        assert results == []

    async def test_hybrid_search_deduplicates(self, manager, vector_memory):
        """Results appearing in both vector and FTS are not duplicated."""
        await vector_memory.store(
            text="The quick brown fox jumps",
            source_type="user_message",
            source_id="conv-1",
        )
        results = await manager._hybrid_search("quick brown fox", limit=10)
        ids = [r.source_id for r in results]
        assert len(ids) == len(set(ids)) or len(results) == 1

    async def test_recall_uses_hybrid(self, manager, vector_memory):
        """recall() uses hybrid search internally."""
        await vector_memory.store(
            text="User prefers dark mode",
            source_type="user_message",
            source_id="conv-1",
        )
        context = await manager.recall("dark mode preference")
        assert "dark mode" in context
