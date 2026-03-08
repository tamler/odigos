# Observability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a DB-persisted `trace.emit()` system that replaces `action_log` and instruments the full agent lifecycle, providing the foundation for the hook/plugin system.

**Architecture:** A `Tracer` class persists structured events to a `traces` table. It replaces the executor's `_log_action()` and adds tracing to agent, reflector, and heartbeat. The `action_log` table is dropped.

**Tech Stack:** Python, pytest, SQLite

---

### Task 1: Create `traces` migration and `Tracer` class

**Files:**
- Create: `migrations/008_traces.sql`
- Create: `odigos/core/trace.py`
- Create: `tests/test_trace.py`

**Step 1: Write the migration**

Create `migrations/008_traces.sql`:

```sql
CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    timestamp TEXT DEFAULT (datetime('now')),
    conversation_id TEXT REFERENCES conversations(id),
    event_type TEXT NOT NULL,
    data_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_traces_conversation ON traces(conversation_id);
CREATE INDEX IF NOT EXISTS idx_traces_event_type ON traces(event_type);
CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp);

DROP TABLE IF EXISTS action_log;
```

**Step 2: Write failing tests**

Create `tests/test_trace.py`:

```python
import json
import uuid

import pytest

from odigos.core.trace import Tracer
from odigos.db import Database


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
```

**Step 3: Run tests to verify they fail**

Run: `pytest tests/test_trace.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'odigos.core.trace'`

**Step 4: Implement the Tracer class**

Create `odigos/core/trace.py`:

```python
from __future__ import annotations

import json
import logging
import uuid

from odigos.db import Database

logger = logging.getLogger(__name__)


class Tracer:
    """Structured event tracing with DB persistence."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def emit(
        self,
        event_type: str,
        conversation_id: str | None,
        data: dict,
    ) -> str:
        """Emit a trace event. Returns the trace ID."""
        trace_id = str(uuid.uuid4())
        try:
            await self.db.execute(
                "INSERT INTO traces (id, conversation_id, event_type, data_json) "
                "VALUES (?, ?, ?, ?)",
                (trace_id, conversation_id, event_type, json.dumps(data)),
            )
        except Exception:
            logger.debug("Failed to emit trace", exc_info=True)
        return trace_id
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_trace.py -v`
Expected: All pass

**Step 6: Commit**

```bash
git add migrations/008_traces.sql odigos/core/trace.py tests/test_trace.py
git commit -m "feat: add Tracer class and traces migration, drop action_log"
```

---

### Task 2: Replace `_log_action()` in Executor with Tracer

**Files:**
- Modify: `odigos/core/executor.py:14-17` (imports)
- Modify: `odigos/core/executor.py:46-62` (constructor -- add tracer param)
- Modify: `odigos/core/executor.py:207-249` (_execute_tool -- replace _log_action calls)
- Delete: `odigos/core/executor.py:251-274` (_log_action method)
- Delete: `tests/test_action_log.py`
- Modify: `tests/test_trace.py` (add executor integration tests)

**Step 1: Write failing tests**

Add to `tests/test_trace.py`:

```python
from unittest.mock import AsyncMock

from odigos.core.context import ContextAssembler
from odigos.core.executor import Executor
from odigos.core.trace import Tracer
from odigos.providers.base import LLMResponse, ToolCall
from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.registry import ToolRegistry


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
        # Simulate active skill
        executor._active_skill_name = "research"
        executor._active_skill_tools = {"web_search", "read_page"}

        await executor.execute("conv-1", "search")

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'tool_result'"
        )
        data = json.loads(rows[0]["data_json"])
        assert data["active_skill"] == "research"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trace.py::TestTracerInExecutor -v`
Expected: FAIL -- `Executor() got unexpected keyword argument 'tracer'`

**Step 3: Modify executor**

In `odigos/core/executor.py`:

1. Add import in TYPE_CHECKING block:
```python
if TYPE_CHECKING:
    from odigos.core.budget import BudgetStatus, BudgetTracker
    from odigos.core.trace import Tracer
    from odigos.skills.registry import SkillRegistry
    from odigos.tools.registry import ToolRegistry
```

