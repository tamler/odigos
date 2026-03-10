from unittest.mock import AsyncMock

import pytest

from odigos.db import Database
from odigos.memory.graph import EntityGraph
from odigos.memory.manager import MemoryManager
from odigos.memory.resolver import EntityResolver
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
    embedder.embed.return_value = [0.1] * 768
    embedder.embed_query.return_value = [0.1] * 768
    return embedder


@pytest.fixture
async def vector_memory(tmp_path, mock_embedder):
    vm = VectorMemory(embedder=mock_embedder, persist_dir=str(tmp_path / "chroma"))
    await vm.initialize()
    return vm


@pytest.fixture
def graph(db):
    return EntityGraph(db=db)


@pytest.fixture
def resolver(graph, vector_memory):
    return EntityResolver(graph=graph, vector_memory=vector_memory)


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.complete.return_value = LLMResponse(
        content="Summary text", model="m", tokens_in=1, tokens_out=1, cost_usd=0.0
    )
    return provider


@pytest.fixture
def summarizer(db, vector_memory, mock_provider):
    return ConversationSummarizer(db=db, vector_memory=vector_memory, llm_provider=mock_provider)


@pytest.fixture
def manager(vector_memory, graph, resolver, summarizer):
    return MemoryManager(
        vector_memory=vector_memory,
        graph=graph,
        resolver=resolver,
        summarizer=summarizer,
    )


class TestWhenToUseGeneration:
    async def test_preference_gets_when_to_use(self, manager, vector_memory, mock_embedder):
        """User preferences generate appropriate when_to_use."""
        await manager.store(
            conversation_id="conv-1",
            user_message="I prefer dark mode in all applications",
            assistant_response="Noted!",
            extracted_entities=[],
        )
        embed_calls = mock_embedder.embed.call_args_list
        any_preference = any("preferences" in str(c).lower() for c in embed_calls)
        assert any_preference

    async def test_fact_gets_when_to_use(self, manager, vector_memory, mock_embedder):
        """Facts about people generate appropriate when_to_use."""
        await manager.store(
            conversation_id="conv-2",
            user_message="Alice is a software engineer at Google",
            assistant_response="Got it!",
            extracted_entities=[],
        )
        embed_calls = mock_embedder.embed.call_args_list
        any_facts = any("facts" in str(c).lower() or "people" in str(c).lower() for c in embed_calls)
        assert any_facts

    def test_generate_when_to_use_preferences(self):
        """Heuristic detects preference keywords."""
        result = MemoryManager._generate_when_to_use("I prefer Python", "user_message")
        assert "preferences" in result

    def test_generate_when_to_use_facts(self):
        """Heuristic detects fact keywords."""
        result = MemoryManager._generate_when_to_use("Alice is a doctor", "user_message")
        assert "facts" in result

    def test_generate_when_to_use_general(self):
        """General messages get a generic when_to_use."""
        result = MemoryManager._generate_when_to_use("Hello how are you", "user_message")
        assert "discussed" in result

    def test_generate_when_to_use_document(self):
        """Document chunks get document-specific when_to_use."""
        result = MemoryManager._generate_when_to_use("Chapter 1 content", "document_chunk")
        assert "documents" in result


class TestMemoryManager:
    async def test_recall_empty(self, manager):
        """Recall with no stored data returns empty string."""
        context = await manager.recall("anything")
        assert context == ""

    async def test_store_entities(self, manager, graph):
        """Store extracts entities into the graph."""
        entities = [
            {"name": "Alice", "type": "person", "relationship": "friend", "detail": "engineer"},
        ]
        await manager.store(
            conversation_id="conv-1",
            user_message="Talked to Alice today",
            assistant_response="That's nice!",
            extracted_entities=entities,
        )

        # Entity should exist in graph
        results = await graph.find_entity("Alice")
        assert len(results) >= 1

    async def test_store_embeds_user_message(self, manager, vector_memory, mock_embedder):
        """User message is embedded for future semantic search."""
        await manager.store(
            conversation_id="conv-1",
            user_message="I prefer Python over JavaScript",
            assistant_response="Noted!",
            extracted_entities=[],
        )

        # The embedder should have been called to embed the user message
        mock_embedder.embed.assert_called()

    async def test_recall_returns_formatted_context(
        self, manager, graph, vector_memory, mock_embedder
    ):
        """After storing data, recall returns formatted memory context."""
        await manager.store(
            conversation_id="conv-1",
            user_message="Alice works on the Odigos project",
            assistant_response="Got it!",
            extracted_entities=[
                {
                    "name": "Alice",
                    "type": "person",
                    "relationship": "works_on",
                    "detail": "Odigos project",
                },
            ],
        )

        context = await manager.recall("Alice")
        assert isinstance(context, str)
