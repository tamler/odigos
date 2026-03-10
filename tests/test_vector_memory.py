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
