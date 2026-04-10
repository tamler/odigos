"""Tests for sub-agent orchestration tools."""
from __future__ import annotations

import json
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


class TestRunSubagentTool:
    async def test_run_subagent_tool_creates_task(self, db):
        from odigos.tools.subagent_tools import RunSubagentTool

        tool = RunSubagentTool(db=db)
        result = await tool.execute({
            "task": "Research LLM memory",
            "persona": "researcher",
        })
        assert result.success is True
        assert "task_id" in result.data.lower() or "dispatched" in result.data.lower()

        # Verify task row exists
        rows = await db.fetch_all("SELECT * FROM tasks WHERE type='subagent'")
        assert len(rows) == 1
        assert rows[0]["persona"] == "researcher"

    async def test_run_subagent_tool_validates_persona(self, db):
        from odigos.tools.subagent_tools import RunSubagentTool

        tool = RunSubagentTool(db=db)
        result = await tool.execute({
            "task": "Do something",
            "persona": "does_not_exist",
        })
        assert result.success is False
        assert "persona" in (result.error or "").lower()


class TestRunParallelSubagentsTool:
    async def test_dispatches_multiple_tasks(self, db):
        from odigos.tools.subagent_tools import RunParallelSubagentsTool

        tool = RunParallelSubagentsTool(db=db)
        result = await tool.execute({
            "tasks": [
                {"task": "Research A", "persona": "researcher"},
                {"task": "Research B", "persona": "researcher"},
                {"task": "Summarize C", "persona": "summarizer"},
            ],
        })
        assert result.success is True

        rows = await db.fetch_all("SELECT * FROM tasks WHERE type='subagent'")
        assert len(rows) == 3


class TestSubagentStatusTool:
    async def test_status_returns_task_state(self, db):
        from odigos.tools.subagent_tools import SubagentStatusTool

        task_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json) "
            "VALUES (?, 'subagent', 'done', 'researcher', 'default', 600, '{}')",
            (task_id,),
        )
        await db.execute(
            "UPDATE tasks SET result_json = ?, duration_ms = 1500, "
            "cost_usd = 0.02 WHERE id = ?",
            (json.dumps({"result": "Final research report"}), task_id),
        )

        tool = SubagentStatusTool(db=db)
        result = await tool.execute({"task_id": task_id})
        assert result.success is True
        # data is a formatted string summary containing the status
        assert "done" in str(result.data).lower()


class TestCancelSubagentTool:
    async def test_cancel_sets_flag(self, db):
        from odigos.tools.subagent_tools import CancelSubagentTool

        task_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json) "
            "VALUES (?, 'subagent', 'pending', 'researcher', 'default', 600, '{}')",
            (task_id,),
        )

        tool = CancelSubagentTool(db=db)
        result = await tool.execute({"task_id": task_id})
        assert result.success is True

        row = await db.fetch_one(
            "SELECT cancel_requested FROM tasks WHERE id = ?", (task_id,),
        )
        assert row["cancel_requested"] == 1