2. Add `tracer` param to `__init__`:
```python
    def __init__(
        self,
        provider: LLMProvider,
        context_assembler: ContextAssembler,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        db: Database | None = None,
        max_tool_turns: int = MAX_TOOL_TURNS,
        budget_tracker: BudgetTracker | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.db = db
        self._max_tool_turns = max_tool_turns
        self.budget_tracker = budget_tracker
        self.tracer = tracer
```

3. Replace `_log_action` calls in `_execute_tool` with `tracer.emit`. The method becomes:

```python
    async def _execute_tool(self, conversation_id: str, tool_call: ToolCall) -> str:
        """Execute a single tool call and return the result string."""
        if not self.tool_registry:
            return "Error: No tool registry available"

        tool = self.tool_registry.get(tool_call.name)
        if not tool:
            error = f"Error: Unknown tool '{tool_call.name}'"
            logger.warning(error)
            await self._emit_trace(conversation_id, "tool_result", {
                "tool": tool_call.name, "success": False, "error": "unknown tool",
            })
            return error

        try:
            args = {**tool_call.arguments, "_conversation_id": conversation_id}
            result = await tool.execute(args)
            await self._emit_trace(conversation_id, "tool_result", {
                "tool": tool_call.name, "success": result.success, "error": result.error,
            })

            # Detect skill activation from structured payload
            if tool_call.name == "activate_skill" and result.success:
                try:
                    payload = json.loads(result.data)
                    if payload.get("__skill_activation__"):
                        self._active_skill_name = payload["skill_name"]
                        self._active_skill_tools = set(payload.get("skill_tools", []))
                        self._pending_skill_prompt = payload["skill_prompt"]
                        return payload.get("message", result.data)
                except (json.JSONDecodeError, KeyError):
                    pass

            if result.success:
                return result.data
            else:
                return f"Error: {result.error}"
        except Exception as e:
            logger.exception("Tool %s raised an exception", tool_call.name)
            await self._emit_trace(conversation_id, "tool_result", {
                "tool": tool_call.name, "success": False, "error": str(e),
            })
            return f"Error: Tool execution failed: {e}"

    async def _emit_trace(
        self, conversation_id: str, event_type: str, data: dict,
    ) -> None:
        """Emit a trace event with skill context."""
        if self._active_skill_name and data.get("tool") != "activate_skill":
            data["active_skill"] = self._active_skill_name
            tool_name = data.get("tool", "")
            if tool_name and tool_name not in self._active_skill_tools:
                data["skill_mismatch"] = True
                data["expected_tools"] = sorted(self._active_skill_tools)
                logger.info(
                    "Tool mismatch: %s called during skill '%s' (expected: %s)",
                    tool_name, self._active_skill_name, self._active_skill_tools,
                )

        if self.tracer:
            await self.tracer.emit(event_type, conversation_id, data)
```

4. Delete the `_log_action` method entirely.

5. Delete `tests/test_action_log.py`.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trace.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add odigos/core/executor.py tests/test_trace.py
git rm tests/test_action_log.py
git commit -m "feat: replace _log_action with Tracer in executor, delete action_log tests"
```

---

### Task 3: Instrument Agent with traces

**Files:**
- Modify: `odigos/core/agent.py:1-26` (imports, TYPE_CHECKING)
- Modify: `odigos/core/agent.py:31-79` (constructor -- add tracer, pass to executor)
- Modify: `odigos/core/agent.py:90-127` (_run -- add trace calls)
- Modify: `tests/test_trace.py` (add agent tests)

**Step 1: Write failing tests**

Add to `tests/test_trace.py`:

```python
from odigos.core.agent import Agent


