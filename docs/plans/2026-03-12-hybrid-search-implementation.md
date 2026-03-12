# Phase 2c: Hybrid Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace ChromaDB with sqlite-vec + FTS5, giving the agent hybrid search (vector + keyword) in a single SQLite database.

**Architecture:** sqlite-vec extension loaded into the existing aiosqlite connection. Three new tables (memory_vec, memory_entries, memory_fts) replace the ChromaDB collection. Hybrid recall uses Reciprocal Rank Fusion to merge vector and FTS5 results.

**Tech Stack:** sqlite-vec, FTS5 (built into SQLite), aiosqlite, sentence-transformers (unchanged)

**Design doc:** `docs/plans/2026-03-12-hybrid-search-design.md`

---

### Task 1: Add sqlite-vec dependency and verify it loads

**Files:**
- Modify: `pyproject.toml:14` (swap chromadb for sqlite-vec)
- Modify: `odigos/db.py:38-43` (load sqlite-vec extension on init)

**Step 1: Update pyproject.toml**

In `pyproject.toml`, replace:
```
    "chromadb>=0.5.0",
```
with:
```
    "sqlite-vec>=0.1.6",
```

**Step 2: Install the new dependency**

Run: `uv sync`
Expected: Installs sqlite-vec, removes chromadb

**Step 3: Load sqlite-vec in Database.initialize()**

In `odigos/db.py`, modify the `initialize` method. After the connection is opened and before migrations, add sqlite-vec loading:

```python
async def initialize(self) -> None:
    """Open connection and run migrations."""
    self._conn = await aiosqlite.connect(self.db_path)
    self._conn.row_factory = aiosqlite.Row
    await self._conn.execute("PRAGMA journal_mode=WAL")
    await self._conn.execute("PRAGMA foreign_keys=ON")

    # Load sqlite-vec extension for vector search
    import sqlite_vec
    await self._conn.enable_load_extension(True)
    await self._conn.load_extension(sqlite_vec.loadable_path())
    await self._conn.enable_load_extension(False)

    await self.run_migrations()
```

**Step 4: Verify syntax**

Run: `node --check` is JS-only — for Python: `python -c "import odigos.db"`
Expected: No import errors

**Step 5: Commit**

```bash
git add pyproject.toml odigos/db.py
git commit -m "feat: replace chromadb dep with sqlite-vec, load extension in Database"
```

---

### Task 2: Write the migration

**Files:**
- Create: `migrations/018_hybrid_search.sql`

**Step 1: Write the migration file**

Create `migrations/018_hybrid_search.sql`:

```sql
-- Memory entries: metadata for stored memories (replaces ChromaDB metadatas)
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    content_preview TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    when_to_use TEXT DEFAULT '',
    memory_type TEXT DEFAULT 'general',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memory_entries_source_type ON memory_entries(source_type);
CREATE INDEX IF NOT EXISTS idx_memory_entries_source_id ON memory_entries(source_id);
CREATE INDEX IF NOT EXISTS idx_memory_entries_memory_type ON memory_entries(memory_type);

-- Vector table: sqlite-vec HNSW index for 768-d embeddings
CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[768]
);

-- FTS5 full-text index over content_preview and when_to_use
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content_preview,
    when_to_use,
    content='memory_entries',
    content_rowid='rowid'
);

-- Triggers to keep FTS5 in sync with memory_entries
CREATE TRIGGER IF NOT EXISTS memory_entries_ai AFTER INSERT ON memory_entries BEGIN
    INSERT INTO memory_fts(rowid, content_preview, when_to_use)
    VALUES (new.rowid, new.content_preview, new.when_to_use);
END;

CREATE TRIGGER IF NOT EXISTS memory_entries_ad AFTER DELETE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content_preview, when_to_use)
    VALUES ('delete', old.rowid, old.content_preview, old.when_to_use);
END;

CREATE TRIGGER IF NOT EXISTS memory_entries_au AFTER UPDATE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content_preview, when_to_use)
    VALUES ('delete', old.rowid, old.content_preview, old.when_to_use);
    INSERT INTO memory_fts(rowid, content_preview, when_to_use)
    VALUES (new.rowid, new.content_preview, new.when_to_use);
END;
```

