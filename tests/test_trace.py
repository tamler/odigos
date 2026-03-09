import json
import uuid
from unittest.mock import AsyncMock

import pytest

from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.trace import Tracer
from odigos.db import Database
from odigos.providers.base import LLMResponse, ToolCall
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


class TestTracer:
    async def test_emit_inserts_row(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        trace_id = await tracer.emit("step_start", "conv-1", {"message": "hello"})

        row = await db.fetch_one("SELECT * FROM traces WHERE id = ?", (trace_id,))
        assert row is not None
        assert row["event_type"] == "step_start"
        assert row["conversation_id"] == "conv-1"
        data = json.loads(row["data_json"])
        assert data["message"] == "hello"

    async def test_emit_returns_id(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        trace_id = await tracer.emit("response", "conv-1", {})
        assert isinstance(trace_id, str)
        assert len(trace_id) > 0

    async def test_emit_without_conversation(self, db):
        tracer = Tracer(db)
        trace_id = await tracer.emit("heartbeat_tick", None, {"todos": 3})

        row = await db.fetch_one("SELECT * FROM traces WHERE id = ?", (trace_id,))
        assert row is not None
        assert row["conversation_id"] is None
        assert row["event_type"] == "heartbeat_tick"

    async def test_emit_serializes_complex_data(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        data = {"tools": ["search", "scrape"], "nested": {"key": "value"}, "count": 42}
        trace_id = await tracer.emit("tool_call", "conv-1", data)

        row = await db.fetch_one("SELECT * FROM traces WHERE id = ?", (trace_id,))
        parsed = json.loads(row["data_json"])
        assert parsed["tools"] == ["search", "scrape"]
        assert parsed["nested"]["key"] == "value"
        assert parsed["count"] == 42

    async def test_emit_with_empty_data(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        trace_id = await tracer.emit("warning", "conv-1", {})

        row = await db.fetch_one("SELECT * FROM traces WHERE id = ?", (trace_id,))
        assert row is not None
        assert json.loads(row["data_json"]) == {}

    async def test_emit_has_timestamp(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        trace_id = await tracer.emit("response", "conv-1", {})

        row = await db.fetch_one("SELECT * FROM traces WHERE id = ?", (trace_id,))
        assert row["timestamp"] is not None

    async def test_action_log_table_dropped(self, db):
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='action_log'"
        )
        assert row is None

    async def test_traces_table_exists(self, db):
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='traces'"
        )
        assert row is not None


class TestTracerInExecutor:
    async def test_tool_call_emits_trace(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)

        mock_tool = AsyncMock(spec=BaseTool)
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        mock_tool.execute = AsyncMock(
            return_value=ToolResult(success=True, data="results here")
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        mock_provider = AsyncMock()
        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "test"})],
            ),
            LLMResponse(
                content="Found it", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
            ),
        ]

        assembler = ContextAssembler(
            db=db, agent_name="Test", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(
            provider=mock_provider,
            context_assembler=assembler,
            tool_registry=registry,
            db=db,
            tracer=tracer,
        )

        await executor.execute("conv-1", "search for test")

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'tool_result'"
        )
        assert len(rows) == 1
        data = json.loads(rows[0]["data_json"])
        assert data["tool"] == "web_search"
        assert data["success"] is True

    async def test_failed_tool_emits_error_trace(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)

        mock_tool = AsyncMock(spec=BaseTool)
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {}}
        mock_tool.execute = AsyncMock(
            return_value=ToolResult(success=False, data="", error="network timeout")
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        mock_provider = AsyncMock()
        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={})],
            ),
            LLMResponse(
                content="Failed", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
            ),
        ]

        assembler = ContextAssembler(
            db=db, agent_name="Test", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(
            provider=mock_provider,
            context_assembler=assembler,
            tool_registry=registry,
            db=db,
            tracer=tracer,
        )

        await executor.execute("conv-1", "search")

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'tool_result'"
        )
        assert len(rows) == 1
        data = json.loads(rows[0]["data_json"])
        assert data["success"] is False
        assert data["error"] == "network timeout"

    async def test_skill_context_in_tool_trace(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)

        mock_tool = AsyncMock(spec=BaseTool)
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {}}
        mock_tool.execute = AsyncMock(
            return_value=ToolResult(success=True, data="ok")
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        mock_provider = AsyncMock()
        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={})],
            ),
            LLMResponse(
                content="Done", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
            ),
        ]

        assembler = ContextAssembler(
            db=db, agent_name="Test", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(
            provider=mock_provider,
            context_assembler=assembler,
            tool_registry=registry,
            db=db,
            tracer=tracer,
        )

        # Inject active skill state after execute() resets it but before tool runs
        responses = [
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={})],
            ),
            LLMResponse(
                content="Done", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
            ),
        ]
        call_count = 0

        async def complete_with_skill_injection(messages, **kwargs):
            nonlocal call_count
            response = responses[call_count]
            call_count += 1
            if call_count == 1:
                executor._active_skill_name = "research"
                executor._active_skill_tools = {"web_search", "read_page"}
            return response

        mock_provider.complete.side_effect = complete_with_skill_injection

        await executor.execute("conv-1", "search")

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'tool_result'"
        )
        data = json.loads(rows[0]["data_json"])
        assert data["active_skill"] == "research"
