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
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_entries'"
        )
        assert row is None
        row2 = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_facts'"
        )
        assert row2 is None