**Step 2: Write a quick migration test**

Run: `python -c "
import asyncio, tempfile, os
from odigos.db import Database
async def test():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    db = Database(path, migrations_dir='migrations')
    await db.initialize()
    row = await db.fetch_one(\"SELECT name FROM sqlite_master WHERE name='memory_entries'\")
    assert row, 'memory_entries table not created'
    row = await db.fetch_one(\"SELECT name FROM sqlite_master WHERE name='memory_vec'\")
    assert row, 'memory_vec table not created'
    row = await db.fetch_one(\"SELECT name FROM sqlite_master WHERE name='memory_fts'\")
    assert row, 'memory_fts table not created'
    await db.close()
    os.unlink(path)
    print('Migration OK')
asyncio.run(test())
"`
Expected: `Migration OK`

**Step 3: Commit**

```bash
git add migrations/018_hybrid_search.sql
git commit -m "feat: add migration 018 for memory_entries, memory_vec, memory_fts tables"
```

---

### Task 3: Rewrite VectorMemory to use sqlite-vec

**Files:**
- Modify: `odigos/memory/vectors.py` (full rewrite)
- Test: `tests/test_vectors.py` (update fixtures)
- Test: `tests/test_vector_memory.py` (update fixtures)

**Step 1: Write the failing tests**

Rewrite `tests/test_vectors.py` — same test cases, sqlite-vec backend:

```python
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

    async def test_count(self, vector_memory):
        """Count returns the number of stored vectors."""
        assert await vector_memory.count() == 0
        await vector_memory.store("text", "test", "doc-1")
        assert await vector_memory.count() == 1

    async def test_delete_by_source(self, vector_memory):
        """Delete removes entries by source_type and source_id."""
        await vector_memory.store("chunk 1", "document_chunk", "doc-1")
        await vector_memory.store("chunk 2", "document_chunk", "doc-1")
        await vector_memory.store("other", "user_message", "conv-1")
        assert await vector_memory.count() == 3

        await vector_memory.delete_by_source("document_chunk", "doc-1")
        assert await vector_memory.count() == 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_vectors.py -v`
Expected: FAIL — VectorMemory constructor signature changed

**Step 3: Rewrite VectorMemory**

Replace `odigos/memory/vectors.py` entirely:

```python
from __future__ import annotations

import logging
import struct
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)


@dataclass
class MemoryResult:
    content_preview: str
    source_type: str
    source_id: str
    distance: float
    when_to_use: str = ""
    memory_type: str = "general"


def _serialize_f32(vec: list[float]) -> bytes:
    """Serialize a list of floats to a compact binary format for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


class VectorMemory:
    """SQLite-backed vector store using sqlite-vec for semantic memory search."""

    def __init__(self, embedder: EmbeddingProvider, db: Database) -> None:
        self.embedder = embedder
        self.db = db

    async def initialize(self) -> None:
        """No-op — schema is handled by migrations."""
        pass

    async def store(
        self,
        text: str,
        source_type: str,
        source_id: str,
        when_to_use: str = "",
        memory_type: str = "general",
    ) -> str:
        """Embed text and store in SQLite. Returns the vector ID."""
        embed_input = when_to_use if when_to_use else text
        vector = await self.embedder.embed(embed_input)
        vec_id = str(uuid.uuid4())

        await self.db.execute_in_transaction([
            (
                "INSERT INTO memory_entries (id, content_preview, source_type, source_id, when_to_use, memory_type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (vec_id, text[:500], source_type, source_id, when_to_use, memory_type),
            ),
            (
                "INSERT INTO memory_vec (id, embedding) VALUES (?, ?)",
                (vec_id, _serialize_f32(vector)),
            ),
        ])
        return vec_id

    async def search(
        self,
        query: str,
        limit: int = 5,
        source_type: str | None = None,
        memory_type: str | None = None,
    ) -> list[MemoryResult]:
        """Embed query and find nearest neighbors via sqlite-vec."""
        count = await self.count()
        if count == 0:
            return []

        vector = await self.embedder.embed_query(query)

        where_clauses = []
        params: list = []
        if source_type:
            where_clauses.append("e.source_type = ?")
            params.append(source_type)
        if memory_type:
            where_clauses.append("e.memory_type = ?")
            params.append(memory_type)

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        sql = f"""
            SELECT e.*, v.distance
            FROM memory_vec v
            JOIN memory_entries e ON e.id = v.id
            {where_sql}
            ORDER BY v.distance
            LIMIT ?
        """
        # sqlite-vec KNN query: pass the query vector as the embedding match param
        # The vec0 virtual table uses a special query syntax
        knn_sql = f"""
            SELECT e.id, e.content_preview, e.source_type, e.source_id,
                   e.when_to_use, e.memory_type, v.distance
            FROM (
                SELECT id, distance
                FROM memory_vec
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            ) v
            JOIN memory_entries e ON e.id = v.id
            {where_sql}
        """
        all_params = [_serialize_f32(vector), min(limit * 3, count)] + params

        rows = await self.db.fetch_all(knn_sql, tuple(all_params))

        results = []
        for row in rows[:limit]:
            results.append(
                MemoryResult(
                    content_preview=row["content_preview"],
                    source_type=row["source_type"],
                    source_id=row["source_id"],
                    distance=row["distance"],
                    when_to_use=row.get("when_to_use", ""),
                    memory_type=row.get("memory_type", "general"),
                )
            )
        return results

    async def search_fts(self, query: str, limit: int = 20) -> list[MemoryResult]:
        """Full-text keyword search via FTS5."""
        # Clean query for FTS5: strip special chars, split into terms
        clean_terms = []
        for word in query.split():
            cleaned = "".join(c for c in word if c.isalnum())
            if cleaned:
                clean_terms.append(cleaned)

        if not clean_terms:
            return []

        fts_query = " OR ".join(clean_terms)

        rows = await self.db.fetch_all(
            """
            SELECT e.id, e.content_preview, e.source_type, e.source_id,
                   e.when_to_use, e.memory_type,
                   rank AS distance
            FROM memory_fts
            JOIN memory_entries e ON e.rowid = memory_fts.rowid
            WHERE memory_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, limit),
        )

        return [
            MemoryResult(
                content_preview=row["content_preview"],
                source_type=row["source_type"],
                source_id=row["source_id"],
                distance=row["distance"],
                when_to_use=row.get("when_to_use", ""),
                memory_type=row.get("memory_type", "general"),
            )
            for row in rows
        ]

    async def count(self) -> int:
        """Return total number of vectors stored."""
        row = await self.db.fetch_one("SELECT COUNT(*) as cnt FROM memory_entries")
        return row["cnt"] if row else 0

    async def delete_by_source(self, source_type: str, source_id: str) -> None:
        """Delete all entries matching source_type and source_id."""
        # Get IDs to delete from vec table too
        rows = await self.db.fetch_all(
            "SELECT id FROM memory_entries WHERE source_type = ? AND source_id = ?",
            (source_type, source_id),
        )
        if not rows:
            return

        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" * len(ids))

        await self.db.execute_in_transaction([
            (f"DELETE FROM memory_vec WHERE id IN ({placeholders})", tuple(ids)),
            (
                "DELETE FROM memory_entries WHERE source_type = ? AND source_id = ?",
                (source_type, source_id),
            ),
        ])
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_vectors.py -v`
Expected: All PASS

**Step 5: Update test_vector_memory.py fixtures**

In `tests/test_vector_memory.py`, update the fixture:

Replace:
```python
@pytest.fixture
async def vector_memory(tmp_path, mock_embedder):
    vm = VectorMemory(embedder=mock_embedder, persist_dir=str(tmp_path / "chroma"))
    await vm.initialize()
    return vm
```
With:
```python
@pytest.fixture
async def db(tmp_db_path):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def vector_memory(db, mock_embedder):
    return VectorMemory(embedder=mock_embedder, db=db)
```

