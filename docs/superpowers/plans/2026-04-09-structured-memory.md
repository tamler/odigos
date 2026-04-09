# Structured Memory System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat vector store (`memory_entries`) with a structured memory system where every memory is typed, keyword-tagged, linked, and evolvable — based on A-MEM's Zettelkasten architecture.

**Architecture:** New `memories` table with 9 types replaces `memory_entries` + `user_facts`. MemoryStore handles classification + embedding + linking on write. MemoryRecall handles typed search + RRF + link expansion on read. MemoryEvolution runs in heartbeat to refine and consolidate memories. EntityGraph stays separate, bridged via entity-type memories.

**Tech Stack:** Python 3.12, aiosqlite, sqlite-vec, sentence-transformers, tiktoken, cross-encoder/ms-marco-MiniLM-L-6-v2

**Spec:** `docs/superpowers/specs/2026-04-09-structured-memory-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `odigos/memory/store.py` | MemoryStore — classify, embed, dedup, link on write |
| `odigos/memory/recall.py` | MemoryRecall — typed search, RRF, recency, link expansion |
| `odigos/memory/evolution.py` | MemoryEvolution — heartbeat evolution + consolidation |
| `odigos/memory/classifier.py` | Classify content into memory_type + keywords + tags + context |
| `data/prompts/memory_classify.md` | Classification prompt |
| `data/prompts/memory_link.md` | Link relationship judgment prompt |
| `data/prompts/memory_evolve.md` | Evolution decision prompt |
| `data/prompts/memory_consolidate.md` | High-connectivity synthesis prompt |
| `tests/test_memory_store.py` | Store pipeline tests |
| `tests/test_memory_recall.py` | Recall pipeline tests |
| `tests/test_memory_evolution.py` | Evolution tests |
| `tests/test_memory_classifier.py` | Classifier tests |
| `migrations/006_structured_memory.sql` | Schema migration |

### Modified Files

| File | Change |
|------|--------|
| `schema.sql` | Drop old tables, create memories/memory_links/evolution_queue |
| `odigos/memory/manager.py` | Use MemoryStore + MemoryRecall instead of VectorMemory |
| `odigos/memory/corrections.py` | Also store corrections as type=correction memories |
| `odigos/memory/summarizer.py` | Store summaries via MemoryStore |
| `odigos/memory/ingester.py` | Store chunks via MemoryStore |
| `odigos/memory/resolver.py` | Use MemoryStore for entity name search |
| `odigos/core/context.py` | Update memory_index counts for new table |
| `odigos/core/heartbeat/orchestrator.py` | Add memory evolution phase |
| `odigos/bootstrap.py` | Create and wire MemoryStore, MemoryRecall, MemoryEvolution |

### Removed Files

| File | Reason |
|------|--------|
| `odigos/memory/vectors.py` | Replaced by store.py + recall.py |

---

### Task 1: Schema Migration

**Files:**
- Modify: `schema.sql`
- Create: `migrations/006_structured_memory.sql`
- Create: `tests/test_memory_store.py` (schema portion)

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_store.py`:

```python
"""Tests for structured memory system."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


class TestSchema:
    async def test_memories_table_exists(self, db):
        mem_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO memories (id, content, memory_type, source_type, source_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (mem_id, "User prefers dark mode", "preference", "conversation", "conv-1"),
        )
        row = await db.fetch_one("SELECT * FROM memories WHERE id = ?", (mem_id,))
        assert row is not None
        assert row["memory_type"] == "preference"
        assert row["status"] == "active"
        assert row["confidence"] == 0.8

    async def test_memory_links_table_exists(self, db):
        m1 = str(uuid.uuid4())
        m2 = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO memories (id, content, memory_type, source_type, source_id) VALUES (?, ?, ?, ?, ?)",
            (m1, "Fact 1", "fact", "conversation", "c1"),
        )
        await db.execute(
            "INSERT INTO memories (id, content, memory_type, source_type, source_id) VALUES (?, ?, ?, ?, ?)",
            (m2, "Fact 2", "fact", "conversation", "c1"),
        )
        await db.execute(
            "INSERT INTO memory_links (source_note_id, target_note_id, relationship) VALUES (?, ?, ?)",
            (m1, m2, "supports"),
        )
        row = await db.fetch_one(
            "SELECT * FROM memory_links WHERE source_note_id = ?", (m1,)
        )
        assert row is not None
        assert row["relationship"] == "supports"

    async def test_evolution_queue_table_exists(self, db):
        m1 = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO memories (id, content, memory_type, source_type, source_id) VALUES (?, ?, ?, ?, ?)",
            (m1, "Old fact", "fact", "conversation", "c1"),
        )
        await db.execute(
            "INSERT INTO evolution_queue (existing_memory_id, new_content, reason) VALUES (?, ?, ?)",
            (m1, "Updated fact", "richer_content"),
        )
        row = await db.fetch_one("SELECT * FROM evolution_queue WHERE existing_memory_id = ?", (m1,))
        assert row is not None
        assert row["reason"] == "richer_content"

    async def test_old_tables_removed(self, db):
        """memory_entries and user_facts tables should not exist."""
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_entries'"
        )
        assert row is None
        row2 = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_facts'"
        )
        assert row2 is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_store.py::TestSchema -x -q`
Expected: FAIL — tables don't exist.

- [ ] **Step 3: Update schema.sql**

Remove the following table definitions from schema.sql:
- `memory_entries` table + its triggers
- `memory_vec` virtual table (the old one referencing memory_entries)
- `memory_fts` virtual table (the old one referencing memory_entries)
- `user_facts` table

Add new tables at the end of schema.sql:

```sql
-- Structured memories (replaces memory_entries + user_facts)
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    keywords_json TEXT DEFAULT '[]',
    tags_json TEXT DEFAULT '[]',
    context_description TEXT,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    conversation_id TEXT,
    confidence REAL DEFAULT 0.8,
    status TEXT DEFAULT 'active',
    superseded_by TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_memories_conversation ON memories(conversation_id);

-- Bidirectional memory links
CREATE TABLE IF NOT EXISTS memory_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_note_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
    target_note_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL,
    strength REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_note_id, target_note_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_note_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(target_note_id);

-- Evolution queue (deferred memory refinement)
CREATE TABLE IF NOT EXISTS evolution_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    existing_memory_id TEXT REFERENCES memories(id),
    new_content TEXT NOT NULL,
    new_source_id TEXT,
    reason TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    processed_at TEXT
);

-- Vector embeddings for memories
CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[768]
);

-- Full-text search for memories
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content, context_description, keywords_json,
    content='memories', content_rowid='rowid'
);

-- FTS sync triggers
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memory_fts(rowid, content, context_description, keywords_json)
    VALUES (new.rowid, new.content, new.context_description, new.keywords_json);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, context_description, keywords_json)
    VALUES ('delete', old.rowid, old.content, old.context_description, old.keywords_json);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, context_description, keywords_json)
    VALUES ('delete', old.rowid, old.content, old.context_description, old.keywords_json);
    INSERT INTO memory_fts(rowid, content, context_description, keywords_json)
    VALUES (new.rowid, new.content, new.context_description, new.keywords_json);
END;
```

- [ ] **Step 4: Create migration**

Create `migrations/006_structured_memory.sql`:

```sql
-- Drop old memory tables
DROP TABLE IF EXISTS memory_entries;
DROP TABLE IF EXISTS user_facts;

-- Note: memory_vec and memory_fts are virtual tables that reference
-- memory_entries. They need to be recreated, but virtual tables can't
-- be dropped with IF EXISTS in all SQLite builds. The schema.sql
-- CREATE IF NOT EXISTS handles fresh DBs. For existing DBs, we
-- recreate them here.

-- Structured memories
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    keywords_json TEXT DEFAULT '[]',
    tags_json TEXT DEFAULT '[]',
    context_description TEXT,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    conversation_id TEXT,
    confidence REAL DEFAULT 0.8,
    status TEXT DEFAULT 'active',
    superseded_by TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_memories_conversation ON memories(conversation_id);

-- Memory links
CREATE TABLE IF NOT EXISTS memory_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_note_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
    target_note_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL,
    strength REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_note_id, target_note_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_note_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(target_note_id);

-- Evolution queue
CREATE TABLE IF NOT EXISTS evolution_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    existing_memory_id TEXT REFERENCES memories(id),
    new_content TEXT NOT NULL,
    new_source_id TEXT,
    reason TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    processed_at TEXT
);
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_store.py::TestSchema -x -q`
Expected: PASS (4 tests). Note: the `test_old_tables_removed` test may need adjustment depending on whether the migration fully removes old tables on fresh DBs.

