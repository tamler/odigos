from unittest.mock import AsyncMock

import pytest

from odigos.db import Database
from odigos.memory.graph import EntityGraph
from odigos.memory.resolver import EntityResolver
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
    embedder.embed.return_value = [0.1] * 768
    embedder.embed_query.return_value = [0.1] * 768
    return embedder


@pytest.fixture
async def graph(db: Database) -> EntityGraph:
    return EntityGraph(db=db)


@pytest.fixture
def vector_memory(db, mock_embedder) -> VectorMemory:
    return VectorMemory(embedder=mock_embedder, db=db)


@pytest.fixture
def resolver(graph: EntityGraph, vector_memory: VectorMemory) -> EntityResolver:
    return EntityResolver(graph=graph, vector_memory=vector_memory, llm_provider=None)


class TestEntityResolver:
    async def test_exact_match(self, resolver: EntityResolver, graph: EntityGraph):
        """Exact name match returns existing entity."""
        entity_id = await graph.create_entity(entity_type="person", name="Alice")

        result = await resolver.resolve(name="Alice", entity_type="person", context="")

        assert result.entity_id == entity_id
        assert result.action == "matched"

    async def test_alias_match(self, resolver: EntityResolver, graph: EntityGraph):
        """Match via alias returns existing entity."""
        entity_id = await graph.create_entity(entity_type="person", name="Robert")
        await graph.update_entity(entity_id, aliases=["Bob"])

        result = await resolver.resolve(name="Bob", entity_type="person", context="")

        assert result.entity_id == entity_id
        assert result.action == "matched"

    async def test_no_match_creates_new(self, resolver: EntityResolver):
        """No match creates a new entity."""
        result = await resolver.resolve(name="NewPerson", entity_type="person", context="")

        assert result.entity_id is not None
        assert result.action == "created"

    async def test_fuzzy_match(self, resolver: EntityResolver, graph: EntityGraph):
        """Fuzzy match (LIKE) finds similar names of same type."""
        entity_id = await graph.create_entity(entity_type="project", name="Odigos Project")

        result = await resolver.resolve(name="Odigos", entity_type="project", context="")

        assert result.entity_id == entity_id
        assert result.action == "matched"