Add import: `from odigos.db import Database`

**Step 6: Run test_vector_memory.py**

Run: `pytest tests/test_vector_memory.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add odigos/memory/vectors.py tests/test_vectors.py tests/test_vector_memory.py
git commit -m "feat: rewrite VectorMemory to use sqlite-vec, add FTS5 search method"
```

---

### Task 4: Implement hybrid recall in MemoryManager

**Files:**
- Modify: `odigos/memory/manager.py:29-67` (recall method + new _hybrid_search)
- Create: `tests/test_hybrid_search.py`

**Step 1: Write the failing tests**

Create `tests/test_hybrid_search.py`:

```python
from unittest.mock import AsyncMock

import pytest

from odigos.db import Database
from odigos.memory.graph import EntityGraph
from odigos.memory.manager import MemoryManager
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.vectors import VectorMemory, MemoryResult
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
    counter = {"n": 0}
    cache = {}

    def make_embed(text):
        if text in cache:
            return list(cache[text])
        counter["n"] += 1
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


class TestHybridSearch:
    async def test_hybrid_search_returns_results(self, manager, vector_memory):
        """Hybrid search finds memories via both vector and keyword paths."""
        await vector_memory.store(
            text="Python is great for data science",
            source_type="user_message",
            source_id="conv-1",
        )
        results = await manager._hybrid_search("Python data science", limit=5)
        assert len(results) >= 1

    async def test_hybrid_search_empty(self, manager):
        """Hybrid search on empty memory returns empty list."""
        results = await manager._hybrid_search("anything", limit=5)
        assert results == []

    async def test_hybrid_search_deduplicates(self, manager, vector_memory):
        """Results appearing in both vector and FTS are not duplicated."""
        await vector_memory.store(
            text="The quick brown fox jumps",
            source_type="user_message",
            source_id="conv-1",
        )
        results = await manager._hybrid_search("quick brown fox", limit=10)
        ids = [r.source_id for r in results]
        # Same memory should not appear twice
        assert len(ids) == len(set(ids)) or len(results) == 1

    async def test_recall_uses_hybrid(self, manager, vector_memory):
        """recall() uses hybrid search internally."""
        await vector_memory.store(
            text="User prefers dark mode",
            source_type="user_message",
            source_id="conv-1",
        )
        context = await manager.recall("dark mode preference")
        assert "dark mode" in context
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hybrid_search.py -v`
Expected: FAIL — `_hybrid_search` method doesn't exist

**Step 3: Implement hybrid recall**

In `odigos/memory/manager.py`, add `_hybrid_search` and update `recall`:

```python
async def _hybrid_search(
    self, query: str, limit: int = 5, k: int = 60
) -> list:
    """Run vector + FTS5 search and merge via Reciprocal Rank Fusion."""
    from odigos.memory.vectors import MemoryResult

    # Run both searches (over-fetch for better RRF merging)
    fetch_limit = limit * 4
    vector_results = await self.vector_memory.search(query, limit=fetch_limit)
    fts_results = await self.vector_memory.search_fts(query, limit=fetch_limit)

    # RRF: score = sum(1 / (k + rank)) across lists
    scores: dict[str, float] = {}
    result_map: dict[str, MemoryResult] = {}

    for rank, r in enumerate(vector_results):
        key = f"{r.source_type}:{r.source_id}:{r.content_preview[:100]}"
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        result_map[key] = r

    for rank, r in enumerate(fts_results):
        key = f"{r.source_type}:{r.source_id}:{r.content_preview[:100]}"
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        if key not in result_map:
            result_map[key] = r

    # Sort by fused score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [result_map[key] for key, _score in ranked[:limit]]
```

Update `recall()` to call `_hybrid_search` instead of `self.vector_memory.search`:

```python
async def recall(self, query: str, limit: int = 5) -> str:
    """Recall relevant memories for the given query.

    Returns a formatted context string for injection into the prompt.
    """
    sections = []

    # 1. Hybrid search (vector + FTS5 with RRF)
    hybrid_results = await self._hybrid_search(query, limit=limit)
    memory_lines = []
    for result in hybrid_results:
        if result.source_type != "entity_name":
            memory_lines.append(f"- {result.content_preview}")

    if memory_lines:
        sections.append("## Relevant memories\n" + "\n".join(memory_lines))

    # 2. Entity lookup (unchanged)
    entity_lines = []
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hybrid_search.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add odigos/memory/manager.py tests/test_hybrid_search.py
git commit -m "feat: implement hybrid recall with RRF merging (vector + FTS5)"
```

---

### Task 5: Update downstream consumers and fixtures

**Files:**
- Modify: `odigos/main.py:148-150` (VectorMemory wiring)
- Modify: `odigos/memory/ingester.py:83-86` (delete uses new method)
- Modify: `tests/test_memory_manager.py:31-33` (fixture)
- Modify: `tests/test_memory_dedup.py:45-47` (fixture)
- Modify: `tests/test_resolver.py:33-35` (fixture)
- Modify: `tests/test_summarizer.py:29-31` (fixture)

**Step 1: Update main.py VectorMemory wiring**

In `odigos/main.py`, replace lines 148-150:

```python
    from pathlib import Path
    vector_memory = VectorMemory(embedder=_embedder, persist_dir=str(Path(settings.database.path).parent / "chroma"))
    await vector_memory.initialize()
```

With:

```python
    vector_memory = VectorMemory(embedder=_embedder, db=_db)
```

Also add `app.state.vector_memory = vector_memory` near the other `app.state` assignments (around line 435) if not already present.

**Step 2: Update DocumentIngester.delete()**

In `odigos/memory/ingester.py`, replace lines 82-86:

```python
        # Single query to delete all chunks
        await self.db.execute(
            "DELETE FROM memory_vectors WHERE source_type = 'document_chunk' AND source_id = ?",
            (document_id,),
        )
```

With:

```python
        await self.vector_memory.delete_by_source("document_chunk", document_id)
```

**Step 3: Update all test fixtures**

In every test file that creates a VectorMemory, replace the fixture pattern:

Old pattern:
```python
@pytest.fixture
async def vector_memory(tmp_path, mock_embedder):
    vm = VectorMemory(embedder=mock_embedder, persist_dir=str(tmp_path / "chroma"))
    await vm.initialize()
    return vm
```

New pattern:
```python
@pytest.fixture
def vector_memory(db, mock_embedder):
    return VectorMemory(embedder=mock_embedder, db=db)
```

Files to update:
- `tests/test_memory_manager.py` — already has `db` fixture, just update `vector_memory`
- `tests/test_memory_dedup.py` — already has `db` fixture, just update `vector_memory`
- `tests/test_resolver.py` — already has `db` fixture, just update `vector_memory`
- `tests/test_summarizer.py` — already has `db` fixture, just update `vector_memory`

**Step 4: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add odigos/main.py odigos/memory/ingester.py tests/test_memory_manager.py tests/test_memory_dedup.py tests/test_resolver.py tests/test_summarizer.py
git commit -m "feat: wire sqlite-vec VectorMemory into main and update all test fixtures"
```

---

### Task 6: Update the API endpoint

**Files:**
- Modify: `odigos/api/memory.py:25-43` (add mode param)

**Step 1: Update the search endpoint**

Replace the `/search` endpoint in `odigos/api/memory.py`:

```python
@router.get("/search")
async def search_memory(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    mode: str = Query(default="hybrid", pattern="^(hybrid|vector|fts)$"),
    vector_memory: VectorMemory = Depends(get_vector_memory),
):
    """Search over memory. Modes: hybrid (default), vector, fts."""
    if mode == "fts":
        results = await vector_memory.search_fts(q, limit=limit)
    elif mode == "vector":
        results = await vector_memory.search(q, limit=limit)
    else:
        # hybrid — need MemoryManager for RRF, but for API we do inline RRF
        vector_results = await vector_memory.search(q, limit=limit * 3)
        fts_results = await vector_memory.search_fts(q, limit=limit * 3)

        scores: dict[str, float] = {}
        result_map = {}
        k = 60
        for rank, r in enumerate(vector_results):
            key = f"{r.source_type}:{r.source_id}:{r.content_preview[:100]}"
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
            result_map[key] = r
        for rank, r in enumerate(fts_results):
            key = f"{r.source_type}:{r.source_id}:{r.content_preview[:100]}"
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
            if key not in result_map:
                result_map[key] = r

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        results = [result_map[key] for key, _ in ranked[:limit]]

    return {
        "results": [
            {
                "content_preview": r.content_preview,
                "source_type": r.source_type,
                "source_id": r.source_id,
                "distance": r.distance,
                "score": getattr(r, 'score', r.distance),
            }
            for r in results
        ]
    }