- [ ] **Step 6: Commit**

```bash
git add schema.sql migrations/006_structured_memory.sql tests/test_memory_store.py
git commit -m "feat: add structured memory schema — memories, memory_links, evolution_queue"
```

---

### Task 2: Memory Classifier

**Files:**
- Create: `odigos/memory/classifier.py`
- Create: `data/prompts/memory_classify.md`
- Create: `tests/test_memory_classifier.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_classifier.py`:

```python
"""Tests for memory content classifier."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from odigos.memory.classifier import MemoryClassifier, ClassificationResult
from odigos.providers.base import LLMResponse


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=50, tokens_out=100, cost_usd=0.001,
    )


class TestClassifier:
    async def test_classifies_preference(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "memory_type": "preference",
            "keywords": ["scheduling", "morning"],
            "tags": ["user-profile"],
            "context_description": "User dislikes early morning meetings.",
        })))

        classifier = MemoryClassifier(llm_client=mock_llm, prompts_dir="data/prompts")
        result = await classifier.classify("Don't schedule meetings before 10am")

        assert result.memory_type == "preference"
        assert "scheduling" in result.keywords
        assert result.context_description is not None

    async def test_classifies_entity(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "memory_type": "entity",
            "keywords": ["Rachel", "tester", "Kimi K2"],
            "tags": ["team"],
            "context_description": "Rachel is a tester who uses Kimi K2.",
        })))

        classifier = MemoryClassifier(llm_client=mock_llm, prompts_dir="data/prompts")
        result = await classifier.classify("Rachel is a tester, she uses Kimi K2")

        assert result.memory_type == "entity"
        assert "Rachel" in result.keywords

    async def test_fallback_on_parse_failure(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response("not valid json"))

        classifier = MemoryClassifier(llm_client=mock_llm, prompts_dir="data/prompts")
        result = await classifier.classify("Some random content")

        assert result.memory_type == "general"
        assert result.context_description == "Some random content"

    async def test_bulk_classify_returns_shared_metadata(self):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "memory_type": "general",
            "keywords": ["deployment", "docker"],
            "tags": ["infrastructure"],
            "context_description": "Document about Docker deployment.",
        })))

        classifier = MemoryClassifier(llm_client=mock_llm, prompts_dir="data/prompts")
        result = await classifier.classify_document(
            filename="deploy-guide.md",
            first_chunk="This guide covers Docker deployment...",
        )

        assert result.memory_type == "general"
        assert "docker" in [k.lower() for k in result.keywords]
        # Only 1 LLM call for the whole document
        assert mock_llm.complete.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_classifier.py -x -q`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create the classification prompt**

Create `data/prompts/memory_classify.md`:

```markdown
You are a memory classification system. Classify the following content into a structured memory record.

## Memory Types

- **fact**: A verifiable statement not tied to a specific named entity. Example: "Meetings are at 10am"
- **preference**: What the user wants, likes, or dislikes. Example: "Prefers concise responses"
- **task**: Something to do or track. Example: "Follow up on email by Friday"
- **idea**: Speculative, not yet validated. Example: "Could automate the weekly report"
- **entity**: About a named person, project, tool, or organization. Example: "Rachel is a tester using Kimi K2"
- **experience**: A learned lesson from tool usage or past interactions. Example: "Search broadly first, then narrow"
- **correction**: User feedback correcting agent behavior. Example: "Don't use formal tone"
- **summary**: Distilled content from a conversation or document.
- **general**: Anything that doesn't fit the above categories.

## Type Disambiguation

- If content is *about* a named entity (person, project, tool, organization): use `entity`
- If content is a standalone verifiable statement not tied to a specific entity: use `fact`
- If content expresses what the user wants/likes/dislikes: use `preference` (not `fact`)
- Example: "The project lead is Rachel" -> `entity`. "Meetings are at 10am" -> `fact`.

## Output

Return valid JSON only, no markdown fences:

{{"memory_type": "preference", "keywords": ["scheduling", "morning", "meetings"], "tags": ["user-profile", "time-preferences"], "context_description": "User prefers not to have meetings scheduled before 10am, especially on Mondays."}}

## Rules

- keywords: 3-5 key concepts from the content
- tags: 1-3 categorical labels (e.g., "user-profile", "work-habits", "infrastructure")
- context_description: 1-2 sentence semantic summary that adds context beyond the raw content

## Content to Classify

{content}
```

- [ ] **Step 4: Implement classifier.py**

Create `odigos/memory/classifier.py`:

```python
"""Classify content into structured memory types."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    memory_type: str = "general"
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    context_description: str = ""


class MemoryClassifier:
    """Classify content into memory_type + keywords + tags + context."""

    VALID_TYPES = {
        "fact", "preference", "task", "idea", "entity",
        "experience", "correction", "summary", "general",
    }

    def __init__(self, llm_client, prompts_dir: str = "data/prompts") -> None:
        self._llm = llm_client
        self._prompts_dir = Path(prompts_dir)

    async def classify(self, content: str) -> ClassificationResult:
        """Classify a single piece of content."""
        prompt = self._load_prompt("memory_classify.md")
        filled = prompt.format(content=content[:2000])

        try:
            response = await self._llm.complete(
                messages=[{"role": "system", "content": filled}],
                temperature=0.2,
                max_tokens=500,
            )
            parsed = self._parse_json(response.content)
            return self._to_result(parsed, content)
        except Exception:
            logger.debug("Classification failed, using defaults", exc_info=True)
            return ClassificationResult(
                memory_type="general",
                context_description=content[:200],
            )

    async def classify_document(
        self, filename: str, first_chunk: str,
    ) -> ClassificationResult:
        """Classify a document from its filename + first chunk.
        Returns shared metadata applicable to all chunks.
        """
        content = f"Document: {filename}\n\n{first_chunk[:1000]}"
        return await self.classify(content)

    def _to_result(self, parsed: dict, fallback_content: str) -> ClassificationResult:
        memory_type = parsed.get("memory_type", "general")
        if memory_type not in self.VALID_TYPES:
            memory_type = "general"
        return ClassificationResult(
            memory_type=memory_type,
            keywords=parsed.get("keywords", [])[:5],
            tags=parsed.get("tags", [])[:3],
            context_description=parsed.get("context_description", fallback_content[:200]),
        )

    def _load_prompt(self, filename: str) -> str:
        path = self._prompts_dir / filename
        if path.exists():
            return path.read_text()
        logger.warning("Prompt not found: %s", path)
        return "Classify this content:\n{content}"

    @staticmethod
    def _parse_json(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text, count=1)
            text = re.sub(r"\n?```\s*$", "", text.rstrip())
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse classifier JSON: %s", text[:200])
            return {}
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_classifier.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add odigos/memory/classifier.py data/prompts/memory_classify.md tests/test_memory_classifier.py
git commit -m "feat: add MemoryClassifier with 9 memory types and bulk document mode"
```

---

### Task 3: MemoryStore — Write Pipeline

**Files:**
- Create: `odigos/memory/store.py`
- Create: `data/prompts/memory_link.md`
- Extend: `tests/test_memory_store.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_memory_store.py`:

```python
import json
from unittest.mock import AsyncMock, MagicMock, patch

from odigos.memory.store import MemoryStore, MemoryRecord
from odigos.memory.classifier import ClassificationResult
from odigos.providers.base import LLMResponse


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=50, tokens_out=100, cost_usd=0.001,
    )


