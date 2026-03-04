# Phase 1: Memory Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add memory layer -- vector search via sqlite-vec, entity-relationship graph, entity resolution pipeline, conversation summarization, and upgraded context assembly that injects relevant memories into every LLM call.

**Architecture:** New `odigos/memory/` package with four modules (vectors, graph, resolver, summarizer) behind a unified MemoryManager. New `odigos/providers/embeddings.py` wraps OpenRouter embeddings API. Existing context.py, reflector.py, agent.py, and main.py are upgraded to wire memory in. sqlite-vec loaded as an extension in db.py.

**Tech Stack:** Python 3.12, sqlite-vec, OpenRouter embeddings API (openai/text-embedding-3-small, 1536d), aiosqlite, httpx, pytest + pytest-asyncio

---

### Task 1: Add sqlite-vec Dependency and Database Extension Loading

**Files:**
- Modify: `pyproject.toml` (add sqlite-vec dep)
- Modify: `odigos/db.py:14-19` (load sqlite-vec extension in initialize)
- Test: `tests/test_db.py` (add test for vec extension loaded)

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
async def test_sqlite_vec_extension_loaded(tmp_db_path: str):
    """Verify sqlite-vec extension is loaded and vec0 is available."""
    db = Database(tmp_db_path, migrations_dir="migrations")
    await db.initialize()
    try:
        # sqlite-vec registers a vec_version() function
        row = await db.fetch_one("SELECT vec_version() AS v")
        assert row is not None
        assert row["v"]  # non-empty version string
    finally:
        await db.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_sqlite_vec_extension_loaded -v`
Expected: FAIL (sqlite-vec not installed, vec_version not found)

**Step 3: Add dependency and load extension**

In `pyproject.toml`, add `"sqlite-vec >= 0.1.0"` to the dependencies list.

In `odigos/db.py`, modify the `initialize` method to load the sqlite-vec extension after connecting:

```python
import sqlite_vec

async def initialize(self) -> None:
    """Open connection and run migrations."""
    self._conn = await aiosqlite.connect(self.db_path)
    self._conn.row_factory = aiosqlite.Row
    # Load sqlite-vec extension
    await self._conn.enable_load_extension(True)
    await self._conn.load_extension(sqlite_vec.loadable_path())
    await self._conn.enable_load_extension(False)
    await self._conn.execute("PRAGMA journal_mode=WAL")
    await self._conn.execute("PRAGMA foreign_keys=ON")
    await self.run_migrations()
```

Add `import sqlite_vec` at the top of `db.py`.

Run `uv sync` to install the new dependency.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: ALL PASS (including new vec extension test)

**Step 5: Commit**

```bash
git add pyproject.toml odigos/db.py tests/test_db.py uv.lock
git commit -m "feat: add sqlite-vec dependency and load extension in database init"
```

---

### Task 2: Memory Tables Migration

**Files:**
- Create: `migrations/002_memory.sql`
- Test: `tests/test_db.py` (add test for new tables)

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
async def test_memory_tables_created(tmp_db_path: str):
    """Verify migration 002 creates entities, edges, and conversation_summaries tables."""
    db = Database(tmp_db_path, migrations_dir="migrations")
    await db.initialize()
    try:
        # Check entities table exists
        entity_row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='entities'"
        )
        assert entity_row is not None

        # Check edges table exists
        edge_row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='edges'"
        )
        assert edge_row is not None

        # Check conversation_summaries table exists
        summary_row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_summaries'"
        )
        assert summary_row is not None

        # Verify we can insert an entity
        await db.execute(
            "INSERT INTO entities (id, type, name) VALUES (?, ?, ?)",
            ("e1", "person", "Alice"),
        )
        row = await db.fetch_one("SELECT name FROM entities WHERE id = 'e1'")
        assert row["name"] == "Alice"
    finally:
        await db.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_memory_tables_created -v`
