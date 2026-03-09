import asyncio
from unittest.mock import AsyncMock

import pytest

from odigos.core.subagent import MAX_CONCURRENT_PER_CONVERSATION, SubagentManager
from odigos.db import Database
from odigos.providers.base import LLMResponse
from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.registry import ToolRegistry


@pytest.fixture
async def db(tmp_db_path: str):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


async def _seed_conversation(db: Database, conversation_id: str) -> None:
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conversation_id, "test"),
    )


def _make_mock_provider(response_content: str = "Done") -> AsyncMock:
    provider = AsyncMock()
    provider.complete = AsyncMock(
        return_value=LLMResponse(
            content=response_content,
            model="test",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )
    )
    return provider


def _make_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()

    web_search = AsyncMock(spec=BaseTool)
    web_search.name = "web_search"
    web_search.description = "Search the web"
    web_search.parameters_schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    web_search.execute = AsyncMock(return_value=ToolResult(success=True, data="results"))
    registry.register(web_search)

    spawn = AsyncMock(spec=BaseTool)
    spawn.name = "spawn_subagent"
    spawn.description = "Spawn a subagent"
    spawn.parameters_schema = {"type": "object", "properties": {"instruction": {"type": "string"}}}
    spawn.execute = AsyncMock(return_value=ToolResult(success=True, data="spawned"))
    registry.register(spawn)

    return registry


class TestSubagentManager:
    async def test_spawn_creates_db_row(self, db):
        await _seed_conversation(db, "conv-1")
        provider = _make_mock_provider()
        registry = _make_tool_registry()
        mgr = SubagentManager(db=db, provider=provider, tool_registry=registry)

        sid = await mgr.spawn("Do something", "conv-1")

        row = await db.fetch_one("SELECT * FROM subagent_tasks WHERE id = ?", (sid,))
        assert row is not None
        assert row["parent_conversation_id"] == "conv-1"
        assert row["instruction"] == "Do something"
        assert row["status"] == "running"

    async def test_spawn_returns_unique_ids(self, db):
        await _seed_conversation(db, "conv-1")
        provider = _make_mock_provider()
        registry = _make_tool_registry()
        mgr = SubagentManager(db=db, provider=provider, tool_registry=registry)

        id1 = await mgr.spawn("Task A", "conv-1")
        id2 = await mgr.spawn("Task B", "conv-1")
        assert id1 != id2

    async def test_spawn_enforces_max_concurrent(self, db):
        await _seed_conversation(db, "conv-1")

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(10)
            return LLMResponse(
                content="Done", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001
            )

        provider = AsyncMock()
        provider.complete = slow_complete
        registry = _make_tool_registry()
        mgr = SubagentManager(db=db, provider=provider, tool_registry=registry)

        for i in range(MAX_CONCURRENT_PER_CONVERSATION):
            await mgr.spawn(f"Task {i}", "conv-1")

        with pytest.raises(ValueError, match="Max concurrent subagents"):
            await mgr.spawn("One too many", "conv-1")

        # Clean up background tasks
        for task in mgr._tasks.values():
            task.cancel()
        await asyncio.gather(*mgr._tasks.values(), return_exceptions=True)

    async def test_spawn_max_concurrent_per_conversation(self, db):
        await _seed_conversation(db, "conv-1")
        await _seed_conversation(db, "conv-2")

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(10)
            return LLMResponse(
                content="Done", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001
            )

        provider = AsyncMock()
        provider.complete = slow_complete
        registry = _make_tool_registry()
        mgr = SubagentManager(db=db, provider=provider, tool_registry=registry)

        for i in range(MAX_CONCURRENT_PER_CONVERSATION):
            await mgr.spawn(f"Task {i}", "conv-1")

        # conv-2 should still allow spawning
        sid = await mgr.spawn("Task for conv-2", "conv-2")
        assert sid is not None

        # Clean up background tasks
        for task in mgr._tasks.values():
            task.cancel()
        await asyncio.gather(*mgr._tasks.values(), return_exceptions=True)