class TestMemoryStore:
    async def test_store_inserts_memory_and_embedding(self, db):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "memory_type": "fact",
            "keywords": ["timezone", "PST"],
            "tags": ["user-profile"],
            "context_description": "User is in PST timezone.",
        })))

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 768)

        store = MemoryStore(
            db=db, llm_client=mock_llm, embedder=mock_embedder,
            prompts_dir="data/prompts",
        )
        record = await store.store(
            content="My timezone is PST",
            source_type="conversation",
            source_id="conv-1",
        )

        assert record is not None
        assert record.memory_type == "fact"

        # Verify DB row
        row = await db.fetch_one("SELECT * FROM memories WHERE id = ?", (record.id,))
        assert row is not None
        assert row["memory_type"] == "fact"
        assert row["content"] == "My timezone is PST"
        assert json.loads(row["keywords_json"]) == ["timezone", "PST"]

    async def test_store_deduplicates_exact_match(self, db):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "memory_type": "fact",
            "keywords": ["timezone"],
            "tags": [],
            "context_description": "Timezone info.",
        })))

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 768)
        mock_embedder.embed_query = AsyncMock(return_value=[0.1] * 768)

        store = MemoryStore(
            db=db, llm_client=mock_llm, embedder=mock_embedder,
            prompts_dir="data/prompts",
        )

        r1 = await store.store("My timezone is PST", "conversation", "conv-1")
        r2 = await store.store("My timezone is PST", "conversation", "conv-2")

        # Second store should return existing record (dedup)
        assert r1.id == r2.id

        # Only 1 row in DB
        rows = await db.fetch_all("SELECT * FROM memories")
        assert len(rows) == 1

    async def test_store_with_bulk_skips_linking(self, db):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "memory_type": "general",
            "keywords": ["docker"],
            "tags": ["infra"],
            "context_description": "Docker content.",
        })))

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 768)

        store = MemoryStore(
            db=db, llm_client=mock_llm, embedder=mock_embedder,
            prompts_dir="data/prompts",
        )
        record = await store.store(
            "Docker deployment steps...", "document", "doc-1", bulk=True,
        )

        assert record is not None
        # No links created in bulk mode
        links = await db.fetch_all("SELECT * FROM memory_links")
        assert len(links) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_store.py::TestMemoryStore -x -q`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create the link prompt**

Create `data/prompts/memory_link.md`:

```markdown
You are a memory relationship analyzer. Given a new memory and candidate related memories, determine the relationship between them.

## Relationship Types

- **supports**: The candidate provides evidence or context for the new memory
- **refines**: The candidate adds detail or nuance to the new memory
- **contradicts**: The candidate conflicts with the new memory
- **related**: The memories are topically related but don't have a directional relationship
- **none**: No meaningful relationship

## Output

Return valid JSON only, no markdown fences:

{{"links": [{{"candidate_id": "id1", "relationship": "supports", "strength": 0.8}}, {{"candidate_id": "id2", "relationship": "none"}}]}}

## New Memory

Type: {new_type}
Content: {new_content}
Context: {new_context}

## Candidate Memories

{candidates_block}
```

- [ ] **Step 4: Implement store.py**

Create `odigos/memory/store.py`:

```python
"""MemoryStore — structured memory write pipeline."""
from __future__ import annotations

import json
import logging
import re
import struct
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.embeddings import EmbeddingProvider

from odigos.memory.classifier import MemoryClassifier, ClassificationResult

logger = logging.getLogger(__name__)

DEDUP_THRESHOLD = 0.15
LINK_THRESHOLD = 0.4
LINK_CANDIDATES = 5


def _serialize_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


@dataclass
class MemoryRecord:
    id: str
    content: str
    memory_type: str
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    context_description: str = ""
    source_type: str = ""
    source_id: str = ""
    conversation_id: str | None = None
    confidence: float = 0.8
    status: str = "active"