Expected: FAIL (tables don't exist)

**Step 3: Create migration file**

Create `migrations/002_memory.sql`:

```sql
-- Entity-relationship graph
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    aliases_json TEXT,
    confidence REAL DEFAULT 1.0,
    status TEXT DEFAULT 'active',
    properties_json TEXT,
    summary TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    source TEXT
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT REFERENCES entities(id),
    relationship TEXT NOT NULL,
    target_id TEXT REFERENCES entities(id),
    strength REAL DEFAULT 1.0,
    metadata_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    last_confirmed TEXT
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_rel ON edges(relationship);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

-- Conversation summaries
CREATE TABLE IF NOT EXISTS conversation_summaries (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    start_message_idx INTEGER,
    end_message_idx INTEGER,
    summary TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add migrations/002_memory.sql tests/test_db.py
git commit -m "feat: add migration 002 for entities, edges, and conversation_summaries"
```

---

### Task 3: Embedding Provider

**Files:**
- Create: `odigos/providers/embeddings.py`
- Create: `tests/test_embeddings.py`

**Step 1: Write the failing test**

Create `tests/test_embeddings.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from odigos.providers.embeddings import EmbeddingProvider


@pytest.fixture
def provider():
    return EmbeddingProvider(api_key="test-key")


class TestEmbeddingProvider:
    async def test_embed_single_text(self, provider: EmbeddingProvider):
        """Embeds a single text string and returns a 1536-d vector."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1] * 1536}],
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }

        with patch.object(provider._client, "post", return_value=mock_response):
            result = await provider.embed("Hello world")

        assert len(result) == 1536
        assert result[0] == pytest.approx(0.1)

    async def test_embed_batch(self, provider: EmbeddingProvider):
        """Embeds a list of texts and returns a list of vectors."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1] * 1536},
                {"embedding": [0.2] * 1536},
            ],
            "usage": {"prompt_tokens": 10, "total_tokens": 10},
        }

        with patch.object(provider._client, "post", return_value=mock_response):
            results = await provider.embed_batch(["Hello", "World"])

        assert len(results) == 2
        assert len(results[0]) == 1536
        assert len(results[1]) == 1536

    async def test_embed_api_error_raises(self, provider: EmbeddingProvider):
        """Non-200 response raises RuntimeError."""
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(provider._client, "post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="Embedding API error"):
                await provider.embed("fail")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_embeddings.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement the embedding provider**

Create `odigos/providers/embeddings.py`:

```python
import logging

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
DEFAULT_MODEL = "openai/text-embedding-3-small"


class EmbeddingProvider:
    """OpenRouter embedding API wrapper (1536-d vectors)."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns a 1536-d vector."""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts. Returns a list of 1536-d vectors."""
        payload = {
            "model": self.model,
            "input": texts,
        }

        response = await self._client.post(OPENROUTER_EMBEDDINGS_URL, json=payload)

        if response.status_code != 200:
            raise RuntimeError(
                f"Embedding API error {response.status_code}: {response.text}"
            )

        data = response.json()
        return [item["embedding"] for item in data["data"]]

    async def close(self) -> None:
        await self._client.aclose()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_embeddings.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/providers/embeddings.py tests/test_embeddings.py
git commit -m "feat: add embedding provider wrapping OpenRouter embeddings API"
```

---

### Task 4: Vector Memory Module

**Files:**
- Create: `odigos/memory/__init__.py`
- Create: `odigos/memory/vectors.py`
- Create: `tests/test_vectors.py`

**Step 1: Write the failing test**

Create `tests/test_vectors.py`:

```python
import uuid
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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vectors.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement vector memory**

Create `odigos/memory/__init__.py`:

```python
```

Create `odigos/memory/vectors.py`:

```python
import uuid
from dataclasses import dataclass

from odigos.db import Database
from odigos.providers.embeddings import EmbeddingProvider

VECTOR_DIMENSIONS = 1536


@dataclass
class MemoryResult:
    content_preview: str
    source_type: str
    source_id: str
    distance: float


class VectorMemory:
    """sqlite-vec backed vector store for semantic memory search."""

    def __init__(self, db: Database, embedder: EmbeddingProvider) -> None:
        self.db = db
        self.embedder = embedder

    async def initialize(self) -> None:
        """Create the vec0 virtual table if it doesn't exist."""
        await self.db.conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors USING vec0(
                id TEXT PRIMARY KEY,
                embedding FLOAT[{VECTOR_DIMENSIONS}],
                +source_type TEXT,
                +source_id TEXT,
                +content_preview TEXT,
                +created_at TEXT
            )
            """
        )
        await self.db.conn.commit()

    async def store(self, text: str, source_type: str, source_id: str) -> str:
        """Embed text and store in vector table. Returns the vector ID."""
        vector = await self.embedder.embed(text)
        vec_id = str(uuid.uuid4())

        await self.db.conn.execute(
            "INSERT INTO memory_vectors (id, embedding, source_type, source_id, "
            "content_preview, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (vec_id, serialize_vector(vector), source_type, source_id, text[:500]),
        )
        await self.db.conn.commit()
        return vec_id

    async def search(self, query: str, limit: int = 5) -> list[MemoryResult]:
        """Embed query and find nearest neighbors."""
        vector = await self.embedder.embed(query)

        cursor = await self.db.conn.execute(
            """
            SELECT id, distance, source_type, source_id, content_preview
            FROM memory_vectors
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            (serialize_vector(vector), limit),
        )
        rows = await cursor.fetchall()

        return [
            MemoryResult(
                content_preview=row[4],
                source_type=row[2],
                source_id=row[3],
                distance=row[1],
            )
            for row in rows
        ]


def serialize_vector(vector: list[float]) -> bytes:
    """Serialize a float vector to bytes for sqlite-vec."""
    import struct

    return struct.pack(f"{len(vector)}f", *vector)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_vectors.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/memory/__init__.py odigos/memory/vectors.py tests/test_vectors.py
git commit -m "feat: add vector memory module with sqlite-vec store and search"
```

---

### Task 5: Entity Graph Module

**Files:**
- Create: `odigos/memory/graph.py`
- Create: `tests/test_graph.py`

**Step 1: Write the failing test**

Create `tests/test_graph.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement entity graph**

Create `odigos/memory/graph.py`:

```python
import json
import uuid

from odigos.db import Database


class EntityGraph:
    """Query helpers for the entity-relationship graph tables."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_entity(
        self,
        entity_type: str,
        name: str,
        properties: dict | None = None,
        confidence: float = 1.0,
        source: str | None = None,
    ) -> str:
        """Create a new entity. Returns the entity ID."""
        entity_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO entities (id, type, name, properties_json, confidence, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entity_id,
                entity_type,
                name,
                json.dumps(properties) if properties else None,
                confidence,
                source,
            ),
        )
        return entity_id

    async def get_entity(self, entity_id: str) -> dict | None:
        """Get a single entity by ID."""
        return await self.db.fetch_one(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        )

    async def find_entity(self, name: str) -> list[dict]:
        """Find entities by exact name or alias match."""
        # Exact name match
        results = await self.db.fetch_all(
            "SELECT * FROM entities WHERE name = ? AND status = 'active'", (name,)
        )
        if results:
            return results

        # Alias match (search aliases_json)
        all_with_aliases = await self.db.fetch_all(
            "SELECT * FROM entities WHERE aliases_json IS NOT NULL AND status = 'active'"
        )
        matches = []
        for row in all_with_aliases:
            aliases = json.loads(row["aliases_json"])
            if name in aliases:
                matches.append(row)
        return matches

    async def update_entity(
        self,
        entity_id: str,
        name: str | None = None,
        aliases: list[str] | None = None,
        properties: dict | None = None,
        confidence: float | None = None,
        summary: str | None = None,
    ) -> None:
        """Update entity fields. Only provided fields are updated."""
        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if aliases is not None:
            updates.append("aliases_json = ?")
            params.append(json.dumps(aliases))
        if properties is not None:
            updates.append("properties_json = ?")
            params.append(json.dumps(properties))
        if confidence is not None:
            updates.append("confidence = ?")
            params.append(confidence)
        if summary is not None:
            updates.append("summary = ?")
            params.append(summary)

        if not updates:
            return

        updates.append("updated_at = datetime('now')")
        params.append(entity_id)

        await self.db.execute(
            f"UPDATE entities SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )

    async def create_edge(
        self,
        source_id: str,
        relationship: str,
        target_id: str,
        metadata: dict | None = None,
        strength: float = 1.0,
    ) -> int:
        """Create an edge between two entities. Returns the edge ID."""
        cursor = await self.db.conn.execute(
            "INSERT INTO edges (source_id, relationship, target_id, strength, "
            "metadata_json, last_confirmed) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (
                source_id,
                relationship,
                target_id,
                strength,
                json.dumps(metadata) if metadata else None,
            ),
        )
        await self.db.conn.commit()
        return cursor.lastrowid

    async def get_related(self, entity_id: str) -> list[dict]:
        """Get all entities one hop away from the given entity."""
        return await self.db.fetch_all(
            """
            SELECT DISTINCT e.* FROM entities e
            JOIN edges ON (
                (edges.source_id = ? AND edges.target_id = e.id) OR
                (edges.target_id = ? AND edges.source_id = e.id)
            )
            WHERE e.status = 'active'
            """,
            (entity_id, entity_id),
        )

    async def traverse(self, entity_id: str, depth: int = 2) -> list[dict]:
        """Multi-hop traversal using recursive CTE. Returns all reachable entities."""
        return await self.db.fetch_all(
            """
            WITH RECURSIVE reachable(id, depth) AS (
                -- Seed: direct neighbors
                SELECT CASE
                    WHEN edges.source_id = ? THEN edges.target_id
                    ELSE edges.source_id
                END, 1
                FROM edges
                WHERE edges.source_id = ? OR edges.target_id = ?

                UNION

                -- Recurse
                SELECT CASE
                    WHEN edges.source_id = reachable.id THEN edges.target_id
                    ELSE edges.source_id
                END, reachable.depth + 1
                FROM edges
                JOIN reachable ON (
                    edges.source_id = reachable.id OR edges.target_id = reachable.id
                )
                WHERE reachable.depth < ?
            )
            SELECT DISTINCT e.* FROM entities e
            JOIN reachable ON e.id = reachable.id
            WHERE e.id != ? AND e.status = 'active'
            """,
            (entity_id, entity_id, entity_id, depth, entity_id),
        )

    async def merge_entities(self, keep_id: str, remove_id: str) -> None:
        """Merge remove_id into keep_id: reassign edges, combine aliases, delete duplicate."""
        # Get both entities
        keep = await self.get_entity(keep_id)
        remove = await self.get_entity(remove_id)
        if not keep or not remove:
            return

        # Combine aliases
        keep_aliases = json.loads(keep["aliases_json"]) if keep["aliases_json"] else []
        remove_aliases = json.loads(remove["aliases_json"]) if remove["aliases_json"] else []
        combined = list(set(keep_aliases + remove_aliases + [remove["name"]]))
        await self.update_entity(keep_id, aliases=combined)

        # Reassign edges
        await self.db.execute(
            "UPDATE edges SET source_id = ? WHERE source_id = ?",
            (keep_id, remove_id),
        )
        await self.db.execute(
            "UPDATE edges SET target_id = ? WHERE target_id = ?",
            (keep_id, remove_id),
        )

        # Delete the removed entity
        await self.db.execute("DELETE FROM entities WHERE id = ?", (remove_id,))
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_graph.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/memory/graph.py tests/test_graph.py
git commit -m "feat: add entity graph module with CRUD, traversal, and merge"
```

---

### Task 6: Entity Resolution Pipeline

**Files:**
- Create: `odigos/memory/resolver.py`
- Create: `tests/test_resolver.py`

**Step 1: Write the failing test**

Create `tests/test_resolver.py`:

```python
from unittest.mock import AsyncMock

import pytest

from odigos.db import Database
from odigos.memory.graph import EntityGraph
from odigos.memory.resolver import EntityResolver, ResolutionResult
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
    embedder.embed.return_value = [0.1] * 1536
    return embedder


@pytest.fixture
async def graph(db: Database) -> EntityGraph:
    return EntityGraph(db=db)


@pytest.fixture
async def vector_memory(db: Database, mock_embedder) -> VectorMemory:
    vm = VectorMemory(db=db, embedder=mock_embedder)
    await vm.initialize()
    return vm


@pytest.fixture
def resolver(graph: EntityGraph, vector_memory: VectorMemory) -> EntityResolver:
    return EntityResolver(graph=graph, vector_memory=vector_memory, llm_provider=None)


class TestEntityResolver:
    async def test_exact_match(self, resolver: EntityResolver, graph: EntityGraph):
        """Exact name match returns existing entity."""
        entity_id = await graph.create_entity(entity_type="person", name="Alice")

        result = await resolver.resolve(
            name="Alice", entity_type="person", context=""
        )

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
        result = await resolver.resolve(
            name="NewPerson", entity_type="person", context=""
        )

        assert result.entity_id is not None
        assert result.action == "created"

    async def test_fuzzy_match(self, resolver: EntityResolver, graph: EntityGraph):
        """Fuzzy match (LIKE) finds similar names of same type."""
        entity_id = await graph.create_entity(entity_type="project", name="Odigos Project")

        result = await resolver.resolve(
            name="Odigos", entity_type="project", context=""
        )

        assert result.entity_id == entity_id
        assert result.action == "matched"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_resolver.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement entity resolver**

Create `odigos/memory/resolver.py`:

```python
import logging
from dataclasses import dataclass

from odigos.memory.graph import EntityGraph
from odigos.memory.vectors import VectorMemory

