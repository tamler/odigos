from unittest.mock import AsyncMock

import pytest

from odigos.memory.vectors import VectorMemory, MemoryResult


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed.return_value = [0.1] * 768
    embedder.embed_query.return_value = [0.1] * 768
    return embedder


@pytest.fixture
async def vector_memory(tmp_path, mock_embedder):
    vm = VectorMemory(embedder=mock_embedder, persist_dir=str(tmp_path / "chroma"))
    await vm.initialize()
    return vm


class TestWhenToUse:
    async def test_store_with_when_to_use(self, vector_memory, mock_embedder):
        """when_to_use is embedded instead of raw content."""
        vec_id = await vector_memory.store(
            text="User prefers dark mode in all applications",
            source_type="user_message",
            source_id="conv-1",
            when_to_use="when configuring UI themes or display settings",
        )
        assert vec_id
        embed_arg = mock_embedder.embed.call_args[0][0]
        assert "configuring UI themes" in embed_arg

    async def test_store_without_when_to_use_uses_content(self, vector_memory, mock_embedder):
        """Without when_to_use, falls back to embedding the content."""
        await vector_memory.store(
            text="Some fact about the user",
            source_type="user_message",
            source_id="conv-1",
        )
        embed_arg = mock_embedder.embed.call_args[0][0]
        assert "Some fact about the user" in embed_arg

    async def test_search_returns_when_to_use(self, vector_memory):
        """Search results include the when_to_use field."""
        await vector_memory.store(
            text="Alice is a software engineer",
            source_type="user_message",
            source_id="conv-1",
            when_to_use="when discussing Alice's profession or technical skills",
        )
        results = await vector_memory.search("Alice's job")
        assert len(results) >= 1
        assert results[0].when_to_use == "when discussing Alice's profession or technical skills"

    async def test_backward_compatible_search(self, vector_memory):
        """Memories stored without when_to_use still searchable."""
        await vector_memory.store(
            text="Meeting at 3pm tomorrow",
            source_type="user_message",
            source_id="conv-2",
        )
        results = await vector_memory.search("meeting time")
        assert len(results) >= 1
        assert results[0].when_to_use == ""


class TestMemoryType:
    async def test_store_with_memory_type(self, vector_memory):
        """Memories can be stored with a type classification."""
        await vector_memory.store(
            text="User prefers Python",
            source_type="user_message",
            source_id="conv-1",
            memory_type="personal",
        )
        results = await vector_memory.search("preferences")
        assert results[0].memory_type == "personal"

    async def test_filter_by_memory_type(self, vector_memory):
        """Search can filter by memory_type."""
        await vector_memory.store(
            text="Deploy with docker compose up",
            source_type="user_message",
            source_id="conv-1",
            memory_type="procedural",
        )
        await vector_memory.store(
            text="User likes dark mode",
            source_type="user_message",
            source_id="conv-2",
            memory_type="personal",
        )
        results = await vector_memory.search("user settings", memory_type="personal")
        for r in results:
            assert r.memory_type == "personal"

    async def test_default_memory_type_is_general(self, vector_memory):
        """Default memory_type is 'general'."""
        await vector_memory.store(
            text="Random fact",
            source_type="user_message",
            source_id="conv-1",
        )
        results = await vector_memory.search("fact")
        assert results[0].memory_type == "general"
