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
    # Only insert into memory_vec if the virtual table exists (requires sqlite-vec)
    row = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_vec'"
    )
    if row is not None:
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

        m1 = await _seed_memory(db, "Old timezone info", "fact", [0.5] * 768)
        await db.execute(
            "UPDATE memories SET status = 'superseded' WHERE id = ?", (m1,)
        )
        await _seed_memory(db, "New timezone info", "fact", [0.5] * 768)

        mock_embedder = AsyncMock()
        mock_embedder.embed_query = AsyncMock(return_value=[0.5] * 768)

        recall = MemoryRecall(db=db, embedder=mock_embedder)
        results = await recall.search("timezone")

        contents = [r.content for r in results]
        assert "Old timezone info" not in contents
        assert "New timezone info" in contents

    async def test_search_excludes_low_confidence(self, db):
        from unittest.mock import AsyncMock
        from odigos.memory.recall import MemoryRecall

        await _seed_memory(db, "Low confidence timezone", "fact", [0.5] * 768, confidence=0.3)
        await _seed_memory(db, "High confidence timezone", "fact", [0.5] * 768, confidence=0.9)

        mock_embedder = AsyncMock()
        mock_embedder.embed_query = AsyncMock(return_value=[0.5] * 768)

        recall = MemoryRecall(db=db, embedder=mock_embedder)
        results = await recall.search("timezone")

        contents = [r.content for r in results]
        assert "Low confidence timezone" not in contents
        assert "High confidence timezone" in contents

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
