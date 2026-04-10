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


from odigos.providers.base import LLMResponse


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=50, tokens_out=100, cost_usd=0.001,
    )


class TestWorkerExecution:
    async def test_execution_writes_result(self, db, tmp_path, monkeypatch):
        from odigos.core.heartbeat import subagent_worker

        # Seed a pending task
        task_id = str(uuid.uuid4())
        params = {
            "task": "Summarize this",
            "persona": "summarizer",
            "context_facts": [],
        }
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json, max_retries, retry_count) "
            "VALUES (?, 'subagent', 'pending', 'summarizer', 'default', 300, ?, 2, 0)",
            (task_id, json.dumps(params)),
        )

        hb = _make_hb(db)
        hb.llm_provider.complete = AsyncMock(
            return_value=_make_llm_response("TL;DR: This is a summary."),
        )

        # Patch the execution helper to use the mock LLM directly
        async def mock_execute_inline(hb, params, task_id, workspace_root):
            return {
                "result": "TL;DR: This is a summary.",
                "artifact_path": None,
                "duration_ms": 100,
                "cost_usd": 0.001,
                "tool_calls": [],
            }
        monkeypatch.setattr(
            subagent_worker, "_execute_subagent_inline", mock_execute_inline,
        )

        started = await subagent_worker.poll_subagent_tasks(hb)
        assert started == 1

        # Wait for the background asyncio.Task to complete
        import asyncio as _aio
        running = subagent_worker._running_tasks.get(task_id)
        if running:
            await running

        row = await db.fetch_one(
            "SELECT status, result_json FROM tasks WHERE id = ?", (task_id,),
        )
        assert row["status"] == "done"
        result = json.loads(row["result_json"])
        assert "summary" in result["result"].lower()

    async def test_execution_creates_notification_on_done(self, db, monkeypatch):
        from odigos.core.heartbeat import subagent_worker

        task_id = str(uuid.uuid4())
        params = {"task": "Test", "persona": "summarizer"}
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json, max_retries, retry_count) "
            "VALUES (?, 'subagent', 'pending', 'summarizer', 'default', 300, ?, 2, 0)",
            (task_id, json.dumps(params)),
        )

        hb = _make_hb(db)

        async def mock_execute_inline(hb, params, task_id, workspace_root):
            return {
                "result": "Done.",
                "artifact_path": None,
                "duration_ms": 50,
                "cost_usd": 0.0,
                "tool_calls": [],
            }
        monkeypatch.setattr(
            subagent_worker, "_execute_subagent_inline", mock_execute_inline,
        )

        await subagent_worker.poll_subagent_tasks(hb)
        running = subagent_worker._running_tasks.get(task_id)
        if running:
            await running

        # Verify notification was created
        assert hb.notifier.create.called


class TestChaining:
    async def test_on_complete_dispatches_follow_up(self, db, monkeypatch):
        from odigos.core.heartbeat import subagent_worker

        # Seed a pending task with on_complete
        task_id = str(uuid.uuid4())
        params = {
            "task": "Research X",
            "persona": "researcher",
            "on_complete": {
                "persona": "summarizer",
                "task": "Summarize the research",
                "input_from": "result",
            },
        }
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json, max_retries, retry_count) "
            "VALUES (?, 'subagent', 'pending', 'researcher', 'default', 600, ?, 2, 0)",
            (task_id, json.dumps(params)),
        )

        hb = _make_hb(db)

        async def mock_execute_inline(hb, params, task_id, workspace_root):
            return {
                "result": "Research complete.",
                "artifact_path": None,
                "duration_ms": 50,
                "cost_usd": 0.0,
                "tool_calls": [],
            }
        monkeypatch.setattr(
            subagent_worker, "_execute_subagent_inline", mock_execute_inline,
        )

        await subagent_worker.poll_subagent_tasks(hb)
        running = subagent_worker._running_tasks.get(task_id)
        if running:
            await running

        # Verify a chained task was created
        chained_rows = await db.fetch_all(
            "SELECT * FROM tasks WHERE parent_task_id = ?", (task_id,),
        )
        assert len(chained_rows) == 1
        chained = chained_rows[0]
        assert chained["persona"] == "summarizer"
        chained_params = json.loads(chained["arguments_json"])
        assert chained_params["input_artifact"] == "Research complete."

    async def test_on_failure_dispatches_recovery(self, db, monkeypatch):
        from odigos.core.heartbeat import subagent_worker

        task_id = str(uuid.uuid4())
        params = {
            "task": "Research X",
            "persona": "researcher",
            "on_failure": {
                "persona": "summarizer",
                "task": "Explain why the research failed",
            },
        }
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json, max_retries, retry_count) "
            "VALUES (?, 'subagent', 'pending', 'researcher', 'default', 600, ?, 0, 0)",
            (task_id, json.dumps(params)),
        )

        hb = _make_hb(db)

        async def mock_execute_inline(hb, params, task_id, workspace_root):
            raise RuntimeError("network error during research")

        monkeypatch.setattr(
            subagent_worker, "_execute_subagent_inline", mock_execute_inline,
        )

        await subagent_worker.poll_subagent_tasks(hb)
        running = subagent_worker._running_tasks.get(task_id)
        if running:
            await running

        # Verify the original task is failed
        row = await db.fetch_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
        assert row["status"] == "failed"

        # Verify on_failure task was created
        failure_rows = await db.fetch_all(
            "SELECT * FROM tasks WHERE parent_task_id = ? AND type = 'subagent'",
            (task_id,),
        )
        assert len(failure_rows) == 1


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