class TestSubagentExecution:
    async def test_completed_result_stored(self, db):
        await _seed_conversation(db, "conv-1")
        provider = _make_mock_provider("Research complete")
        registry = _make_tool_registry()
        mgr = SubagentManager(db=db, provider=provider, tool_registry=registry)

        sid = await mgr.spawn("Research topic X", "conv-1")
        await mgr._tasks[sid]

        row = await db.fetch_one("SELECT * FROM subagent_tasks WHERE id = ?", (sid,))
        assert row["status"] == "completed"
        assert row["result"] == "Research complete"
        assert row["completed_at"] is not None

    async def test_timeout_produces_failed(self, db):
        await _seed_conversation(db, "conv-1")

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(10)
            return LLMResponse(
                content="Done", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001
            )

        provider = AsyncMock()
        provider.complete = slow_complete
        registry = _make_tool_registry()
        mgr = SubagentManager(db=db, provider=provider, tool_registry=registry)

        sid = await mgr.spawn("Slow task", "conv-1", timeout=1)
        await mgr._tasks[sid]

        row = await db.fetch_one("SELECT * FROM subagent_tasks WHERE id = ?", (sid,))
        assert row["status"] == "failed"
        assert row["result"] == "Subagent timed out"

    async def test_exception_produces_failed(self, db):
        await _seed_conversation(db, "conv-1")
        provider = AsyncMock()
        provider.complete = AsyncMock(side_effect=RuntimeError("LLM exploded"))
        registry = _make_tool_registry()
        mgr = SubagentManager(db=db, provider=provider, tool_registry=registry)

        sid = await mgr.spawn("Doomed task", "conv-1")
        await mgr._tasks[sid]

        row = await db.fetch_one("SELECT * FROM subagent_tasks WHERE id = ?", (sid,))
        assert row["status"] == "failed"
        assert "LLM exploded" in row["result"]


class TestSubagentDelivery:
    async def test_get_completed_returns_undelivered(self, db):
        await _seed_conversation(db, "conv-1")
        provider = _make_mock_provider()
        registry = _make_tool_registry()
        mgr = SubagentManager(db=db, provider=provider, tool_registry=registry)

        sid = await mgr.spawn("Quick task", "conv-1")
        await mgr._tasks[sid]

        completed = await mgr.get_completed_all()
        assert len(completed) == 1
        assert completed[0]["id"] == sid

    async def test_mark_delivered(self, db):
        await _seed_conversation(db, "conv-1")
        provider = _make_mock_provider()
        registry = _make_tool_registry()
        mgr = SubagentManager(db=db, provider=provider, tool_registry=registry)

        sid = await mgr.spawn("Quick task", "conv-1")
        await mgr._tasks[sid]

        await mgr.mark_delivered(sid)

        completed = await mgr.get_completed_all()
        assert len(completed) == 0

    async def test_get_completed_excludes_running(self, db):
        await _seed_conversation(db, "conv-1")

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(10)
            return LLMResponse(
                content="Done", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001
            )

        provider = AsyncMock()
        provider.complete = slow_complete
        registry = _make_tool_registry()
        mgr = SubagentManager(db=db, provider=provider, tool_registry=registry)

        await mgr.spawn("Slow task", "conv-1")

        completed = await mgr.get_completed_all()
        assert len(completed) == 0

        # Clean up background tasks
        for task in mgr._tasks.values():
            task.cancel()
        await asyncio.gather(*mgr._tasks.values(), return_exceptions=True)


class TestSubagentToolExclusion:
    def test_restricted_registry_excludes_spawn(self):
        registry = _make_tool_registry()
        provider = _make_mock_provider()
        mgr = SubagentManager(db=AsyncMock(), provider=provider, tool_registry=registry)

        restricted = mgr._build_restricted_registry()

        tool_names = [t.name for t in restricted.list()]
        assert "spawn_subagent" not in tool_names
        assert "web_search" in tool_names
