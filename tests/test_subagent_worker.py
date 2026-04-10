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


def _make_hb(db, manager_execute=None) -> MagicMock:
    """Build a mock Heartbeat with a subagent_manager.

    Args:
        db: real Database instance
        manager_execute: optional async callable to use as the manager's
            execute_task() implementation. Defaults to a no-op.
    """
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

    # Attach a SubagentManager mock. The worker delegates execution to it.
    manager = MagicMock()
    manager.db = db
    if manager_execute is None:
        async def _noop(task_row):
            return
        manager_execute = _noop
    manager.execute_task = AsyncMock(side_effect=manager_execute)
    hb.subagent_manager = manager
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
    async def test_execution_writes_result(self, db):
        """Worker delegates to manager, manager writes result to DB."""
        from odigos.core.heartbeat import subagent_worker

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

        # execute_task mock writes a "done" row directly
        async def fake_execute(task_row):
            await db.execute(
                "UPDATE tasks SET status = 'done', result_json = ? WHERE id = ?",
                (json.dumps({"result": "TL;DR: This is a summary."}), task_row["id"]),
            )

        hb = _make_hb(db, manager_execute=fake_execute)
        started = await subagent_worker.poll_subagent_tasks(hb)
        assert started == 1

        # Wait for the background asyncio.Task to finish
        running = subagent_worker._running_tasks.get(task_id)
        if running:
            await running

        row = await db.fetch_one(
            "SELECT status, result_json FROM tasks WHERE id = ?", (task_id,),
        )
        assert row["status"] == "done"
        result = json.loads(row["result_json"])
        assert "summary" in result["result"].lower()

    async def test_worker_calls_manager_execute_task(self, db):
        """The worker delegates to SubagentManager.execute_task per dispatched row."""
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
        await subagent_worker.poll_subagent_tasks(hb)
        running = subagent_worker._running_tasks.get(task_id)
        if running:
            await running

        # The worker should have called manager.execute_task with the task row
        assert hb.subagent_manager.execute_task.called
        call_args = hb.subagent_manager.execute_task.call_args
        passed_row = call_args[0][0]
        assert passed_row["id"] == task_id


class TestChaining:
    """Chaining is internal to SubagentManager. Test it directly."""

    async def _make_manager(self, db, llm_content: str = "done"):
        from odigos.core.subagent import SubagentManager
        from odigos.tools.registry import ToolRegistry

        provider = AsyncMock()
        provider.complete = AsyncMock(return_value=_make_llm_response(llm_content))
        return SubagentManager(
            db=db,
            llm_provider=provider,
            tool_registry=ToolRegistry(),
        )

    async def test_on_complete_dispatches_follow_up(self, db):
        """When a task has on_complete, a chained task is created on success."""
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
            "VALUES (?, 'subagent', 'running', 'researcher', 'default', 600, ?, 2, 0)",
            (task_id, json.dumps(params)),
        )

        manager = await self._make_manager(db, llm_content="Research complete.")
        row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        await manager.execute_task(dict(row))

        # Original task should be done
        updated = await db.fetch_one("SELECT status, result_json FROM tasks WHERE id = ?", (task_id,))
        assert updated["status"] == "done"

        # Chained task should exist with parent_task_id pointing to original
        chained_rows = await db.fetch_all(
            "SELECT * FROM tasks WHERE parent_task_id = ?", (task_id,),
        )
        assert len(chained_rows) == 1
        chained = chained_rows[0]
        assert chained["persona"] == "summarizer"
        chained_params = json.loads(chained["arguments_json"])
        assert chained_params["input_artifact"] == "Research complete."

    async def test_on_failure_dispatches_recovery(self, db):
        """When a task has on_failure, a recovery task is created on exception."""
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
            "VALUES (?, 'subagent', 'running', 'researcher', 'default', 600, ?, 0, 0)",
            (task_id, json.dumps(params)),
        )

        # Build a manager whose _run_inline raises
        from odigos.core.subagent import SubagentManager
        from odigos.tools.registry import ToolRegistry

        provider = AsyncMock()
        provider.complete = AsyncMock(side_effect=RuntimeError("network error"))
        manager = SubagentManager(
            db=db,
            llm_provider=provider,
            tool_registry=ToolRegistry(),
        )

        row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        await manager.execute_task(dict(row))

        # Original task should be failed
        updated = await db.fetch_one(
            "SELECT status, error FROM tasks WHERE id = ?", (task_id,),
        )
        assert updated["status"] == "failed"

        # Recovery task should exist
        failure_rows = await db.fetch_all(
            "SELECT * FROM tasks WHERE parent_task_id = ? AND type = 'subagent'",
            (task_id,),
        )
        assert len(failure_rows) == 1
        assert failure_rows[0]["persona"] == "summarizer"


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