logger = logging.getLogger(__name__)

CONFIDENCE_HIGH = 0.8
CONFIDENCE_LOW = 0.3


@dataclass
class ResolutionResult:
    entity_id: str
    action: str  # "matched", "created", "created_low_confidence"
    confidence: float


class EntityResolver:
    """Multi-stage entity resolution pipeline.

    Stages: exact match -> fuzzy match -> alias match -> vector match -> create new.
    LLM tiebreaker is deferred until an LLM provider is available for cheap calls.
    """

    def __init__(
        self,
        graph: EntityGraph,
        vector_memory: VectorMemory,
        llm_provider=None,
    ) -> None:
        self.graph = graph
        self.vector_memory = vector_memory
        self.llm_provider = llm_provider

    async def resolve(
        self, name: str, entity_type: str, context: str
    ) -> ResolutionResult:
        """Resolve a candidate entity against the existing graph."""

        # Stage 1: Exact match
        exact = await self.graph.find_entity(name)
        exact_typed = [e for e in exact if e["type"] == entity_type]
        if len(exact_typed) == 1:
            return ResolutionResult(
                entity_id=exact_typed[0]["id"],
                action="matched",
                confidence=1.0,
            )

        # Stage 2: Fuzzy match (LIKE with type filter)
        fuzzy = await self.graph.db.fetch_all(
            "SELECT * FROM entities WHERE name LIKE ? AND type = ? AND status = 'active'",
            (f"%{name}%", entity_type),
        )
        if len(fuzzy) == 1:
            return ResolutionResult(
                entity_id=fuzzy[0]["id"],
                action="matched",
                confidence=0.85,
            )

        # Stage 3: Alias match (already covered in find_entity, but check
        # across all types if exact_typed was empty)
        if exact and not exact_typed:
            # Found by name/alias but different type -- treat as no match
            pass

        # Stage 4: Vector match
        vector_results = await self.vector_memory.search(
            f"{entity_type}: {name}", limit=3
        )
        for vr in vector_results:
            if vr.source_type == "entity_name" and vr.distance < 0.3:
                entity = await self.graph.get_entity(vr.source_id)
                if entity and entity["type"] == entity_type:
                    return ResolutionResult(
                        entity_id=entity["id"],
                        action="matched",
                        confidence=0.7,
                    )

        # Stage 5: No match -- create new entity
        entity_id = await self.graph.create_entity(
            entity_type=entity_type, name=name, source="extraction"
        )

        # Embed the entity name for future vector matching
        await self.vector_memory.store(
            text=f"{entity_type}: {name}",
            source_type="entity_name",
            source_id=entity_id,
        )

        return ResolutionResult(
            entity_id=entity_id,
            action="created",
            confidence=1.0,
        )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_resolver.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/memory/resolver.py tests/test_resolver.py
git commit -m "feat: add entity resolution pipeline (exact, fuzzy, alias, vector)"
```

---

### Task 7: Conversation Summarizer

**Files:**
- Create: `odigos/memory/summarizer.py`
- Create: `tests/test_summarizer.py`

**Step 1: Write the failing test**

Create `tests/test_summarizer.py`:

```python
import uuid
from unittest.mock import AsyncMock

import pytest

from odigos.db import Database
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
    embedder.embed.return_value = [0.1] * 1536
    return embedder


@pytest.fixture
async def vector_memory(db: Database, mock_embedder) -> VectorMemory:
    vm = VectorMemory(db=db, embedder=mock_embedder)
    await vm.initialize()
    return vm


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.complete.return_value = LLMResponse(
        content="Summary: discussed project architecture and SQLite choice.",
        model="test/model",
        tokens_in=100,
        tokens_out=20,
        cost_usd=0.0,
    )
    return provider


@pytest.fixture
def summarizer(db, vector_memory, mock_provider):
    return ConversationSummarizer(
        db=db,
        vector_memory=vector_memory,
        llm_provider=mock_provider,
        context_window=5,  # small window for testing
    )


async def _insert_messages(db: Database, conversation_id: str, count: int):
    """Helper: insert N alternating user/assistant messages."""
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conversation_id, "test"),
    )
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), conversation_id, role, f"Message {i}"),
        )


class TestConversationSummarizer:
    async def test_no_summarization_within_window(self, summarizer, db):
        """No summarization needed when messages fit in context window."""
        await _insert_messages(db, "conv-1", 4)  # under window of 5

        await summarizer.summarize_if_needed("conv-1")

        summaries = await db.fetch_all(
            "SELECT * FROM conversation_summaries WHERE conversation_id = 'conv-1'"
        )
        assert len(summaries) == 0

    async def test_summarizes_messages_beyond_window(self, summarizer, db, mock_provider):
        """Messages beyond the window get summarized."""
        await _insert_messages(db, "conv-1", 8)  # 3 beyond window of 5

        await summarizer.summarize_if_needed("conv-1")

        summaries = await db.fetch_all(
            "SELECT * FROM conversation_summaries WHERE conversation_id = 'conv-1'"
        )
        assert len(summaries) == 1
        assert "Summary" in summaries[0]["summary"]
        mock_provider.complete.assert_called_once()

    async def test_does_not_resummarize(self, summarizer, db, mock_provider):
        """Already-summarized messages are not re-summarized."""
        await _insert_messages(db, "conv-1", 8)

        await summarizer.summarize_if_needed("conv-1")
        mock_provider.complete.reset_mock()

        # Add one more message (still only 4 unsummarized within the window)
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), "conv-1", "user", "New message"),
        )

        await summarizer.summarize_if_needed("conv-1")
        # Should not call LLM again since no new messages fell out of window
        # (9 total, 3 already summarized, 6 remaining -- 1 over window but depends on impl)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_summarizer.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement conversation summarizer**

Create `odigos/memory/summarizer.py`:

