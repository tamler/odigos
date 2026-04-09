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
    # memory_vec is a virtual table requiring sqlite-vec extension — skip if unavailable
    try:
        await db.execute(
            "INSERT INTO memory_vec (id, embedding) VALUES (?, ?)",
            (mem_id, _serialize_f32(vec)),
        )
    except Exception:
        pass
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
