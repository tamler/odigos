import pytest

from odigos.db import Database
from odigos.memory.graph import EntityGraph


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def graph(db: Database) -> EntityGraph:
    return EntityGraph(db=db)


class TestEntityGraph:
    async def test_create_entity(self, graph: EntityGraph):
        """Create an entity and verify it's stored."""
        entity_id = await graph.create_entity(
            entity_type="person", name="Alice", properties={"role": "engineer"}
        )
        assert entity_id is not None

        entity = await graph.get_entity(entity_id)
        assert entity["name"] == "Alice"
        assert entity["type"] == "person"

    async def test_find_entity_by_name(self, graph: EntityGraph):
        """Find entity by exact name match."""
        await graph.create_entity(entity_type="person", name="Bob")

        results = await graph.find_entity("Bob")
        assert len(results) >= 1
        assert results[0]["name"] == "Bob"

    async def test_find_entity_by_alias(self, graph: EntityGraph):
        """Find entity by alias stored in aliases_json."""
        entity_id = await graph.create_entity(entity_type="person", name="Robert")
        await graph.update_entity(entity_id, aliases=["Bob", "Bobby"])

        results = await graph.find_entity("Bob")
        assert len(results) >= 1
        assert results[0]["name"] == "Robert"

    async def test_create_edge(self, graph: EntityGraph):
        """Create an edge between two entities."""
        id_a = await graph.create_entity(entity_type="person", name="Alice")
        id_b = await graph.create_entity(entity_type="project", name="Odigos")

        edge_id = await graph.create_edge(
            source_id=id_a, relationship="works_on", target_id=id_b
        )
        assert edge_id is not None

    async def test_get_related(self, graph: EntityGraph):
        """Get all entities related to a given entity (one hop)."""
        id_a = await graph.create_entity(entity_type="person", name="Alice")
        id_b = await graph.create_entity(entity_type="project", name="Odigos")
        id_c = await graph.create_entity(entity_type="person", name="Bob")

        await graph.create_edge(source_id=id_a, relationship="works_on", target_id=id_b)
        await graph.create_edge(source_id=id_c, relationship="works_on", target_id=id_b)

        related = await graph.get_related(id_a)
        names = [r["name"] for r in related]
        assert "Odigos" in names

    async def test_traverse_depth(self, graph: EntityGraph):
        """Multi-hop traversal returns transitive connections."""
        id_a = await graph.create_entity(entity_type="person", name="Alice")
        id_b = await graph.create_entity(entity_type="project", name="Odigos")
        id_c = await graph.create_entity(entity_type="concept", name="SQLite")

        await graph.create_edge(source_id=id_a, relationship="works_on", target_id=id_b)
        await graph.create_edge(source_id=id_b, relationship="uses", target_id=id_c)

        # Depth 2 should reach SQLite from Alice
        reachable = await graph.traverse(id_a, depth=2)
        names = [r["name"] for r in reachable]
        assert "Odigos" in names
        assert "SQLite" in names

    async def test_merge_entities(self, graph: EntityGraph):
        """Merging two entities reassigns edges and removes the duplicate."""
        id_keep = await graph.create_entity(entity_type="person", name="Robert")
        id_remove = await graph.create_entity(entity_type="person", name="Bob")
        id_project = await graph.create_entity(entity_type="project", name="Odigos")

        await graph.create_edge(
            source_id=id_remove, relationship="works_on", target_id=id_project
        )

        await graph.merge_entities(keep_id=id_keep, remove_id=id_remove)

        # Edge should now point from Robert
        related = await graph.get_related(id_keep)
        names = [r["name"] for r in related]
        assert "Odigos" in names

        # Bob entity should be gone
        removed = await graph.get_entity(id_remove)
        assert removed is None