```python
import logging
import uuid

from odigos.db import Database
from odigos.memory.vectors import VectorMemory
from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

SUMMARIZE_PROMPT = (
    "Summarize this conversation segment in 2-3 sentences. "
    "Focus on key facts, decisions, and entities mentioned."
)


class ConversationSummarizer:
    """Summarizes conversation segments that fall out of the context window."""

    def __init__(
        self,
        db: Database,
        vector_memory: VectorMemory,
        llm_provider: LLMProvider,
        context_window: int = 20,
    ) -> None:
        self.db = db
        self.vector_memory = vector_memory
        self.llm_provider = llm_provider
        self.context_window = context_window

    async def summarize_if_needed(self, conversation_id: str) -> None:
        """Check if there are messages beyond the context window that need summarizing."""
        # Get total message count
        row = await self.db.fetch_one(
            "SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        total = row["cnt"] if row else 0

        if total <= self.context_window:
            return

        # Find the highest end_message_idx already summarized
        last_summary = await self.db.fetch_one(
            "SELECT MAX(end_message_idx) as max_idx FROM conversation_summaries "
            "WHERE conversation_id = ?",
            (conversation_id,),
        )
        already_summarized = (
            last_summary["max_idx"] if last_summary and last_summary["max_idx"] else 0
        )

        # Messages to summarize: from already_summarized to (total - context_window)
        messages_to_keep = self.context_window
        cutoff = total - messages_to_keep

        if cutoff <= already_summarized:
            return

        # Fetch the unsummarized messages that need to be summarized
        messages = await self.db.fetch_all(
            "SELECT role, content FROM messages WHERE conversation_id = ? "
            "ORDER BY timestamp ASC LIMIT ? OFFSET ?",
            (conversation_id, cutoff - already_summarized, already_summarized),
        )

        if not messages:
            return

        # Build the text to summarize
        text_parts = []
        for msg in messages:
            text_parts.append(f"{msg['role']}: {msg['content']}")
        conversation_text = "\n".join(text_parts)

        # Call LLM to summarize
        summary_response = await self.llm_provider.complete(
            messages=[
                {"role": "system", "content": SUMMARIZE_PROMPT},
                {"role": "user", "content": conversation_text},
            ]
        )

        summary_text = summary_response.content

        # Store the summary
        summary_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO conversation_summaries "
            "(id, conversation_id, start_message_idx, end_message_idx, summary) "
            "VALUES (?, ?, ?, ?, ?)",
            (summary_id, conversation_id, already_summarized, cutoff, summary_text),
        )

        # Embed the summary for vector search
        await self.vector_memory.store(
            text=summary_text,
            source_type="conversation_summary",
            source_id=summary_id,
        )

        logger.info(
            "Summarized messages %d-%d for conversation %s",
            already_summarized,
            cutoff,
            conversation_id,
        )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_summarizer.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/memory/summarizer.py tests/test_summarizer.py
git commit -m "feat: add conversation summarizer with LLM-driven summarization"
```

---

### Task 8: Memory Manager

**Files:**
- Create: `odigos/memory/manager.py`
- Create: `tests/test_memory_manager.py`

**Step 1: Write the failing test**

Create `tests/test_memory_manager.py`:

```python
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from odigos.db import Database
from odigos.memory.graph import EntityGraph
from odigos.memory.manager import MemoryManager
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.vectors import MemoryResult, VectorMemory
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
    embedder.embed.return_value = [0.1] * 1536
    return embedder


@pytest.fixture
async def vector_memory(db, mock_embedder):
    vm = VectorMemory(db=db, embedder=mock_embedder)
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
    return ConversationSummarizer(
        db=db, vector_memory=vector_memory, llm_provider=mock_provider
    )


@pytest.fixture
def manager(vector_memory, graph, resolver, summarizer):
    return MemoryManager(
        vector_memory=vector_memory,
        graph=graph,
        resolver=resolver,
        summarizer=summarizer,
    )


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

    async def test_recall_returns_formatted_context(self, manager, graph, vector_memory, mock_embedder):
        """After storing data, recall returns formatted memory context."""
        # Store some data
        await manager.store(
            conversation_id="conv-1",
            user_message="Alice works on the Odigos project",
            assistant_response="Got it!",
            extracted_entities=[
                {"name": "Alice", "type": "person", "relationship": "works_on", "detail": "Odigos project"},
            ],
        )

        context = await manager.recall("Alice")

        # Should contain some memory content (even if just vector results)
        # The exact format depends on what's stored
        assert isinstance(context, str)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_memory_manager.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement memory manager**

Create `odigos/memory/manager.py`:

```python
import logging

from odigos.memory.graph import EntityGraph
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.vectors import VectorMemory

logger = logging.getLogger(__name__)


