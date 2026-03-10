import pytest
from odigos.memory.vectors import VectorMemory, MemoryResult


class TestVectorMemory:
    @pytest.fixture
    async def vector_memory(self, tmp_path):
        """Create a VectorMemory with a test ChromaDB collection."""
        from unittest.mock import AsyncMock

        embedder = AsyncMock()
        embedder.embed.return_value = [0.1] * 768
        embedder.embed_query.return_value = [0.1] * 768

        vm = VectorMemory(embedder=embedder, persist_dir=str(tmp_path / "chroma"))
        await vm.initialize()
        return vm

    async def test_store_and_search(self, vector_memory):
        """Store a document and retrieve it via search."""
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
        """Search on empty collection returns empty list."""
        results = await vector_memory.search("anything", limit=5)
        assert results == []

    async def test_store_returns_unique_ids(self, vector_memory):
        """Each store call returns a unique vector ID."""
        id1 = await vector_memory.store("text one", "test", "doc-1")
        id2 = await vector_memory.store("text two", "test", "doc-2")
        assert id1 != id2

    async def test_search_respects_limit(self, vector_memory):
        """Search returns at most `limit` results."""
        for i in range(10):
            await vector_memory.store(f"document {i}", "test", f"doc-{i}")

        results = await vector_memory.search("document", limit=3)
        assert len(results) <= 3

    async def test_metadata_filtering(self, vector_memory):
        """Search can filter by source_type metadata."""
        await vector_memory.store("user said hello", "user_message", "conv-1")
        await vector_memory.store("chunk about cats", "document_chunk", "doc-1")

        results = await vector_memory.search("hello", limit=10, source_type="user_message")
        for r in results:
            assert r.source_type == "user_message"