class MemoryStore:
    """Structured memory write pipeline: classify, embed, dedup, link."""

    def __init__(
        self,
        db: Database,
        llm_client,
        embedder: EmbeddingProvider,
        prompts_dir: str = "data/prompts",
    ) -> None:
        self._db = db
        self._llm = llm_client
        self._embedder = embedder
        self._classifier = MemoryClassifier(llm_client, prompts_dir)
        self._prompts_dir = Path(prompts_dir)

    async def store(
        self,
        content: str,
        source_type: str,
        source_id: str,
        conversation_id: str | None = None,
        confidence: float = 0.8,
        bulk: bool = False,
        classification: ClassificationResult | None = None,
    ) -> MemoryRecord:
        """Store a memory: classify, embed, dedup, link.

        Args:
            content: Raw content to store.
            source_type: Where this came from (conversation, document, etc.)
            source_id: ID of the source.
            conversation_id: Optional conversation reference.
            confidence: Initial confidence score.
            bulk: If True, skip link discovery (for bulk ingestion).
            classification: Pre-computed classification (for bulk document mode).
        """
        # 1. Classify
        if classification is None:
            classification = await self._classifier.classify(content)

        # 2. Embed
        embed_text = classification.context_description or content
        vector = await self._embedder.embed(embed_text)

        # 3. Dedup check
        existing = await self._find_near_duplicate(vector, classification.memory_type)
        if existing:
            return existing

        # 4. Store
        mem_id = str(uuid.uuid4())
        await self._db.execute(
            """
            INSERT INTO memories
                (id, content, memory_type, keywords_json, tags_json,
                 context_description, source_type, source_id,
                 conversation_id, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mem_id, content, classification.memory_type,
                json.dumps(classification.keywords),
                json.dumps(classification.tags),
                classification.context_description,
                source_type, source_id, conversation_id, confidence,
            ),
        )
        await self._db.execute(
            "INSERT INTO memory_vec (id, embedding) VALUES (?, ?)",
            (mem_id, _serialize_f32(vector)),
        )

        record = MemoryRecord(
            id=mem_id,
            content=content,
            memory_type=classification.memory_type,
            keywords=classification.keywords,
            tags=classification.tags,
            context_description=classification.context_description,
            source_type=source_type,
            source_id=source_id,
            conversation_id=conversation_id,
            confidence=confidence,
        )

        # 5. Link discovery (skip in bulk mode and for summaries)
        if not bulk and classification.memory_type != "summary":
            await self._discover_links(record, vector)

        return record

    async def _find_near_duplicate(
        self, vector: list[float], memory_type: str,
    ) -> MemoryRecord | None:
        """Check for near-duplicate in vector store."""
        count = await self._db.fetch_one("SELECT COUNT(*) as c FROM memory_vec")
        if not count or count["c"] == 0:
            return None

        rows = await self._db.fetch_all(
            """
            SELECT m.*, v.distance FROM (
                SELECT id, distance FROM memory_vec
                WHERE embedding MATCH ? ORDER BY distance LIMIT 3
            ) v
            JOIN memories m ON m.id = v.id
            WHERE m.status = 'active'
            """,
            (_serialize_f32(vector),),
        )

        for row in rows:
            if row["distance"] < DEDUP_THRESHOLD:
                if row["memory_type"] == memory_type:
                    # Exact dedup — return existing
                    return MemoryRecord(
                        id=row["id"],
                        content=row["content"],
                        memory_type=row["memory_type"],
                        keywords=json.loads(row["keywords_json"] or "[]"),
                        tags=json.loads(row["tags_json"] or "[]"),
                        context_description=row["context_description"] or "",
                        source_type=row["source_type"],
                        source_id=row["source_id"],
                        confidence=row["confidence"],
                        status=row["status"],
                    )
                else:
                    # Type mismatch — queue for evolution
                    await self._db.execute(
                        "INSERT INTO evolution_queue (existing_memory_id, new_content, reason) "
                        "VALUES (?, ?, ?)",
                        (row["id"], row["content"], "type_mismatch"),
                    )
        return None

    async def _discover_links(
        self, record: MemoryRecord, vector: list[float],
    ) -> None:
        """Find and create links to related memories."""
        count = await self._db.fetch_one("SELECT COUNT(*) as c FROM memory_vec")
        if not count or count["c"] < 2:
            return

        rows = await self._db.fetch_all(
            """
            SELECT m.id, m.content, m.memory_type, m.context_description,
                   v.distance
            FROM (
                SELECT id, distance FROM memory_vec
                WHERE embedding MATCH ? ORDER BY distance LIMIT ?
            ) v
            JOIN memories m ON m.id = v.id
            WHERE m.status = 'active' AND m.id != ?
            """,
            (_serialize_f32(vector), LINK_CANDIDATES + 1, record.id),
        )

        candidates = [r for r in rows if r["distance"] < LINK_THRESHOLD]
        if not candidates:
            return

        # Build candidates block for LLM
        lines = []
        for c in candidates:
            lines.append(
                f"- ID: {c['id']} | Type: {c['memory_type']} | "
                f"Content: {(c['context_description'] or c['content'])[:200]}"
            )
        candidates_block = "\n".join(lines)

        prompt = self._load_prompt("memory_link.md")
        filled = prompt.format(
            new_type=record.memory_type,
            new_content=record.content[:500],
            new_context=record.context_description[:300],
            candidates_block=candidates_block,
        )

        try:
            response = await self._llm.complete(
                messages=[{"role": "system", "content": filled}],
                temperature=0.2,
                max_tokens=500,
            )
            parsed = self._parse_json(response.content)
            links = parsed.get("links", [])

            for link in links:
                rel = link.get("relationship", "none")
                if rel == "none":
                    continue
                target_id = link.get("candidate_id")
                strength = link.get("strength", 0.5)
                if not target_id:
                    continue

                # Bidirectional link
                await self._db.execute(
                    "INSERT OR IGNORE INTO memory_links "
                    "(source_note_id, target_note_id, relationship, strength) "
                    "VALUES (?, ?, ?, ?)",
                    (record.id, target_id, rel, strength),
                )
                await self._db.execute(
                    "INSERT OR IGNORE INTO memory_links "
                    "(source_note_id, target_note_id, relationship, strength) "
                    "VALUES (?, ?, ?, ?)",
                    (target_id, record.id, rel, strength),
                )

                # Handle contradictions
                if rel == "contradicts":
                    await self._db.execute(
                        "UPDATE memories SET status = 'superseded', "
                        "superseded_by = ? WHERE id = ?",
                        (record.id, target_id),
                    )
        except Exception:
            logger.debug("Link discovery failed", exc_info=True)

    def _load_prompt(self, filename: str) -> str:
        path = self._prompts_dir / filename
        if path.exists():
            return path.read_text()
        return ""

    @staticmethod
    def _parse_json(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text, count=1)
            text = re.sub(r"\n?```\s*$", "", text.rstrip())
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_store.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add odigos/memory/store.py data/prompts/memory_link.md tests/test_memory_store.py
git commit -m "feat: add MemoryStore with classify, embed, dedup, link pipeline"
```

---

### Task 4: MemoryRecall — Read Pipeline

**Files:**
- Create: `odigos/memory/recall.py`
- Create: `tests/test_memory_recall.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_memory_recall.py`:

```python
"""Tests for structured memory recall pipeline."""
from __future__ import annotations

import json
import struct
import uuid

import pytest
import pytest_asyncio

from odigos.db import Database


def _serialize_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


async def _seed_memory(db, content, memory_type, vec, confidence=0.8, **kwargs):
    """Insert a memory + embedding directly for testing."""
    mem_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO memories (id, content, memory_type, keywords_json, tags_json,
           context_description, source_type, source_id, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (mem_id, content, memory_type, "[]", "[]",
         kwargs.get("context", content), "test", "test-1", confidence),
    )
    await db.execute(
        "INSERT INTO memory_vec (id, embedding) VALUES (?, ?)",
        (mem_id, _serialize_f32(vec)),
    )
    return mem_id


async def _seed_link(db, source_id, target_id, relationship, strength=1.0):
    await db.execute(
        "INSERT INTO memory_links (source_note_id, target_note_id, relationship, strength) "
        "VALUES (?, ?, ?, ?)",
        (source_id, target_id, relationship, strength),
    )


class TestRecall:
    async def test_search_returns_typed_results(self, db):
        from unittest.mock import AsyncMock
        from odigos.memory.recall import MemoryRecall

        # Seed a fact and a preference with slightly different vectors
        await _seed_memory(db, "Timezone is PST", "fact", [0.9] + [0.1] * 767)
        await _seed_memory(db, "Likes dark mode", "preference", [0.1] + [0.9] * 767)

        mock_embedder = AsyncMock()
        mock_embedder.embed_query = AsyncMock(return_value=[0.9] + [0.1] * 767)

        recall = MemoryRecall(db=db, embedder=mock_embedder)
        results = await recall.search("What timezone?", memory_types=["fact"])

        assert len(results) >= 1
        assert all(r.memory_type == "fact" for r in results)

    async def test_search_excludes_superseded(self, db):
        from unittest.mock import AsyncMock
        from odigos.memory.recall import MemoryRecall

        m1 = await _seed_memory(db, "Old fact", "fact", [0.5] * 768)
        await db.execute(
            "UPDATE memories SET status = 'superseded' WHERE id = ?", (m1,)
        )
        await _seed_memory(db, "New fact", "fact", [0.5] * 768)

        mock_embedder = AsyncMock()
        mock_embedder.embed_query = AsyncMock(return_value=[0.5] * 768)

        recall = MemoryRecall(db=db, embedder=mock_embedder)
        results = await recall.search("facts")

        contents = [r.content for r in results]
        assert "Old fact" not in contents
        assert "New fact" in contents

    async def test_search_excludes_low_confidence(self, db):
        from unittest.mock import AsyncMock
        from odigos.memory.recall import MemoryRecall

        await _seed_memory(db, "Low confidence fact", "fact", [0.5] * 768, confidence=0.3)
        await _seed_memory(db, "High confidence fact", "fact", [0.5] * 768, confidence=0.9)

        mock_embedder = AsyncMock()
        mock_embedder.embed_query = AsyncMock(return_value=[0.5] * 768)

        recall = MemoryRecall(db=db, embedder=mock_embedder)
        results = await recall.search("facts")

        contents = [r.content for r in results]
        assert "Low confidence fact" not in contents
        assert "High confidence fact" in contents

    async def test_link_expansion(self, db):
        from unittest.mock import AsyncMock
        from odigos.memory.recall import MemoryRecall

        m1 = await _seed_memory(db, "Timezone is PST", "fact", [0.9] + [0.1] * 767)
        m2 = await _seed_memory(db, "No meetings before 10am", "preference", [0.1] + [0.9] * 767)
        await _seed_link(db, m1, m2, "supports", 0.9)

        mock_embedder = AsyncMock()
        mock_embedder.embed_query = AsyncMock(return_value=[0.9] + [0.1] * 767)

        recall = MemoryRecall(db=db, embedder=mock_embedder)
        results = await recall.search("timezone", expand_links=True)

        contents = [r.content for r in results]
        assert "Timezone is PST" in contents
        # Linked preference should be pulled in via link expansion
        assert "No meetings before 10am" in contents

    async def test_format_grouped(self, db):
        from unittest.mock import AsyncMock
        from odigos.memory.recall import MemoryRecall, MemoryResult

        results = [
            MemoryResult(id="1", content="TZ is PST", memory_type="fact",
                         context_description="User timezone", confidence=0.9),
            MemoryResult(id="2", content="Likes concise", memory_type="preference",
                         context_description="Prefers brevity", confidence=0.8),
        ]
        recall = MemoryRecall(db=db, embedder=AsyncMock())
        output = recall.format_grouped(results)

        assert "## Recalled knowledge" in output
        assert "### Facts" in output
        assert "### Preferences" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_recall.py -x -q`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement recall.py**

Create `odigos/memory/recall.py`:

```python
"""MemoryRecall — structured memory read pipeline."""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)

TYPE_ROUTING = {
    "simple": ["fact", "preference", "entity"],
    "standard": ["fact", "preference", "entity", "experience", "correction"],
    "complex": None,
    "planning": ["task", "idea", "experience", "fact", "entity"],
    "document_query": ["general", "summary", "fact"],
}

RECENCY_DECAY = {
    "preference": 0.01, "task": 0.01, "fact": 0.01,
    "entity": 0.002, "experience": 0.002,
    "summary": 0.0, "correction": 0.0,
    "idea": 0.005, "general": 0.005,
}

MIN_CONFIDENCE = 0.5
RRF_K = 60


def _serialize_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


@dataclass
class MemoryResult:
    id: str
    content: str
    memory_type: str
    context_description: str = ""
    confidence: float = 0.8
    distance: float = 0.0
    score: float = 0.0
    source: str = ""
    updated_at: str = ""


class MemoryRecall:
    """Structured memory read pipeline: typed search, RRF, link expansion."""

    def __init__(self, db: Database, embedder: EmbeddingProvider) -> None:
        self._db = db
        self._embedder = embedder

    async def search(
        self,
        query: str,
        classification_type: str | None = None,
        memory_types: list[str] | None = None,
        limit: int = 10,
        expand_links: bool = True,
    ) -> list[MemoryResult]:
        """Search memories with type filtering, RRF, recency, and link expansion."""
        # Determine type filter
        if memory_types:
            types = memory_types
        elif classification_type:
            types = TYPE_ROUTING.get(classification_type)
        else:
            types = None

        # Parallel: vector + FTS
        vector = await self._embedder.embed_query(query)
        vec_results = await self._vector_search(vector, types, limit=20)
        fts_results = await self._fts_search(query, types, limit=20)

        # RRF fusion
        merged = self._rrf_merge(vec_results, fts_results)

        # Recency weighting
        self._apply_recency(merged)

        # Sort by score descending, apply confidence filter
        merged.sort(key=lambda r: r.score, reverse=True)
        filtered = [r for r in merged if r.confidence >= MIN_CONFIDENCE][:limit]

        # Link expansion
        if expand_links and filtered:
            linked = await self._expand_links(
                [r.id for r in filtered], limit=5,
            )
            # Add linked results that aren't already present
            existing_ids = {r.id for r in filtered}
            for lr in linked:
                if lr.id not in existing_ids:
                    filtered.append(lr)
                    existing_ids.add(lr.id)

        return filtered

    async def _vector_search(
        self, vector: list[float], types: list[str] | None, limit: int,
    ) -> list[MemoryResult]:
        count = await self._db.fetch_one("SELECT COUNT(*) as c FROM memory_vec")
        if not count or count["c"] == 0:
            return []

        fetch_limit = limit * 3 if types else limit

        rows = await self._db.fetch_all(
            """
            SELECT m.id, m.content, m.memory_type, m.context_description,
                   m.confidence, m.updated_at, v.distance
            FROM (
                SELECT id, distance FROM memory_vec
                WHERE embedding MATCH ? ORDER BY distance LIMIT ?
            ) v
            JOIN memories m ON m.id = v.id
            WHERE m.status = 'active'
            """,
            (_serialize_f32(vector), fetch_limit),
        )

        results = []
        for row in rows:
            if types and row["memory_type"] not in types:
                continue
            results.append(MemoryResult(
                id=row["id"],
                content=row["content"],
                memory_type=row["memory_type"],
                context_description=row["context_description"] or "",
                confidence=row["confidence"],
                distance=row["distance"],
                source="vector",
                updated_at=row.get("updated_at", ""),
            ))
        return results[:limit]

    async def _fts_search(
        self, query: str, types: list[str] | None, limit: int,
    ) -> list[MemoryResult]:
        _RESERVED = {"AND", "OR", "NOT", "NEAR"}
        terms = []
        for word in query.split():
            cleaned = "".join(c for c in word if c.isalnum())
            if cleaned and cleaned.upper() not in _RESERVED:
                terms.append(cleaned)
        if not terms:
            return []

        fts_query = " OR ".join(terms)
        if len(terms) >= 2:
            phrase = " ".join(terms)
            fts_query = f'"{phrase}" OR {fts_query}'

        rows = await self._db.fetch_all(
            """
            SELECT m.id, m.content, m.memory_type, m.context_description,
                   m.confidence, m.updated_at, rank as distance
            FROM memory_fts
            JOIN memories m ON m.rowid = memory_fts.rowid
            WHERE memory_fts MATCH ? AND m.status = 'active'
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, limit * 3 if types else limit),
        )

        results = []
        for row in rows:
            if types and row["memory_type"] not in types:
                continue
            results.append(MemoryResult(
                id=row["id"],
                content=row["content"],
                memory_type=row["memory_type"],
                context_description=row["context_description"] or "",
                confidence=row["confidence"],
                distance=abs(row["distance"]),
                source="fts",
                updated_at=row.get("updated_at", ""),
            ))
        return results[:limit]

    def _rrf_merge(
        self, vec_results: list[MemoryResult], fts_results: list[MemoryResult],
    ) -> list[MemoryResult]:
        scores: dict[str, float] = {}
        result_map: dict[str, MemoryResult] = {}

        for rank, r in enumerate(vec_results):
            scores[r.id] = scores.get(r.id, 0) + 1.0 / (RRF_K + rank + 1)
            result_map[r.id] = r

        for rank, r in enumerate(fts_results):
            scores[r.id] = scores.get(r.id, 0) + 1.0 / (RRF_K + rank + 1)
            if r.id not in result_map:
                result_map[r.id] = r

        for mid, score in scores.items():
            result_map[mid].score = score

        return list(result_map.values())

    def _apply_recency(self, results: list[MemoryResult]) -> None:
        now = datetime.now(timezone.utc)
        for r in results:
            decay_rate = RECENCY_DECAY.get(r.memory_type, 0.005)
            if decay_rate == 0.0 or not r.updated_at:
                continue
            try:
                updated = datetime.fromisoformat(r.updated_at.replace("Z", "+00:00"))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                days = (now - updated).total_seconds() / 86400
                r.score *= 1.0 / (1.0 + days * decay_rate)
            except (ValueError, TypeError):
                pass

    async def _expand_links(
        self, result_ids: list[str], limit: int = 5,
    ) -> list[MemoryResult]:
        if not result_ids:
            return []
        placeholders = ",".join("?" * len(result_ids))
        rows = await self._db.fetch_all(
            f"""
            SELECT m.id, m.content, m.memory_type, m.context_description,
                   m.confidence, ml.strength
            FROM memories m
            JOIN memory_links ml ON m.id = ml.target_note_id
            WHERE ml.source_note_id IN ({placeholders})
              AND m.status = 'active'
              AND m.confidence >= ?
              AND m.id NOT IN ({placeholders})
            ORDER BY ml.strength DESC
            LIMIT ?
            """,
            (*result_ids, MIN_CONFIDENCE, *result_ids, limit),
        )
        return [
            MemoryResult(
                id=row["id"],
                content=row["content"],
                memory_type=row["memory_type"],
                context_description=row["context_description"] or "",
                confidence=row["confidence"],
                source="link",
            )
            for row in rows
        ]

    @staticmethod
    def format_grouped(results: list[MemoryResult]) -> str:
        """Format results grouped by memory_type for the system prompt."""
        if not results:
            return ""

        TYPE_HEADERS = {
            "fact": "Facts", "preference": "Preferences",
            "task": "Tasks", "idea": "Ideas",
            "entity": "Related entities", "experience": "Experiences",
            "correction": "Learned corrections",
            "summary": "Relevant summaries", "general": "Other",
        }

        groups: dict[str, list[str]] = {}
        for r in results:
            header = TYPE_HEADERS.get(r.memory_type, "Other")
            text = r.context_description or r.content
            groups.setdefault(header, []).append(f"- {text}")

        sections = ["## Recalled knowledge\n"]
        for header in TYPE_HEADERS.values():
            if header in groups:
                sections.append(f"### {header}")
                sections.extend(groups[header])
                sections.append("")

        return "\n".join(sections).strip()
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_recall.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add odigos/memory/recall.py tests/test_memory_recall.py
git commit -m "feat: add MemoryRecall with typed search, RRF, recency, link expansion"
```

---

### Task 5: MemoryEvolution — Heartbeat Job

**Files:**
- Create: `odigos/memory/evolution.py`
- Create: `data/prompts/memory_evolve.md`
- Create: `data/prompts/memory_consolidate.md`
- Create: `tests/test_memory_evolution.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_memory_evolution.py`:

```python
"""Tests for memory evolution heartbeat job."""
from __future__ import annotations

