# Phase 2c: Hybrid Search — SQLite Consolidation

**Date:** 2026-03-12
**Status:** Approved

## Decision

Replace ChromaDB with sqlite-vec + FTS5 to consolidate all storage into SQLite. This eliminates a redundant storage system and keeps the base agent minimal — external vector/graph DBs can be optional capabilities, not core dependencies.

Pre-release, no users, no data to migrate — clean swap.

## Schema

New migration `018_hybrid_search.sql` adds three structures:

### Vector table (sqlite-vec)

```sql
CREATE VIRTUAL TABLE memory_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[768]
);
```

### Metadata table

```sql
CREATE TABLE memory_entries (
    id TEXT PRIMARY KEY,
    content_preview TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    when_to_use TEXT DEFAULT '',
    memory_type TEXT DEFAULT 'general',
    created_at TEXT DEFAULT (datetime('now'))
);
```

### FTS5 virtual table (external content)

```sql
CREATE VIRTUAL TABLE memory_fts USING fts5(
    content_preview,
    when_to_use,
    content='memory_entries',
    content_rowid='rowid'
);
```

Three tables, one database file. `memory_vec` handles vector similarity, `memory_fts` handles keyword search, `memory_entries` holds actual data. All joined by the same text `id`. FTS5 uses external content configuration — no data duplication.

## VectorMemory Replacement

Same `VectorMemory` class interface, different backend.

### Store flow
1. Generate embedding via `self.embedder.embed()`
2. Single transaction:
   - INSERT into `memory_entries` (metadata)
   - INSERT into `memory_vec` (id + embedding blob)
   - INSERT into `memory_fts` (triggers FTS indexing)

### Search flow (vector-only)
1. Embed query via `self.embedder.embed_query()`
2. Query `memory_vec` with `vec_distance_cosine()` joined to `memory_entries`
3. Return `MemoryResult` list (same dataclass as today)

### Constructor change
- Takes `db: Database` instead of `persist_dir: str`
- `initialize()` becomes a no-op (schema handled by migration)
- Filtering via SQL `WHERE` on `memory_entries` join (replaces ChromaDB `where` clause)

## Hybrid Recall

`MemoryManager.recall()` becomes a hybrid search with Reciprocal Rank Fusion (RRF).

### Flow
1. Run two queries in parallel:
   - **Vector search:** embed query, top-20 nearest neighbors via `memory_vec`
   - **FTS5 search:** `MATCH` query with BM25 ranking, top-20
2. Merge with RRF: `score = sum(1 / (k + rank))` per result across both lists, `k=60`
3. Return top `limit` results by fused score
4. Entity graph lookup runs after (unchanged)

### Why RRF
Rank-based, not score-based — no normalization needed between cosine distances and BM25 scores. No tuning constants beyond `k`.

### Implementation
- New `_hybrid_search()` private method on `MemoryManager`
- New `search_fts()` method on `VectorMemory`
- `recall()` calls `_hybrid_search()` instead of `self.vector_memory.search()`
- `_is_duplicate()` stays vector-only (cosine distance threshold)

### FTS query preprocessing
Strip punctuation, collapse whitespace. Multi-word queries use individual terms (implicit OR).

## API

`GET /api/memory/search` gains optional `mode` param:
- `"hybrid"` (default) — vector + FTS merged via RRF
- `"vector"` — vector-only (current behavior)
- `"fts"` — keyword-only

Response shape unchanged, adds `score` field.

## Wiring (main.py)

- `VectorMemory(embedder=_embedder, db=_db)` replaces `VectorMemory(embedder=_embedder, persist_dir=...)`
- Remove `await vector_memory.initialize()`
- sqlite-vec extension loaded once in `Database.initialize()`
- All downstream consumers (MemoryManager, DocumentIngester, CorrectionsManager, EntityResolver) take same `VectorMemory` — no signature changes

## Dependency Changes

- Remove: `chromadb>=0.5.0`
- Add: `sqlite-vec>=0.1.0`
- Clean up `data/chroma/` references in `.dockerignore`, `install.sh`, docs

## Tests

- Rewrite `test_vector_memory.py` — same cases, in-memory SQLite with sqlite-vec
- New `test_hybrid_search.py` — RRF merging, FTS matching, mode selection
- Update fixtures in `test_memory_manager.py`, `test_memory_dedup.py`, `test_resolver.py`, `test_summarizer.py`

## What Doesn't Change

- `MemoryResult` dataclass
- `EntityGraph` (already SQLite)
- `MemoryManager.store()` flow
- `DocumentIngester` interface
- Dashboard / frontend