class MemoryManager:
    """Unified recall/store interface for the agent core."""

    def __init__(
        self,
        vector_memory: VectorMemory,
        graph: EntityGraph,
        resolver: EntityResolver,
        summarizer: ConversationSummarizer,
    ) -> None:
        self.vector_memory = vector_memory
        self.graph = graph
        self.resolver = resolver
        self.summarizer = summarizer

    async def recall(self, query: str, limit: int = 5) -> str:
        """Recall relevant memories for the given query.

        Returns a formatted context string for injection into the prompt.
        """
        sections = []

        # 1. Vector search for relevant memories
        vector_results = await self.vector_memory.search(query, limit=limit)
        memory_lines = []
        for result in vector_results:
            if result.source_type != "entity_name":  # Skip entity name embeddings
                memory_lines.append(f"- {result.content_preview}")

        if memory_lines:
            sections.append("## Relevant memories\n" + "\n".join(memory_lines))

        # 2. Entity lookup
        entity_lines = []
        # Simple word-based entity search from the query
        words = [w for w in query.split() if len(w) > 2]
        seen_entities = set()
        for word in words:
            entities = await self.graph.find_entity(word)
            for entity in entities:
                if entity["id"] not in seen_entities:
                    seen_entities.add(entity["id"])
                    related = await self.graph.get_related(entity["id"])
                    related_names = [r["name"] for r in related[:3]]
                    line = f"- {entity['name']}: {entity['type']}"
                    if entity.get("summary"):
                        line += f", {entity['summary']}"
                    if related_names:
                        line += f" (related: {', '.join(related_names)})"
                    entity_lines.append(line)

        if entity_lines:
            sections.append("## Known entities\n" + "\n".join(entity_lines))

        return "\n\n".join(sections)

    async def store(
        self,
        conversation_id: str,
        user_message: str,
        assistant_response: str,
        extracted_entities: list[dict],
    ) -> None:
        """Process and store memories from a conversation turn.

        Args:
            conversation_id: The conversation this belongs to.
            user_message: The user's message text.
            assistant_response: The assistant's response text.
            extracted_entities: List of dicts with keys: name, type, relationship, detail.
        """
        # 1. Resolve and store entities
        for entity_data in extracted_entities:
            result = await self.resolver.resolve(
                name=entity_data["name"],
                entity_type=entity_data.get("type", "concept"),
                context=user_message,
            )

            # If entity has a relationship, create an edge
            if entity_data.get("relationship") and entity_data.get("detail"):
                # Find or create the target entity for the relationship
                detail = entity_data["detail"]
                target_result = await self.resolver.resolve(
                    name=detail,
                    entity_type="concept",
                    context=user_message,
                )
                await self.graph.create_edge(
                    source_id=result.entity_id,
                    relationship=entity_data["relationship"],
                    target_id=target_result.entity_id,
                )

        # 2. Embed the user message for semantic search
        await self.vector_memory.store(
            text=user_message,
            source_type="user_message",
            source_id=conversation_id,
        )

        # 3. Check if summarization is needed
        await self.summarizer.summarize_if_needed(conversation_id)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_memory_manager.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/memory/manager.py tests/test_memory_manager.py
git commit -m "feat: add memory manager as unified recall/store interface"
```

---

### Task 9: Upgrade Context Assembly

**Files:**
- Modify: `odigos/core/context.py` (inject memories + entity extraction instruction)
- Modify: `tests/test_core.py` (update context assembler tests)

**Step 1: Write the failing test**

Add to `tests/test_core.py`:

```python
class TestContextAssemblerWithMemory:
    async def test_injects_memories(self, db: Database):
        """Context includes memory section when memory manager has data."""
        mock_memory = AsyncMock()
        mock_memory.recall.return_value = (
            "## Relevant memories\n- Alice prefers morning meetings."
        )

        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20, memory_manager=mock_memory
        )
        messages = await assembler.build("conv-1", "When should we meet?")

        system_content = messages[0]["content"]
        assert "Relevant memories" in system_content
        assert "Alice prefers morning meetings" in system_content

    async def test_includes_entity_extraction_instruction(self, db: Database):
        """System prompt includes entity extraction instruction."""
        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20
        )
        messages = await assembler.build("conv-1", "Hello")

        system_content = messages[0]["content"]
        assert "<!--entities" in system_content

    async def test_no_memory_manager_still_works(self, db: Database):
        """Without memory manager, context assembler works as before."""
        assembler = ContextAssembler(
            db=db, agent_name="TestBot", history_limit=20
        )
        messages = await assembler.build("conv-1", "Hello")

        assert messages[0]["role"] == "system"
        assert messages[-1]["content"] == "Hello"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestContextAssemblerWithMemory -v`
Expected: FAIL (ContextAssembler doesn't accept memory_manager)

**Step 3: Upgrade context assembler**

Replace the full `odigos/core/context.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.db import Database

if TYPE_CHECKING:
    from odigos.memory.manager import MemoryManager

SYSTEM_PROMPT_TEMPLATE = """You are {agent_name}, a personal AI assistant.

You are helpful, direct, and concise. You remember past conversations and provide thoughtful responses.
When you don't know something, say so honestly rather than guessing."""

ENTITY_EXTRACTION_INSTRUCTION = """
After your response, on a new line, include extracted entities in this exact format:
<!--entities
[{{"name": "...", "type": "person|project|preference|concept", "relationship": "...", "detail": "..."}}]
-->
Only include entities if the conversation mentions specific people, projects, preferences, or important concepts.
If none are relevant, omit the block entirely."""