```

**Step 2: Verify syntax**

Run: `python -c "import odigos.api.memory"`
Expected: No errors

**Step 3: Commit**

```bash
git add odigos/api/memory.py
git commit -m "feat: add hybrid/vector/fts mode param to /api/memory/search"
```

---

### Task 7: Remove ChromaDB references and clean up

**Files:**
- Modify: `Dockerfile:36` (remove data/chroma mkdir)
- Modify: `install.sh:32` (remove data/chroma mkdir)
- Modify: `.dockerignore:12` (remove data/chroma)

**Step 1: Clean up Dockerfile**

In `Dockerfile`, change line 36:
```
RUN mkdir -p /app/data /app/data/plugins /app/data/chroma
```
To:
```
RUN mkdir -p /app/data /app/data/plugins
```

**Step 2: Clean up install.sh**

In `install.sh`, change line 32:
```
mkdir -p data data/plugins data/chroma skills plugins
```
To:
```
mkdir -p data data/plugins skills plugins
```

**Step 3: Clean up .dockerignore**

Remove the `data/chroma` line from `.dockerignore`.

**Step 4: Verify no remaining chromadb references**

Run: `grep -ri "chromadb\|chroma" --include="*.py" --include="*.toml" --include="*.yaml" --include="*.sh" --include="*.md" odigos/ tests/ pyproject.toml Dockerfile install.sh .dockerignore`

Expected: No matches (except possibly docs/plans which are fine)

**Step 5: Commit**

```bash
git add Dockerfile install.sh .dockerignore
git commit -m "chore: remove all ChromaDB references from Docker and install files"
```

---

### Task 8: Run full test suite and verify

**Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests pass (65+ existing + new hybrid tests)

**Step 2: Verify the app starts**

Run: `python -c "from odigos.main import app; print('App imports OK')"`
Expected: `App imports OK`

**Step 3: Final commit if any fixes were needed**

Only if previous steps required fixes. Otherwise, the implementation is complete.

---

## Summary of Changes

| File | Action |
|------|--------|
| `pyproject.toml` | Replace chromadb with sqlite-vec |
| `odigos/db.py` | Load sqlite-vec extension on init |
| `migrations/018_hybrid_search.sql` | New: memory_entries, memory_vec, memory_fts tables |
| `odigos/memory/vectors.py` | Rewrite: sqlite-vec backend with FTS5 search |
| `odigos/memory/manager.py` | Add _hybrid_search with RRF, update recall() |
| `odigos/memory/ingester.py` | Use delete_by_source instead of raw SQL |
| `odigos/api/memory.py` | Add mode param (hybrid/vector/fts) |
| `odigos/main.py` | Simplify VectorMemory wiring |
| `Dockerfile` | Remove data/chroma |
| `install.sh` | Remove data/chroma |
| `.dockerignore` | Remove data/chroma |
| `tests/test_vectors.py` | Rewrite for sqlite-vec |
| `tests/test_vector_memory.py` | Update fixtures |
| `tests/test_hybrid_search.py` | New: RRF and hybrid tests |
| `tests/test_memory_manager.py` | Update fixtures |
| `tests/test_memory_dedup.py` | Update fixtures |
| `tests/test_resolver.py` | Update fixtures |
| `tests/test_summarizer.py` | Update fixtures |
