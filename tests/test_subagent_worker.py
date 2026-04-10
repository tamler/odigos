"""Tests for sub-agent heartbeat worker."""
from __future__ import annotations

import json
import uuid
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


def _make_hb(db) -> MagicMock:
    hb = MagicMock()
    hb.db = db
    hb.llm_provider = AsyncMock()
    hb.background_model = "test/model"
    hb.budget_tracker = MagicMock()
    hb.budget_tracker.is_within_budget = AsyncMock(return_value=True)
    hb.notifier = MagicMock()
    hb.notifier.create = AsyncMock()
    hb.message_bus = MagicMock()
    hb.message_bus.publish = AsyncMock()
    return hb


async def _seed_pending_task(db, persona="researcher", concurrency_key="default") -> str:
    task_id = str(uuid.uuid4())
    params = {"task": "Do something", "persona": persona}
    await db.execute(
        "INSERT INTO tasks "
        "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
        "arguments_json, max_retries, retry_count) "
        "VALUES (?, 'subagent', 'pending', ?, ?, 600, ?, 2, 0)",
        (task_id, persona, concurrency_key, json.dumps(params)),
    )
    return task_id


class TestWorkerGating:
    async def test_skips_when_over_budget(self, db):
        from odigos.core.heartbeat import subagent_worker

        await _seed_pending_task(db)
        hb = _make_hb(db)
        hb.budget_tracker.is_within_budget = AsyncMock(return_value=False)

        started = await subagent_worker.poll_subagent_tasks(hb)
        assert started == 0

    async def test_skips_when_at_concurrency_limit(self, db):
        from odigos.core.heartbeat import subagent_worker

        # Seed 3 running tasks at default concurrency (limit=3)
        for _ in range(3):
            task_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO tasks "
                "(id, type, status, concurrency_key, max_runtime_seconds, "
                "arguments_json, started_at) "
                "VALUES (?, 'subagent', 'running', 'default', 600, '{}', datetime('now'))",
                (task_id,),
            )

        # Seed a pending task
        await _seed_pending_task(db, concurrency_key="default")

        hb = _make_hb(db)
        started = await subagent_worker.poll_subagent_tasks(hb)
        assert started == 0

    async def test_skips_cancelled_tasks(self, db):
        from odigos.core.heartbeat import subagent_worker

        task_id = await _seed_pending_task(db)
        await db.execute(
            "UPDATE tasks SET cancel_requested = 1 WHERE id = ?", (task_id,),
        )

        hb = _make_hb(db)
        started = await subagent_worker.poll_subagent_tasks(hb)
        assert started == 0


class TestWorkerOrphanRecovery:
    async def test_orphaned_running_task_marked_failed(self, db):
        from odigos.core.heartbeat import subagent_worker

        # Create a task that appears to have started 20 minutes ago (past timeout)
        task_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, concurrency_key, max_runtime_seconds, "
            "arguments_json, started_at) "
            "VALUES (?, 'subagent', 'running', 'default', 600, '{}', "
            "datetime('now', '-20 minutes'))",
            (task_id,),
        )

        hb = _make_hb(db)
        recovered = await subagent_worker.recover_orphaned_tasks(hb)
        assert recovered >= 1

        row = await db.fetch_one(
            "SELECT status, error FROM tasks WHERE id = ?", (task_id,),
        )
        assert row["status"] == "failed"
        assert "interrupted" in row["error"].lower()