class ContextAssembler:
    """Builds the messages list for an LLM call from conversation history."""

    def __init__(
        self,
        db: Database,
        agent_name: str,
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.db = db
        self.agent_name = agent_name
        self.history_limit = history_limit
        self.memory_manager = memory_manager

    async def build(self, conversation_id: str, current_message: str) -> list[dict]:
        """Assemble the full messages list: system + memories + history + current."""
        messages: list[dict] = []

        # Build system prompt
        system_parts = [SYSTEM_PROMPT_TEMPLATE.format(agent_name=self.agent_name)]

        # Inject relevant memories
        if self.memory_manager:
            memory_context = await self.memory_manager.recall(current_message)
            if memory_context:
                system_parts.append(memory_context)

        # Add entity extraction instruction
        system_parts.append(ENTITY_EXTRACTION_INSTRUCTION)

        messages.append({"role": "system", "content": "\n\n".join(system_parts)})

        # Conversation history
        history = await self.db.fetch_all(
            "SELECT role, content FROM messages "
            "WHERE conversation_id = ? "
            "ORDER BY timestamp ASC "
            "LIMIT ?",
            (conversation_id, self.history_limit),
        )
        for row in history:
            messages.append({"role": row["role"], "content": row["content"]})

        # Current message
        messages.append({"role": "user", "content": current_message})

        return messages
```

Also update the import in `tests/test_core.py` to add `from unittest.mock import AsyncMock` if not already present.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: ALL PASS (both old and new tests)

**Step 5: Commit**

```bash
git add odigos/core/context.py tests/test_core.py
git commit -m "feat: upgrade context assembler with memory injection and entity extraction"
```

---

### Task 10: Upgrade Reflector for Entity Extraction

**Files:**
- Modify: `odigos/core/reflector.py` (parse entities, call memory manager)
- Add tests to: `tests/test_core.py`

**Step 1: Write the failing test**

Add to `tests/test_core.py`:

```python
class TestReflectorWithMemory:
    async def test_parses_entity_block(self, db: Database):
        """Reflector parses <!--entities--> block from response and strips it."""
        mock_memory = AsyncMock()
        reflector = Reflector(db=db, memory_manager=mock_memory)

        content_with_entities = (
            'Hello! I can help with that.\n\n'
            '<!--entities\n'
            '[{"name": "Alice", "type": "person", "relationship": "friend", "detail": "engineer"}]\n'
            '-->'
        )
        response = LLMResponse(
            content=content_with_entities,
            model="test/model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.001,
        )

        # Create conversation first
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-1", "test"),
        )

        await reflector.reflect("conv-1", response, user_message="I talked to Alice")

        # Memory manager should have been called with extracted entities
        mock_memory.store.assert_called_once()
        call_kwargs = mock_memory.store.call_args
        entities = call_kwargs[1]["extracted_entities"] if call_kwargs[1] else call_kwargs[0][3]
        assert len(entities) == 1
        assert entities[0]["name"] == "Alice"

        # Stored message should NOT contain the entities block
        msg = await db.fetch_one(
            "SELECT content FROM messages WHERE conversation_id = 'conv-1' AND role = 'assistant'"
        )
        assert "<!--entities" not in msg["content"]
        assert "Hello! I can help with that." in msg["content"]

    async def test_no_entity_block(self, db: Database):
        """Reflector works normally when no entity block is present."""
        mock_memory = AsyncMock()
        reflector = Reflector(db=db, memory_manager=mock_memory)

        response = LLMResponse(
            content="Just a normal response.",
            model="test/model",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )

        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-2", "test"),
        )

        await reflector.reflect("conv-2", response, user_message="Hello")

        # Memory manager called with empty entities
        mock_memory.store.assert_called_once()
        call_kwargs = mock_memory.store.call_args
        entities = call_kwargs[1]["extracted_entities"] if call_kwargs[1] else call_kwargs[0][3]
        assert entities == []

    async def test_reflector_backward_compatible(self, db: Database):
        """Reflector without memory_manager still works (Phase 0 compat)."""
        reflector = Reflector(db=db)
        response = LLMResponse(
            content="Hi there", model="m", tokens_in=1, tokens_out=1, cost_usd=0.0
        )

        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-3", "test"),
        )

        await reflector.reflect("conv-3", response)

        msg = await db.fetch_one(
            "SELECT content FROM messages WHERE conversation_id = 'conv-3'"
        )
        assert msg["content"] == "Hi there"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestReflectorWithMemory -v`
Expected: FAIL (Reflector doesn't accept memory_manager or user_message)

**Step 3: Upgrade reflector**

Replace `odigos/core/reflector.py`:

```python
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import TYPE_CHECKING

from odigos.db import Database
from odigos.providers.base import LLMResponse

if TYPE_CHECKING:
    from odigos.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

ENTITY_PATTERN = re.compile(
    r"<!--entities\s*\n(.*?)\n-->", re.DOTALL
)


class Reflector:
    """Evaluates results and stores learnings.

    Parses entity extraction blocks from LLM responses and passes them
    to the memory manager for storage and resolution.
    """

    def __init__(
        self,
        db: Database,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.db = db
        self.memory_manager = memory_manager

    async def reflect(
        self,
        conversation_id: str,
        response: LLMResponse,
        user_message: str | None = None,
    ) -> None:
        # Parse and strip entity block
        content = response.content
        entities = []
        match = ENTITY_PATTERN.search(content)
        if match:
            try:
                entities = json.loads(match.group(1))
            except (json.JSONDecodeError, IndexError):
                logger.warning("Failed to parse entity block from response")
            content = ENTITY_PATTERN.sub("", content).rstrip()

        # Store the clean assistant message
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, model_used, "
            "tokens_in, tokens_out, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                conversation_id,
                "assistant",
                content,
                response.model,
                response.tokens_in,
                response.tokens_out,
                response.cost_usd,
            ),
        )

        # Pass to memory manager if available
        if self.memory_manager and user_message is not None:
            await self.memory_manager.store(
                conversation_id=conversation_id,
                user_message=user_message,
                assistant_response=content,
                extracted_entities=entities,
            )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_core.py -v`
Expected: ALL PASS

Note: The existing `TestReflector.test_stores_message` test calls `reflector.reflect(conv_id, response)` without `user_message` -- this should still work because `user_message` defaults to `None` and the memory manager path is skipped when `memory_manager is None`.

**Step 5: Commit**

```bash
git add odigos/core/reflector.py tests/test_core.py
git commit -m "feat: upgrade reflector to parse entity blocks and call memory manager"
```

---

### Task 11: Wire Memory into Agent and Main

**Files:**
- Modify: `odigos/core/agent.py` (accept and pass memory_manager)
- Modify: `odigos/main.py` (initialize embedding provider, memory stack)
- Modify: `tests/test_core.py` (update agent test)

**Step 1: Write the failing test**

Add to `tests/test_core.py`:

```python
class TestAgentWithMemory:
    async def test_full_loop_with_memory(self, db: Database, mock_provider: AsyncMock):
        """Agent passes user_message to reflector when memory is wired."""
        mock_memory = AsyncMock()
        mock_memory.recall.return_value = ""

        agent = Agent(
            db=db,
            provider=mock_provider,
            agent_name="TestBot",
            history_limit=20,
            memory_manager=mock_memory,
        )
        message = _make_message("Hello agent")

        response = await agent.handle_message(message)
        assert response == "I'm Odigos, your assistant."

        # Verify memory_manager.store was called (via reflector)
        # Since reflector has memory_manager, it should call store
        mock_memory.store.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestAgentWithMemory -v`
Expected: FAIL (Agent doesn't accept memory_manager)

**Step 3: Upgrade agent.py**

Replace `odigos/core/agent.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.planner import Planner
from odigos.core.reflector import Reflector
from odigos.db import Database
from odigos.providers.base import LLMProvider

