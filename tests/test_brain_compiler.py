"""Tests for brain compilation trigger logic."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


async def _set_kv(db, key, value):
    await db.execute(
        "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
        (key, value),
    )


async def _seed_memories(db, count: int, created_after: str | None = None) -> None:
    for i in range(count):
        mem_id = str(uuid.uuid4())
        created = created_after or datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO memories (id, content, memory_type, source_type, source_id, "
            "confidence, created_at, updated_at) "
            "VALUES (?, ?, 'fact', 'conversation', 'c1', 0.8, ?, ?)",
            (mem_id, f"Fact {i}", created, created),
        )


async def _seed_entity(db) -> str:
    eid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO entities (id, type, name) VALUES (?, 'person', 'TestEntity')",
        (eid,),
    )
    return eid


class TestShouldCompile:
    async def test_returns_true_on_first_compile_with_entities(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        await _seed_entity(db)
        assert await should_compile(db) is True

    async def test_returns_false_when_no_entities(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        assert await should_compile(db) is False

    async def test_returns_false_when_pending_task_exists(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        await _seed_entity(db)
        await _set_kv(db, "brain_compile_task", "some-task-id")
        assert await should_compile(db) is False

    async def test_returns_true_when_enough_new_memories(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await _set_kv(db, "brain_last_compiled", past)
        await _seed_memories(db, 12)
        assert await should_compile(db) is True

    async def test_returns_false_when_too_few_memories(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        past = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        await _set_kv(db, "brain_last_compiled", past)
        await _seed_memories(db, 3)
        assert await should_compile(db) is False

    async def test_returns_true_on_24h_fallback(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        await _set_kv(db, "brain_last_compiled", old)
        await _seed_memories(db, 1)
        assert await should_compile(db) is True


class TestBuildContext:
    async def test_context_includes_memories_and_slugs(self, db, tmp_path):
        from odigos.core.heartbeat.brain_compiler import build_compilation_context

        await _seed_memories(db, 5)
        await _seed_entity(db)

        # Create a fake brain dir with one entity file
        brain_dir = tmp_path / "brain" / "entities"
        brain_dir.mkdir(parents=True)
        (brain_dir / "test-entity.md").write_text("# Test Entity\n\nSome facts.")

        ctx = await build_compilation_context(db, brain_dir=str(tmp_path / "brain"))
        assert "existing_slugs" in ctx
        assert "test-entity" in ctx["existing_slugs"]
        assert len(ctx["new_memories"]) > 0