class TestTracerInAgent:
    async def test_step_start_traced(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(
            return_value=LLMResponse(
                content="Hello!", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
            )
        )

        agent = Agent(db=db, provider=mock_provider, tracer=tracer)

        msg = _make_message("conv-1", "hi there")
        await agent.handle_message(msg)

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'step_start'"
        )
        assert len(rows) == 1
        data = json.loads(rows[0]["data_json"])
        assert "hi there" in data["message_preview"]

    async def test_response_traced(self, db):
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)

        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(
            return_value=LLMResponse(
                content="Hello!", model="test-model", tokens_in=10, tokens_out=5, cost_usd=0.001,
            )
        )

        agent = Agent(db=db, provider=mock_provider, tracer=tracer)

        msg = _make_message("conv-1", "hi")
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
        await _seed_conversation(db, "conv-1")
        tracer = Tracer(db)

        mock_provider = AsyncMock()

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(10)
            return LLMResponse(content="late", model="test", tokens_in=0, tokens_out=0, cost_usd=0)

        mock_provider.complete = slow_complete

        agent = Agent(db=db, provider=mock_provider, tracer=tracer, run_timeout=1)

        msg = _make_message("conv-1", "hi")
        result = await agent.handle_message(msg)

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'timeout'"
        )
        assert len(rows) == 1

    async def test_budget_exceeded_traced(self, db):
        await _seed_conversation(db, "conv-1")
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

        msg = _make_message("conv-1", "hi")
        await agent.handle_message(msg)

        rows = await db.fetch_all(
            "SELECT * FROM traces WHERE event_type = 'budget_exceeded'"
        )
        assert len(rows) == 1
```

Also add the helper at the top of the test file (after `_seed_conversation`):

```python
import asyncio
from datetime import datetime, timezone
from odigos.channels.base import UniversalMessage


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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trace.py::TestTracerInAgent -v`
Expected: FAIL -- `Agent() got unexpected keyword argument 'tracer'`

**Step 3: Modify Agent**

In `odigos/core/agent.py`:

1. Add `Tracer` to TYPE_CHECKING imports:
```python
if TYPE_CHECKING:
    from odigos.core.budget import BudgetTracker
    from odigos.core.trace import Tracer
    from odigos.memory.corrections import CorrectionsManager
    from odigos.memory.manager import MemoryManager
    from odigos.memory.summarizer import ConversationSummarizer
    from odigos.skills.registry import SkillRegistry
    from odigos.tools.registry import ToolRegistry
```

2. Add `tracer` param to `__init__`, pass to Executor:
```python
    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        agent_name: str = "Odigos",
        history_limit: int = 20,
        memory_manager: MemoryManager | None = None,
        personality_path: str = "data/personality.yaml",
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        cost_fetcher: Callable | None = None,
        budget_tracker: BudgetTracker | None = None,
        max_tool_turns: int = 25,
        run_timeout: int = 300,
        summarizer: ConversationSummarizer | None = None,
        corrections_manager: CorrectionsManager | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self.db = db
        self.budget_tracker = budget_tracker
        self.tracer = tracer
        self._max_tool_turns = max_tool_turns
        self._run_timeout = run_timeout
        # ... existing session lock setup ...
        self.executor = Executor(
            provider,
            self.context_assembler,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            db=db,
            max_tool_turns=max_tool_turns,
            budget_tracker=budget_tracker,
            tracer=tracer,
        )
        self.reflector = Reflector(
            db,
            memory_manager=memory_manager,
            cost_fetcher=cost_fetcher,
            corrections_manager=corrections_manager,
            tracer=tracer,
        )