import json
import struct
import uuid

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock

from odigos.db import Database
from odigos.providers.base import LLMResponse


def _serialize_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=50, tokens_out=100, cost_usd=0.001,
    )


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


async def _seed_memory(db, content, memory_type, vec=None):
    mem_id = str(uuid.uuid4())
    if vec is None:
        vec = [0.5] * 768
    await db.execute(
        """INSERT INTO memories (id, content, memory_type, keywords_json, tags_json,
           context_description, source_type, source_id, confidence)
        VALUES (?, ?, ?, '[]', '[]', ?, 'test', 'test-1', 0.8)""",
        (mem_id, content, memory_type, content),
    )
    await db.execute(
        "INSERT INTO memory_vec (id, embedding) VALUES (?, ?)",
        (mem_id, _serialize_f32(vec)),
    )
    return mem_id


class TestEvolutionQueue:
    async def test_processes_update_action(self, db):
        from odigos.memory.evolution import MemoryEvolution

        m1 = await _seed_memory(db, "User timezone is EST", "fact")
        await db.execute(
            "INSERT INTO evolution_queue (existing_memory_id, new_content, reason) "
            "VALUES (?, ?, ?)",
            (m1, "User moved to PST timezone", "richer_content"),
        )

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "action": "UPDATE",
            "context_description": "User timezone is PST (moved from EST).",
            "keywords": ["timezone", "PST"],
            "tags": ["user-profile"],
        })))

        evo = MemoryEvolution(db=db, llm_client=mock_llm, prompts_dir="data/prompts")
        stats = await evo.run_cycle()

        assert stats["processed"] >= 1

        # Memory should be updated
        row = await db.fetch_one("SELECT * FROM memories WHERE id = ?", (m1,))
        assert "PST" in row["context_description"]

        # Queue item should be marked processed
        q = await db.fetch_one("SELECT processed_at FROM evolution_queue WHERE existing_memory_id = ?", (m1,))
        assert q["processed_at"] is not None

    async def test_processes_supersede_action(self, db):
        from odigos.memory.evolution import MemoryEvolution

        m1 = await _seed_memory(db, "Old fact about user", "fact")
        await db.execute(
            "INSERT INTO evolution_queue (existing_memory_id, new_content, reason) "
            "VALUES (?, ?, ?)",
            (m1, "Completely new information", "richer_content"),
        )

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "action": "SUPERSEDE",
            "content": "Completely new and better information",
            "memory_type": "fact",
            "keywords": ["new"],
            "tags": [],
            "context_description": "Replaced outdated information.",
        })))

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.6] * 768)

        evo = MemoryEvolution(
            db=db, llm_client=mock_llm, prompts_dir="data/prompts",
            embedder=mock_embedder,
        )
        stats = await evo.run_cycle()

        assert stats["processed"] >= 1

        # Old memory should be superseded
        old = await db.fetch_one("SELECT status, superseded_by FROM memories WHERE id = ?", (m1,))
        assert old["status"] == "superseded"
        assert old["superseded_by"] is not None

        # New memory should exist
        new = await db.fetch_one("SELECT * FROM memories WHERE id = ?", (old["superseded_by"],))
        assert new is not None
        assert new["status"] == "active"

    async def test_skips_empty_queue(self, db):
        from odigos.memory.evolution import MemoryEvolution

        mock_llm = AsyncMock()
        evo = MemoryEvolution(db=db, llm_client=mock_llm, prompts_dir="data/prompts")
        stats = await evo.run_cycle()

        assert stats["processed"] == 0
        mock_llm.complete.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_evolution.py -x -q`
Expected: FAIL.

- [ ] **Step 3: Create prompts**

Create `data/prompts/memory_evolve.md`:

```markdown
You are a memory evolution system. An existing memory may need updating based on new information.

