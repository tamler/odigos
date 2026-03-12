from unittest.mock import AsyncMock

import pytest

from odigos.memory.manager import MemoryManager
from odigos.memory.graph import EntityGraph
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.vectors import VectorMemory
from odigos.db import Database
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
    cache = {}
    counter = {"n": 0}

    def make_embed(text):
        if text in cache:
            return list(cache[text])
        counter["n"] += 1
        # Use different dominant dimensions so cosine distance is large
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


class TestDeduplication:
    async def test_duplicate_message_not_stored_twice(self, manager, vector_memory):
        """Storing the same message twice should not create duplicate vectors."""
        await manager.store(
            conversation_id="conv-1",
            user_message="I prefer Python over JavaScript for backend work",
            assistant_response="Noted!",
            extracted_entities=[],
        )
        count_after_first = await vector_memory.count()

        await manager.store(
            conversation_id="conv-2",
            user_message="I prefer Python over JavaScript for backend work",
            assistant_response="Got it!",
            extracted_entities=[],
        )
        count_after_second = await vector_memory.count()

        assert count_after_second == count_after_first

    async def test_different_messages_both_stored(self, manager, vector_memory):
        """Genuinely different messages should both be stored."""
        await manager.store(
            conversation_id="conv-1",
            user_message="I prefer Python for backend work",
            assistant_response="Noted!",
            extracted_entities=[],
        )
        count_first = await vector_memory.count()

        await manager.store(
            conversation_id="conv-2",
            user_message="My favorite food is sushi and I eat it every Friday",
            assistant_response="Yum!",
            extracted_entities=[],
        )
        count_second = await vector_memory.count()

        assert count_second > count_first
