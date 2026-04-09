"""Tests for structured memory system."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.db import Database
from odigos.memory.classifier import ClassificationResult
from odigos.memory.store import MemoryRecord, MemoryStore
from odigos.providers.base import LLMResponse


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test/model",
        tokens_in=50,
        tokens_out=100,
        cost_usd=0.001,
    )


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
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_entries'"
        )
        assert row is None
        row2 = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_facts'"
        )
        assert row2 is None


class TestMemoryStore:
    async def test_store_inserts_memory_and_embedding(self, db):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                json.dumps({
                    "memory_type": "fact",
                    "keywords": ["timezone", "PST"],
                    "tags": ["user-profile"],
                    "context_description": "User is in PST timezone.",
                })
            )
        )

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 768)

        store = MemoryStore(
            db=db,
            llm_client=mock_llm,
            embedder=mock_embedder,
            prompts_dir="data/prompts",
        )
        record = await store.store(
            content="My timezone is PST",
            source_type="conversation",
            source_id="conv-1",
        )

        assert record is not None
        assert record.memory_type == "fact"

        row = await db.fetch_one("SELECT * FROM memories WHERE id = ?", (record.id,))
        assert row is not None
        assert row["memory_type"] == "fact"
        assert row["content"] == "My timezone is PST"
        assert json.loads(row["keywords_json"]) == ["timezone", "PST"]

    async def test_store_deduplicates_exact_match(self, db):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                json.dumps({
                    "memory_type": "fact",
                    "keywords": ["timezone"],
                    "tags": [],
                    "context_description": "Timezone info.",
                })
            )
        )

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 768)
        mock_embedder.embed_query = AsyncMock(return_value=[0.1] * 768)

        store = MemoryStore(
            db=db,
            llm_client=mock_llm,
            embedder=mock_embedder,
            prompts_dir="data/prompts",
        )

        r1 = await store.store("My timezone is PST", "conversation", "conv-1")
        r2 = await store.store("My timezone is PST", "conversation", "conv-2")

        assert r1.id == r2.id

        rows = await db.fetch_all("SELECT * FROM memories")
        assert len(rows) == 1

    async def test_store_with_bulk_skips_linking(self, db):
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                json.dumps({
                    "memory_type": "general",
                    "keywords": ["docker"],
                    "tags": ["infra"],
                    "context_description": "Docker content.",
                })
            )
        )

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 768)

        store = MemoryStore(
            db=db,
            llm_client=mock_llm,
            embedder=mock_embedder,
            prompts_dir="data/prompts",
        )
        record = await store.store(
            "Docker deployment steps...", "document", "doc-1", bulk=True,
        )

        assert record is not None
        links = await db.fetch_all("SELECT * FROM memory_links")
        assert len(links) == 0