if TYPE_CHECKING:
    from odigos.memory.manager import MemoryManager


class Agent:
    """Main agent: receives messages, runs plan->execute->reflect loop."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        agent_name: str = "Odigos",
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.db = db
        self.planner = Planner()
        self.context_assembler = ContextAssembler(
            db, agent_name, history_limit, memory_manager=memory_manager
        )
        self.executor = Executor(provider, self.context_assembler)
        self.reflector = Reflector(db, memory_manager=memory_manager)

    async def handle_message(self, message: UniversalMessage) -> str:
        """Process an incoming message and return a response string."""
        # Find or create conversation
        conversation_id = await self._get_or_create_conversation(message)

        # Store user message
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (message.id, conversation_id, "user", message.content),
        )

        # Plan -> Execute -> Reflect
        await self.planner.plan(message.content)
        response = await self.executor.execute(conversation_id, message.content)
        await self.reflector.reflect(
            conversation_id, response, user_message=message.content
        )

        # Update conversation
        await self.db.execute(
            "UPDATE conversations SET last_message_at = datetime('now'), "
            "message_count = message_count + 2 WHERE id = ?",
            (conversation_id,),
        )

        return response.content

    async def _get_or_create_conversation(self, message: UniversalMessage) -> str:
        """Get existing conversation for this chat, or create a new one."""
        chat_id = message.metadata.get("chat_id", message.sender)
        lookup_id = f"{message.channel}:{chat_id}"

        existing = await self.db.fetch_one(
            "SELECT id FROM conversations WHERE id = ?", (lookup_id,)
        )
        if existing:
            return existing["id"]

        await self.db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (lookup_id, message.channel),
        )
        return lookup_id
```

**Step 4: Upgrade main.py**

Replace `odigos/main.py`:

```python
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from odigos.channels.telegram import TelegramChannel
from odigos.config import load_settings
from odigos.core.agent import Agent
from odigos.db import Database
from odigos.memory.graph import EntityGraph
from odigos.memory.manager import MemoryManager
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.vectors import VectorMemory
from odigos.providers.embeddings import EmbeddingProvider
from odigos.providers.openrouter import OpenRouterProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Module-level references for cleanup
_db: Database | None = None
_provider: OpenRouterProvider | None = None
_embedder: EmbeddingProvider | None = None
_telegram: TelegramChannel | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for FastAPI."""
    global _db, _provider, _embedder, _telegram

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    settings = load_settings(config_path)

    logger.info("Starting Odigos agent: %s", settings.agent.name)

    # Initialize database
    _db = Database(settings.database.path)
    await _db.initialize()
    logger.info("Database initialized at %s", settings.database.path)

    # Initialize LLM provider
    _provider = OpenRouterProvider(
        api_key=settings.openrouter_api_key,
        default_model=settings.openrouter.default_model,
        fallback_model=settings.openrouter.fallback_model,
        max_tokens=settings.openrouter.max_tokens,
        temperature=settings.openrouter.temperature,
    )

    # Initialize embedding provider
    _embedder = EmbeddingProvider(api_key=settings.openrouter_api_key)

    # Initialize memory stack
    vector_memory = VectorMemory(db=_db, embedder=_embedder)
    await vector_memory.initialize()

    graph = EntityGraph(db=_db)
    resolver = EntityResolver(graph=graph, vector_memory=vector_memory)
    summarizer = ConversationSummarizer(
        db=_db, vector_memory=vector_memory, llm_provider=_provider
    )
    memory_manager = MemoryManager(
        vector_memory=vector_memory,
        graph=graph,
        resolver=resolver,
        summarizer=summarizer,
    )
    logger.info("Memory system initialized")

    # Initialize agent
    agent = Agent(
        db=_db,
        provider=_provider,
        agent_name=settings.agent.name,
        memory_manager=memory_manager,
    )

    # Initialize Telegram channel
    _telegram = TelegramChannel(
        token=settings.telegram_bot_token,
        agent=agent,
        mode=settings.telegram.mode,
        webhook_url=settings.telegram.webhook_url,
    )
    await _telegram.start()
    logger.info("Telegram channel started in %s mode", settings.telegram.mode)

    logger.info("Odigos is ready.")

    yield

    # Shutdown
    logger.info("Shutting down Odigos...")
    if _telegram:
        await _telegram.stop()
    if _embedder:
        await _embedder.close()
    if _provider:
        await _provider.close()
    if _db:
        await _db.close()
    logger.info("Odigos stopped.")


app = FastAPI(title="Odigos", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "odigos"}


def main():
    import uvicorn

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    settings = load_settings(config_path)

    uvicorn.run(
        "odigos.main:app",
        host=settings.server.host,
        port=settings.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

**Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add odigos/core/agent.py odigos/main.py tests/test_core.py
git commit -m "feat: wire memory manager into agent, context, reflector, and main"
```

---

### Task 12: Final Verification and Lint

**Files:** All modified files

**Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: ALL tests PASS

**Step 2: Run linter**

Run: `uv run ruff check odigos/ tests/`

Fix any issues found (unused imports, formatting, etc.).

**Step 3: Run ruff format**

Run: `uv run ruff format odigos/ tests/`

**Step 4: Run tests again after lint fixes**

Run: `uv run pytest -v`
Expected: ALL PASS

**Step 5: Verify the app starts**

Run: `uv run odigos` (ctrl-C after startup confirms no import errors)

Expected: App starts, logs "Memory system initialized", "Odigos is ready."

**Step 6: Commit**

```bash
git add -A
git commit -m "chore: lint fixes and final verification for Phase 1 memory"
```