```

3. Add trace calls to `_run`:
```python
    async def _run(self, conversation_id: str, message: UniversalMessage) -> str:
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (message.id, conversation_id, "user", message.content),
        )

        # Trace: step start
        if self.tracer:
            await self.tracer.emit("step_start", conversation_id, {
                "message_preview": message.content[:200],
            })

        # Budget check
        if self.budget_tracker:
            status = await self.budget_tracker.check_budget()
            if not status.within_budget:
                logger.warning("Budget exceeded, returning low-cost response")
                if self.tracer:
                    await self.tracer.emit("budget_exceeded", conversation_id, {})
                return (
                    "I've hit my spending limit for this period. "
                    "I can still help with simple tasks that don't need an LLM call. "
                    "Use /status to see current budget usage."
                )

        try:
            async with asyncio.timeout(self._run_timeout):
                result = await self.executor.execute(conversation_id, message.content)
        except asyncio.TimeoutError:
            logger.warning("Run timed out after %ds for %s", self._run_timeout, conversation_id)
            if self.tracer:
                await self.tracer.emit("timeout", conversation_id, {
                    "timeout_seconds": self._run_timeout,
                })
            return "I ran out of time working on that. Try breaking it into smaller pieces."

        clean_content = await self.reflector.reflect(
            conversation_id,
            result.response,
            user_message=message.content,
        )

        # Trace: response
        if self.tracer:
            await self.tracer.emit("response", conversation_id, {
                "model": result.response.model,
                "tokens_in": result.response.tokens_in,
                "tokens_out": result.response.tokens_out,
                "cost_usd": result.response.cost_usd,
            })

        await self.db.execute(
            "UPDATE conversations SET last_message_at = datetime('now'), "
            "message_count = message_count + 2 WHERE id = ?",
            (conversation_id,),
        )

        return clean_content
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trace.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add odigos/core/agent.py tests/test_trace.py
git commit -m "feat: instrument Agent with trace events"
```

---

### Task 4: Instrument Reflector with traces

**Files:**
- Modify: `odigos/core/reflector.py:14-16` (TYPE_CHECKING imports)
- Modify: `odigos/core/reflector.py:31-41` (constructor -- add tracer)
- Modify: `odigos/core/reflector.py:43-119` (reflect -- add trace calls)
- Modify: `tests/test_trace.py` (add reflector tests)

**Step 1: Write failing tests**

Add to `tests/test_trace.py`:

```python
from odigos.core.reflector import Reflector


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

        import json as json_mod
        correction_data = {
            "original": "wrong",
            "correction": "right",
            "category": "accuracy",
            "context": "test",
        }
        content = f"Response.\\n<!--correction\\n{json_mod.dumps(correction_data)}\\n-->"
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

        import json as json_mod
        entities = [{"name": "Alice", "type": "person", "relationship": "friend", "detail": ""}]
        content = f"Response.\\n<!--entities\\n{json_mod.dumps(entities)}\\n-->"
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trace.py::TestTracerInReflector -v`
Expected: FAIL -- `Reflector() got unexpected keyword argument 'tracer'`

**Step 3: Modify Reflector**

In `odigos/core/reflector.py`:

1. Add `Tracer` to TYPE_CHECKING:
```python
if TYPE_CHECKING:
    from odigos.core.trace import Tracer
    from odigos.memory.corrections import CorrectionsManager
    from odigos.memory.manager import MemoryManager
