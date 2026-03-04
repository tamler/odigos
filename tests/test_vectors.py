from unittest.mock import AsyncMock

import pytest

from odigos.db import Database
from odigos.memory.vectors import VectorMemory


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    # Return a deterministic 1536-d vector
    embedder.embed.return_value = [0.1] * 1536
    return embedder


@pytest.fixture
async def vector_memory(db: Database, mock_embedder) -> VectorMemory:
    vm = VectorMemory(db=db, embedder=mock_embedder)
    await vm.initialize()
    return vm


class TestVectorMemory:
    async def test_store_and_search(self, vector_memory: VectorMemory, mock_embedder):
        """Store a memory and retrieve it via search."""
        await vector_memory.store(
            text="Alice prefers morning meetings",
            source_type="message",
            source_id="msg-1",
        )

        results = await vector_memory.search("morning meetings", limit=5)

        assert len(results) >= 1
        assert results[0].content_preview == "Alice prefers morning meetings"
        assert results[0].source_type == "message"
        assert results[0].source_id == "msg-1"

    async def test_search_empty_returns_empty(self, vector_memory: VectorMemory):
        """Search with no stored vectors returns empty list."""
        results = await vector_memory.search("anything", limit=5)
        assert results == []

    async def test_store_multiple_and_limit(self, vector_memory: VectorMemory, mock_embedder):
        """Store multiple memories and verify limit is respected."""
        for i in range(5):
            await vector_memory.store(
                text=f"Memory {i}",
                source_type="message",
                source_id=f"msg-{i}",
            )

        results = await vector_memory.search("memory", limit=3)
        assert len(results) <= 3

    async def test_creates_virtual_table(self, db: Database, mock_embedder):
        """Virtual table is created on initialize."""
        vm = VectorMemory(db=db, embedder=mock_embedder)
        await vm.initialize()

        # Verify table exists by querying sqlite_master
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_vectors'"
        )
        assert row is not None
