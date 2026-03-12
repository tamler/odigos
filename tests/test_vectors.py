import pytest
from unittest.mock import AsyncMock
from odigos.db import Database
from odigos.memory.vectors import VectorMemory, MemoryResult


@pytest.fixture
async def db(tmp_db_path):
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
def vector_memory(db, mock_embedder):
    return VectorMemory(embedder=mock_embedder, db=db)


class TestVectorMemory:
    async def test_store_and_search(self, vector_memory):
        vec_id = await vector_memory.store(
            text="The cat sat on the mat",
            source_type="test",
            source_id="doc-1",
        )
        assert vec_id is not None
        results = await vector_memory.search("cat mat", limit=5)
        assert len(results) >= 1
        assert results[0].content_preview == "The cat sat on the mat"
        assert results[0].source_type == "test"

    async def test_search_empty_collection(self, vector_memory):
        results = await vector_memory.search("anything", limit=5)
        assert results == []

    async def test_store_returns_unique_ids(self, vector_memory):
        id1 = await vector_memory.store("text one", "test", "doc-1")
        id2 = await vector_memory.store("text two", "test", "doc-2")
        assert id1 != id2

    async def test_search_respects_limit(self, vector_memory):
        for i in range(10):
            await vector_memory.store(f"document {i}", "test", f"doc-{i}")
        results = await vector_memory.search("document", limit=3)
        assert len(results) <= 3

    async def test_metadata_filtering(self, vector_memory):
        await vector_memory.store("user said hello", "user_message", "conv-1")
        await vector_memory.store("chunk about cats", "document_chunk", "doc-1")
        results = await vector_memory.search("hello", limit=10, source_type="user_message")
        for r in results:
            assert r.source_type == "user_message"

    async def test_count(self, vector_memory):
        assert await vector_memory.count() == 0
        await vector_memory.store("text", "test", "doc-1")
        assert await vector_memory.count() == 1

    async def test_delete_by_source(self, vector_memory):
        await vector_memory.store("chunk 1", "document_chunk", "doc-1")
        await vector_memory.store("chunk 2", "document_chunk", "doc-1")
        await vector_memory.store("other", "user_message", "conv-1")
        assert await vector_memory.count() == 3
        await vector_memory.delete_by_source("document_chunk", "doc-1")
        assert await vector_memory.count() == 1