## Existing Memory

Type: {memory_type}
Content: {existing_content}
Context: {existing_context}
Keywords: {existing_keywords}

## New Information

{new_content}

## Decide

1. **UPDATE** -- the new information enriches the existing memory. Return updated fields.
2. **SUPERSEDE** -- the new information replaces or fundamentally changes the memory. Return a complete new memory.
3. **SKIP** -- the new information adds nothing meaningful.

Return valid JSON only:

For UPDATE:
{{"action": "UPDATE", "context_description": "...", "keywords": [...], "tags": [...]}}

For SUPERSEDE:
{{"action": "SUPERSEDE", "content": "...", "memory_type": "...", "keywords": [...], "tags": [...], "context_description": "..."}}

For SKIP:
{{"action": "SKIP"}}
```

Create `data/prompts/memory_consolidate.md`:

```markdown
You are a memory synthesis system. A memory has many connections to other memories. Determine if they should be consolidated into a richer, higher-order insight.

## Central Memory

Type: {memory_type}
Content: {content}
Context: {context_description}

## Connected Memories

{connected_block}

## Decide

Should these memories be consolidated into a single richer memory that captures the combined insight?

Return valid JSON only:

{{"should_consolidate": true, "content": "Synthesized insight...", "memory_type": "fact", "keywords": [...], "tags": [...], "context_description": "..."}}

Or if consolidation is not warranted:

{{"should_consolidate": false}}
```

- [ ] **Step 4: Implement evolution.py**

Create `odigos/memory/evolution.py`:

```python
"""MemoryEvolution — heartbeat job for refining and consolidating memories."""
from __future__ import annotations

import json
import logging
import re
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)

MAX_QUEUE_PER_CYCLE = 5
MAX_CONSOLIDATE_PER_CYCLE = 3
CONSOLIDATION_LINK_THRESHOLD = 4


def _serialize_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


