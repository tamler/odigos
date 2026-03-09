import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from odigos.channels.base import UniversalMessage
from odigos.core.agent import Agent
from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.reflector import Reflector
from odigos.core.trace import HOOK_TIMEOUT, Tracer
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


def _make_message(conversation_id: str, content: str) -> UniversalMessage:
    chat_id = conversation_id.split(":", 1)[-1] if ":" in conversation_id else conversation_id
    return UniversalMessage(
        id=str(uuid.uuid4()),
        channel="test",
        sender="user",
        content=content,
        timestamp=datetime.now(timezone.utc),
        metadata={"chat_id": chat_id},
    )


class TestTracerInAgent:
    async def test_step_start_traced(self, db):
        await _seed_conversation(db, "test:conv-1")
        tracer = Tracer(db)

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(
            return_value=LLMResponse(
                content="Hello!", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
            )
        )

        agent = Agent(db=db, provider=mock_provider, tracer=tracer)

        msg = _make_message("test:conv-1", "hi there")
        await agent.handle_message(msg)

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'step_start'"
        )
        assert len(rows) == 1
        data = json.loads(rows[0]["data_json"])
        assert "hi there" in data["message_preview"]

    async def test_response_traced(self, db):
        await _seed_conversation(db, "test:conv-1")
        tracer = Tracer(db)

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(
            return_value=LLMResponse(
                content="Hello!", model="test-model", tokens_in=10, tokens_out=5, cost_usd=0.001,
            )
        )

        agent = Agent(db=db, provider=mock_provider, tracer=tracer)

        msg = _make_message("test:conv-1", "hi")
        await agent.handle_message(msg)

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'response'"
        )
        assert len(rows) == 1
        data = json.loads(rows[0]["data_json"])
        assert data["model"] == "test-model"
        assert data["tokens_in"] == 10
        assert data["cost_usd"] == 0.001

    async def test_timeout_traced(self, db):
        await _seed_conversation(db, "test:conv-1")
        tracer = Tracer(db)

        mock_provider = AsyncMock()

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(10)
            return LLMResponse(content="late", model="test", tokens_in=0, tokens_out=0, cost_usd=0)

        mock_provider.complete = slow_complete

        agent = Agent(db=db, provider=mock_provider, tracer=tracer, run_timeout=1)

        msg = _make_message("test:conv-1", "hi")
        await agent.handle_message(msg)

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'timeout'"
        )
        assert len(rows) == 1

    async def test_budget_exceeded_traced(self, db):
        await _seed_conversation(db, "test:conv-1")
        tracer = Tracer(db)

        mock_provider = AsyncMock()
        mock_budget = AsyncMock()
        mock_budget.check_budget = AsyncMock(
            return_value=AsyncMock(within_budget=False)
        )

        agent = Agent(
            db=db, provider=mock_provider, tracer=tracer,
            budget_tracker=mock_budget,
        )

        msg = _make_message("test:conv-1", "hi")
        await agent.handle_message(msg)

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'budget_exceeded'"
        )
        assert len(rows) == 1


class TestTracerInReflector:
    async def test_reflection_traced(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        reflector = Reflector(db, tracer=tracer)

        response = LLMResponse(
            content="Here is my answer.",
            model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
        )
        await reflector.reflect("conv-1", response)

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'reflection'"
        )
        assert len(rows) == 1

    async def test_correction_detected_traced(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        mock_corrections = AsyncMock()
        mock_corrections.store = AsyncMock(return_value="corr-1")
        reflector = Reflector(db, corrections_manager=mock_corrections, tracer=tracer)

        correction_data = {
            "original": "wrong",
            "correction": "right",
            "category": "accuracy",
            "context": "test",
        }
        content = f"Response.\n<!--correction\n{json.dumps(correction_data)}\n-->"
        response = LLMResponse(
            content=content, model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
        )
        await reflector.reflect("conv-1", response)

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'correction_detected'"
        )
        assert len(rows) == 1
        data = json.loads(rows[0]["data_json"])
        assert data["category"] == "accuracy"

    async def test_entity_extracted_traced(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        reflector = Reflector(db, tracer=tracer)

        entities = [{"name": "Alice", "type": "person", "relationship": "friend", "detail": ""}]
        content = f"Response.\n<!--entities\n{json.dumps(entities)}\n-->"
        response = LLMResponse(
            content=content, model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
        )
        await reflector.reflect("conv-1", response)

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'entity_extracted'"
        )
        assert len(rows) == 1
        data = json.loads(rows[0]["data_json"])
        assert data["count"] == 1


class TestTracerSubscribers:
    async def test_subscribe_receives_event(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        received = []

        async def callback(event_type, conversation_id, data):
            received.append((event_type, conversation_id, data))

        tracer.subscribe("step_start", callback)
        await tracer.emit("step_start", "conv-1", {"key": "value"})

        assert len(received) == 1
        assert received[0] == ("step_start", "conv-1", {"key": "value"})

    async def test_subscribe_only_matching_events(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        received = []

        async def callback(event_type, conversation_id, data):
            received.append(event_type)

        tracer.subscribe("tool_call", callback)
        await tracer.emit("step_start", "conv-1", {})
        await tracer.emit("tool_call", "conv-1", {})

        assert received == ["tool_call"]

    async def test_multiple_subscribers(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        received_a = []
        received_b = []

        async def callback_a(event_type, conversation_id, data):
            received_a.append(event_type)

        async def callback_b(event_type, conversation_id, data):
            received_b.append(event_type)

        tracer.subscribe("step_start", callback_a)
        tracer.subscribe("step_start", callback_b)
        await tracer.emit("step_start", "conv-1", {})

        assert len(received_a) == 1
        assert len(received_b) == 1

    async def test_subscriber_timeout(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)

        async def slow_callback(event_type, conversation_id, data):
            await asyncio.sleep(10)

        tracer.subscribe("step_start", slow_callback)

        start = asyncio.get_event_loop().time()
        trace_id = await tracer.emit("step_start", "conv-1", {"msg": "hi"})
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed < 7
        row = await db.fetch_one("SELECT * FROM traces WHERE id = ?", (trace_id,))
        assert row is not None

    async def test_subscriber_exception_continues(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        received = []

        async def bad_callback(event_type, conversation_id, data):
            raise RuntimeError("boom")

        async def good_callback(event_type, conversation_id, data):
            received.append(event_type)

        tracer.subscribe("step_start", bad_callback)
        tracer.subscribe("step_start", good_callback)
        await tracer.emit("step_start", "conv-1", {})

        assert len(received) == 1

    async def test_clear_subscribers(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)
        received = []

        async def callback(event_type, conversation_id, data):
            received.append(event_type)

        tracer.subscribe("step_start", callback)
        tracer.clear_subscribers()
        await tracer.emit("step_start", "conv-1", {})

        assert len(received) == 0