```

2. Add `tracer` param to `__init__`:
```python
    def __init__(
        self,
        db: Database,
        memory_manager: MemoryManager | None = None,
        cost_fetcher: Callable | None = None,
        corrections_manager: CorrectionsManager | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self.db = db
        self.memory_manager = memory_manager
        self._cost_fetcher = cost_fetcher
        self.corrections_manager = corrections_manager
        self.tracer = tracer
```

3. Add trace calls in `reflect()`:

After entity parsing (line ~59, after `content = ENTITY_PATTERN.sub("", content).rstrip()`):
```python
            if entities and self.tracer:
                await self.tracer.emit("entity_extracted", conversation_id, {
                    "count": len(entities),
                })
```

After correction parsing (line ~73, after the store call):
```python
                    if self.tracer:
                        await self.tracer.emit("correction_detected", conversation_id, {
                            "category": correction_data.get("category", "behavior"),
                        })
```

Before `return content` at the end:
```python
        if self.tracer:
            await self.tracer.emit("reflection", conversation_id, {})
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trace.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add odigos/core/reflector.py tests/test_trace.py
git commit -m "feat: instrument Reflector with trace events"
```

---

### Task 5: Instrument Heartbeat with traces

**Files:**
- Modify: `odigos/core/heartbeat.py:15-19` (TYPE_CHECKING imports)
- Modify: `odigos/core/heartbeat.py:27-48` (constructor -- add tracer)
- Modify: `odigos/core/heartbeat.py:73-87` (_tick -- add trace call)

**Step 1: Implement**

In `odigos/core/heartbeat.py`:

1. Add `Tracer` to TYPE_CHECKING:
```python
if TYPE_CHECKING:
    from odigos.channels.telegram import TelegramChannel
    from odigos.core.agent import Agent
    from odigos.core.goal_store import GoalStore
    from odigos.core.trace import Tracer
    from odigos.providers.base import LLMProvider
```

2. Add `tracer` param to `__init__`:
```python
    def __init__(
        self,
        db: Database,
        agent: Agent,
        telegram_channel: TelegramChannel,
        goal_store: GoalStore,
        provider: LLMProvider,
        interval: float = 30,
        max_todos_per_tick: int = 3,
        idle_think_interval: int = 900,
        tracer: Tracer | None = None,
    ) -> None:
        # ... existing assignments ...
        self.tracer = tracer
```

3. Add trace at end of `_tick`:
```python
    async def _tick(self) -> None:
        if self.paused:
            return

        did_work = False

        # Phase 1: Fire due reminders
        did_work |= await self._fire_reminders()

        # Phase 2: Work on pending todos
        did_work |= await self._work_todos()

        # Phase 3: Idle thoughts (only if nothing ran above)
        if not did_work:
            await self._idle_think()

        if self.tracer:
            await self.tracer.emit("heartbeat_tick", None, {
                "did_work": did_work,
            })
```

**Step 2: Run all tests to verify nothing is broken**

Run: `pytest tests/test_trace.py -v`
Expected: All pass

**Step 3: Commit**

```bash
git add odigos/core/heartbeat.py
git commit -m "feat: instrument Heartbeat with trace events"
```

---

### Task 6: Wire Tracer into main.py and update existing tests

**Files:**
- Modify: `odigos/main.py` (create Tracer, pass to Agent, Heartbeat)
- Delete: `tests/test_action_log.py` (if not already deleted in Task 2)

**Step 1: Implement**

In `odigos/main.py`:

1. Add import:
```python
from odigos.core.trace import Tracer
```

2. Create Tracer after database initialization (after line 58):
```python
    # Initialize tracer
    tracer = Tracer(db=_db)
    logger.info("Tracer initialized")
```

3. Pass to Agent (around line 223):
```python
    agent = Agent(
        db=_db,
        provider=_router,
        agent_name=settings.agent.name,
        memory_manager=memory_manager,
        personality_path=settings.personality.path,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        cost_fetcher=_delayed_cost_fetcher,
        budget_tracker=budget_tracker,
        max_tool_turns=settings.agent.max_tool_turns,
        run_timeout=settings.agent.run_timeout_seconds,
        summarizer=summarizer,
        corrections_manager=corrections_manager,
        tracer=tracer,
    )
```

4. Pass to Heartbeat (around line 250):
```python
    _heartbeat = Heartbeat(
        db=_db,
        agent=agent,
        telegram_channel=_telegram,
        goal_store=goal_store,
        provider=_router,
        interval=settings.heartbeat.interval_seconds,
        max_todos_per_tick=settings.heartbeat.max_todos_per_tick,
        idle_think_interval=settings.heartbeat.idle_think_interval,
        tracer=tracer,
    )
```

**Step 2: Run all tests**

Run: `pytest tests/test_trace.py tests/test_skills.py tests/test_skill_manage.py tests/test_prompt_builder.py tests/test_corrections.py -v`
Expected: All pass (action_log tests are gone, traces tests cover the same behavior)

**Step 3: Commit**

```bash
git add odigos/main.py
git rm tests/test_action_log.py 2>/dev/null; true
git commit -m "feat: wire Tracer into main.py, pass to Agent and Heartbeat"
```