class MemoryEvolution:
    """Heartbeat job: process evolution queue + consolidate high-connectivity memories."""

    def __init__(
        self,
        db: Database,
        llm_client,
        prompts_dir: str = "data/prompts",
        embedder: "EmbeddingProvider | None" = None,
    ) -> None:
        self._db = db
        self._llm = llm_client
        self._prompts_dir = Path(prompts_dir)
        self._embedder = embedder

    async def run_cycle(self) -> dict:
        """Run one evolution cycle. Returns stats."""
        processed = await self._process_queue()
        consolidated = await self._consolidate_high_connectivity()
        return {"processed": processed, "consolidated": consolidated}

    async def _process_queue(self) -> int:
        rows = await self._db.fetch_all(
            "SELECT eq.*, m.content as existing_content, m.memory_type, "
            "m.context_description as existing_context, m.keywords_json "
            "FROM evolution_queue eq "
            "JOIN memories m ON m.id = eq.existing_memory_id "
            "WHERE eq.processed_at IS NULL AND m.status = 'active' "
            "ORDER BY eq.created_at ASC LIMIT ?",
            (MAX_QUEUE_PER_CYCLE,),
        )
        if not rows:
            return 0

        count = 0
        for row in rows:
            try:
                await self._evolve_one(row)
                count += 1
            except Exception:
                logger.debug("Evolution failed for queue item %s", row["id"], exc_info=True)

            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "UPDATE evolution_queue SET processed_at = ? WHERE id = ?",
                (now, row["id"]),
            )
        return count

    async def _evolve_one(self, row) -> None:
        prompt = self._load_prompt("memory_evolve.md")
        filled = prompt.format(
            memory_type=row["memory_type"],
            existing_content=row["existing_content"][:500],
            existing_context=(row["existing_context"] or "")[:300],
            existing_keywords=row["keywords_json"] or "[]",
            new_content=row["new_content"][:500],
        )

        response = await self._llm.complete(
            messages=[{"role": "system", "content": filled}],
            temperature=0.3, max_tokens=800,
        )
        parsed = self._parse_json(response.content)
        action = parsed.get("action", "SKIP")

        if action == "UPDATE":
            now = datetime.now(timezone.utc).isoformat()
            updates = []
            params = []
            if parsed.get("context_description"):
                updates.append("context_description = ?")
                params.append(parsed["context_description"])
            if parsed.get("keywords"):
                updates.append("keywords_json = ?")
                params.append(json.dumps(parsed["keywords"]))
            if parsed.get("tags"):
                updates.append("tags_json = ?")
                params.append(json.dumps(parsed["tags"]))
            updates.append("updated_at = ?")
            params.append(now)
            params.append(row["existing_memory_id"])

            if updates:
                await self._db.execute(
                    f"UPDATE memories SET {', '.join(updates)} WHERE id = ?",
                    tuple(params),
                )

        elif action == "SUPERSEDE":
            new_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                """INSERT INTO memories (id, content, memory_type, keywords_json,
                   tags_json, context_description, source_type, source_id, confidence)
                VALUES (?, ?, ?, ?, ?, ?, 'evolution', ?, 0.8)""",
                (
                    new_id,
                    parsed.get("content", row["new_content"]),
                    parsed.get("memory_type", row["memory_type"]),
                    json.dumps(parsed.get("keywords", [])),
                    json.dumps(parsed.get("tags", [])),
                    parsed.get("context_description", ""),
                    row["existing_memory_id"],
                ),
            )

            # Embed new memory if embedder available
            if self._embedder:
                embed_text = parsed.get("context_description", parsed.get("content", ""))
                vec = await self._embedder.embed(embed_text)
                await self._db.execute(
                    "INSERT INTO memory_vec (id, embedding) VALUES (?, ?)",
                    (new_id, _serialize_f32(vec)),
                )

            # Mark old as superseded
            await self._db.execute(
                "UPDATE memories SET status = 'superseded', superseded_by = ?, "
                "updated_at = ? WHERE id = ?",
                (new_id, now, row["existing_memory_id"]),
            )

            # Transfer links to new memory
            await self._db.execute(
                "UPDATE memory_links SET source_note_id = ? WHERE source_note_id = ?",
                (new_id, row["existing_memory_id"]),
            )
            await self._db.execute(
                "UPDATE memory_links SET target_note_id = ? WHERE target_note_id = ?",
                (new_id, row["existing_memory_id"]),
            )

    async def _consolidate_high_connectivity(self) -> int:
        """Find memories with 4+ links and attempt synthesis."""
        rows = await self._db.fetch_all(
            """
            SELECT m.id, m.content, m.memory_type, m.context_description,
                   COUNT(ml.id) as link_count
            FROM memories m
            JOIN memory_links ml ON ml.target_note_id = m.id
            WHERE m.status = 'active'
            GROUP BY m.id
            HAVING link_count >= ?
            ORDER BY link_count DESC
            LIMIT ?
            """,
            (CONSOLIDATION_LINK_THRESHOLD, MAX_CONSOLIDATE_PER_CYCLE),
        )
        if not rows:
            return 0

        count = 0
        for row in rows:
            try:
                did = await self._consolidate_one(row)
                if did:
                    count += 1
            except Exception:
                logger.debug("Consolidation failed for %s", row["id"], exc_info=True)
        return count

    async def _consolidate_one(self, row) -> bool:
        # Fetch connected memories
        connected = await self._db.fetch_all(
            """
            SELECT m.id, m.content, m.memory_type, m.context_description
            FROM memories m
            JOIN memory_links ml ON m.id = ml.source_note_id
            WHERE ml.target_note_id = ? AND m.status = 'active'
            LIMIT 10
            """,
            (row["id"],),
        )
        if len(connected) < 2:
            return False

        lines = []
        for c in connected:
            lines.append(
                f"- [{c['memory_type']}] {(c['context_description'] or c['content'])[:200]}"
            )

        prompt = self._load_prompt("memory_consolidate.md")
        filled = prompt.format(
            memory_type=row["memory_type"],
            content=row["content"][:500],
            context_description=(row["context_description"] or "")[:300],
            connected_block="\n".join(lines),
        )

        response = await self._llm.complete(
            messages=[{"role": "system", "content": filled}],
            temperature=0.3, max_tokens=800,
        )
        parsed = self._parse_json(response.content)

        if not parsed.get("should_consolidate"):
            return False

        new_id = str(uuid.uuid4())
        await self._db.execute(
            """INSERT INTO memories (id, content, memory_type, keywords_json,
               tags_json, context_description, source_type, source_id, confidence)
            VALUES (?, ?, ?, ?, ?, ?, 'synthesis', ?, 0.9)""",
            (
                new_id,
                parsed.get("content", ""),
                parsed.get("memory_type", "fact"),
                json.dumps(parsed.get("keywords", [])),
                json.dumps(parsed.get("tags", [])),
                parsed.get("context_description", ""),
                row["id"],
            ),
        )

        if self._embedder:
            vec = await self._embedder.embed(
                parsed.get("context_description", parsed.get("content", ""))
            )
            await self._db.execute(
                "INSERT INTO memory_vec (id, embedding) VALUES (?, ?)",
                (new_id, _serialize_f32(vec)),
            )

        # Link synthesized memory to originals
        all_ids = [row["id"]] + [c["id"] for c in connected]
        for orig_id in all_ids:
            await self._db.execute(
                "INSERT OR IGNORE INTO memory_links "
                "(source_note_id, target_note_id, relationship, strength) "
                "VALUES (?, ?, 'synthesized_from', 1.0)",
                (new_id, orig_id),
            )

        return True

    def _load_prompt(self, filename: str) -> str:
        path = self._prompts_dir / filename
        if path.exists():
            return path.read_text()
        return ""

    @staticmethod
    def _parse_json(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text, count=1)
            text = re.sub(r"\n?```\s*$", "", text.rstrip())
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_evolution.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add odigos/memory/evolution.py data/prompts/memory_evolve.md \
       data/prompts/memory_consolidate.md tests/test_memory_evolution.py
git commit -m "feat: add MemoryEvolution with queue processing and high-connectivity consolidation"
```

---

### Task 6: Update MemoryManager to Use New System

**Files:**
- Modify: `odigos/memory/manager.py`

- [ ] **Step 1: Rewrite MemoryManager**

The current MemoryManager uses VectorMemory for store/recall. Replace with MemoryStore + MemoryRecall:

1. Change imports: remove `VectorMemory`, add `MemoryStore`, `MemoryRecall`
2. Update `__init__`: accept `memory_store: MemoryStore` and `memory_recall: MemoryRecall` instead of `vector_memory: VectorMemory`
3. Update `recall()`: call `self.memory_recall.search()` + entity graph traverse, then `format_grouped()`
4. Update `store()`: call `self.memory_store.store()` for facts/messages. Entity storage still goes through EntityGraph.
5. Remove `_hybrid_search()` method (replaced by MemoryRecall.search)
6. Keep `_bulk_fetch_full_text()` for document expansion
7. Keep the cross-encoder reranker import (MemoryRecall doesn't use it yet, but manager can apply it as a post-filter)

Key changes in `store()`:
- Replace `self.vector_memory.store(text, source_type, source_id, ...)` with `await self.memory_store.store(content=text, source_type=source_type, source_id=source_id, ...)`
- Remove `user_facts` inserts — facts now go through MemoryStore as type=fact
- Keep entity creation via EntityGraph, but also create a type=entity memory

Key changes in `recall()`:
- Replace `self._hybrid_search(query, ...)` with `await self.memory_recall.search(query, classification_type=...)`
- Keep entity graph traverse — merge entity results with memory results
- Return `self.memory_recall.format_grouped(all_results)`

- [ ] **Step 2: Run existing tests that use MemoryManager**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q -k "memory" 2>&1 | tail -20`
Expected: Some tests may fail if they reference VectorMemory directly. Fix as needed.

- [ ] **Step 3: Commit**

```bash
git add odigos/memory/manager.py
git commit -m "feat: update MemoryManager to use MemoryStore + MemoryRecall"
```

---

### Task 7: Update Callers — Corrections, Summarizer, Ingester, Resolver

**Files:**
- Modify: `odigos/memory/corrections.py`
- Modify: `odigos/memory/summarizer.py`
- Modify: `odigos/memory/ingester.py`
- Modify: `odigos/memory/resolver.py`

- [ ] **Step 1: Update CorrectionsManager**

In `corrections.py`, the `store()` method currently calls `self.vector_memory.store(...)`. Add a MemoryStore call alongside:

```python
def __init__(self, db, vector_memory=None, memory_store=None):
    self.db = db
    self._memory_store = memory_store

async def store(self, ...):
    # ... existing corrections table insert ...
    
    # Also store as a typed memory
    if self._memory_store:
        from odigos.memory.classifier import ClassificationResult
        classification = ClassificationResult(
            memory_type="correction",
            keywords=[category],
            tags=["user-feedback"],
            context_description=f"[{category}] {correction} (context: {context})",
        )
        await self._memory_store.store(
            content=f"{context}: {correction}",
            source_type="correction",
            source_id=correction_id,
            conversation_id=conversation_id,
            classification=classification,
        )

async def relevant(self, query, limit=5):
    if self._memory_store:
        from odigos.memory.recall import MemoryRecall
        # Use the recall system filtered to corrections
        # This requires access to MemoryRecall — pass it through or query DB directly
    # ... fallback to existing behavior ...
```

- [ ] **Step 2: Update ConversationSummarizer**

Replace `self.vector_memory.store(...)` with `self.memory_store.store(...)` passing `classification=ClassificationResult(memory_type="summary", ...)`.

- [ ] **Step 3: Update DocumentIngester**

Replace `self.vector_memory.store(...)` with `self.memory_store.store(...)`. For bulk mode, classify the document once and pass the shared `classification` to each chunk's store call with `bulk=True`.

- [ ] **Step 4: Update EntityResolver**

Replace `self.vector_memory.search(...)` with a direct DB query against `memories` table filtered by `memory_type='entity'`.

- [ ] **Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q 2>&1 | tail -20`
Expected: All pass (or identify which tests need fixture updates).

- [ ] **Step 6: Commit**

```bash
git add odigos/memory/corrections.py odigos/memory/summarizer.py \
       odigos/memory/ingester.py odigos/memory/resolver.py
git commit -m "feat: migrate callers to MemoryStore — corrections, summarizer, ingester, resolver"
```

---

### Task 8: Update ContextAssembler + Remove Old Files

**Files:**
- Modify: `odigos/core/context.py`
- Remove: `odigos/memory/vectors.py`

- [ ] **Step 1: Update context.py memory_index counts**

The `_memory_index()` function queries `memory_entries`. Update to query `memories`:

```python
# Old:
# COUNT(*) FROM memory_entries WHERE source_type = 'document_chunk'
# New:
count_docs = await self.db.fetch_one(
    "SELECT COUNT(*) as c FROM memories WHERE source_type = 'document' AND status = 'active'"
)
count_convos = await self.db.fetch_one(
    "SELECT COUNT(*) as c FROM memories WHERE source_type = 'conversation' AND status = 'active'"
)
count_entities = await self.db.fetch_one(
    "SELECT COUNT(*) as c FROM entities WHERE status = 'active'"
)
```

- [ ] **Step 2: Remove vectors.py**

```bash
git rm odigos/memory/vectors.py
```

- [ ] **Step 3: Fix any remaining imports of VectorMemory**

Search for `from odigos.memory.vectors import` and remove/replace all occurrences.

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: update ContextAssembler for new memory tables, remove vectors.py"
```

---

### Task 9: Heartbeat + Bootstrap Wiring

**Files:**
- Modify: `odigos/core/heartbeat/orchestrator.py`
- Modify: `odigos/core/heartbeat/maintenance.py`
- Modify: `odigos/bootstrap.py`

- [ ] **Step 1: Add memory evolution phase to orchestrator**

After experience extraction (Phase 9), add:

```python
# Phase 9.5: Memory evolution
if hasattr(self, "memory_evolution") and self.memory_evolution:
    try:
        stats = await self.memory_evolution.run_cycle()
        if stats.get("processed", 0) > 0:
            logger.info("Memory evolution: %d processed, %d consolidated",
                        stats["processed"], stats.get("consolidated", 0))
    except Exception:
        logger.debug("Memory evolution failed", exc_info=True)
```

- [ ] **Step 2: Wire in bootstrap.py**

Create MemoryStore, MemoryRecall, MemoryEvolution instances. Pass MemoryStore to all callers that need it (MemoryManager, CorrectionsManager, Summarizer, Ingester). Attach MemoryEvolution to heartbeat.

- [ ] **Step 3: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q`

- [ ] **Step 4: Commit**

```bash
git add odigos/core/heartbeat/orchestrator.py odigos/core/heartbeat/maintenance.py odigos/bootstrap.py
git commit -m "feat: wire MemoryStore, MemoryRecall, MemoryEvolution into heartbeat and bootstrap"
```

---

### Task 10: Integration Test — Full Pipeline

**Files:**
- Create: `tests/test_memory_integration.py`

- [ ] **Step 1: Write integration test**

```python
"""Integration test: store -> recall -> evolution full pipeline."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.db import Database
from odigos.memory.store import MemoryStore
from odigos.memory.recall import MemoryRecall
from odigos.memory.evolution import MemoryEvolution
from odigos.providers.base import LLMResponse


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=50, tokens_out=100, cost_usd=0.001,
    )


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


class TestFullPipeline:
    async def test_store_recall_cycle(self, db):
        """Store a memory, then recall it by type."""
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(json.dumps({
            "memory_type": "preference",
            "keywords": ["dark mode", "UI"],
            "tags": ["user-profile"],
            "context_description": "User prefers dark mode for the UI.",
        })))

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.5] * 768)
        mock_embedder.embed_query = AsyncMock(return_value=[0.5] * 768)

        store = MemoryStore(db=db, llm_client=mock_llm, embedder=mock_embedder)
        recall = MemoryRecall(db=db, embedder=mock_embedder)

        # Store
        record = await store.store(
            content="I prefer dark mode",
            source_type="conversation",
            source_id="conv-1",
        )
        assert record.memory_type == "preference"

        # Recall
        results = await recall.search("dark mode preference", memory_types=["preference"])
        assert len(results) >= 1
        assert any("dark mode" in r.content.lower() for r in results)

        # Format
        output = recall.format_grouped(results)
        assert "### Preferences" in output

    async def test_evolution_updates_stale_memory(self, db):
        """Store a fact, queue evolution, verify it updates."""
        classify_response = json.dumps({
            "memory_type": "fact",
            "keywords": ["timezone", "EST"],
            "tags": ["user-profile"],
            "context_description": "User timezone is EST.",
        })
        evolve_response = json.dumps({
            "action": "UPDATE",
            "context_description": "User timezone is PST (moved from EST).",
            "keywords": ["timezone", "PST"],
            "tags": ["user-profile"],
        })

        call_count = 0

        async def mock_complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return _make_llm_response(classify_response)
            return _make_llm_response(evolve_response)

        mock_llm = AsyncMock()
        mock_llm.complete = mock_complete

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.5] * 768)

        store = MemoryStore(db=db, llm_client=mock_llm, embedder=mock_embedder)
        record = await store.store("My timezone is EST", "conversation", "conv-1")

        # Queue evolution
        await db.execute(
            "INSERT INTO evolution_queue (existing_memory_id, new_content, reason) "
            "VALUES (?, ?, ?)",
            (record.id, "I moved to PST", "richer_content"),
        )

        # Run evolution
        evo = MemoryEvolution(db=db, llm_client=mock_llm, prompts_dir="data/prompts")
        stats = await evo.run_cycle()
        assert stats["processed"] == 1

        # Verify update
        row = await db.fetch_one("SELECT * FROM memories WHERE id = ?", (record.id,))
        assert "PST" in row["context_description"]
```

- [ ] **Step 2: Run test**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_integration.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_memory_integration.py
git commit -m "test: add full pipeline integration test for structured memory"
```

---

### Task 11: Final — Full Suite + Lint + Smoke Test

- [ ] **Step 1: Run all new memory tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_memory_store.py tests/test_memory_recall.py tests/test_memory_evolution.py tests/test_memory_classifier.py tests/test_memory_integration.py -v`
Expected: All pass.

- [ ] **Step 2: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 3: Docker build + smoke test**

Run: `cd /Users/jacob/Projects/odigos && make build && make up && sleep 5 && make logs`
Expected: Clean startup, no import errors.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A && git commit -m "fix: lint and cleanup for structured memory system"
```
