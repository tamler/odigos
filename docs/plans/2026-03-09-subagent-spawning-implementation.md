# Subagent Spawning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the main agent delegate background tasks to isolated subagents that run concurrently and report results back via the heartbeat.

**Architecture:** Subagents are background asyncio tasks that run a fresh Executor with a restricted tool set (all tools except `spawn_subagent`). Results are stored in a `subagent_tasks` DB table and delivered by the heartbeat as proactive messages. The LLM spawns subagents via a `spawn_subagent` tool.

**Tech Stack:** Python 3.12, asyncio, SQLite, pytest

**Design doc:** `docs/plans/2026-03-09-subagent-spawning-design.md`

---

### Task 1: Database migration for subagent_tasks

**Files:**
- Create: `migrations/009_subagent_tasks.sql`

**Step 1: Create the migration file**

Create `migrations/009_subagent_tasks.sql`:

```sql
CREATE TABLE IF NOT EXISTS subagent_tasks (
    id TEXT PRIMARY KEY,
    parent_conversation_id TEXT NOT NULL,
    instruction TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    result TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    delivered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_subagent_parent ON subagent_tasks(parent_conversation_id);
CREATE INDEX IF NOT EXISTS idx_subagent_status ON subagent_tasks(status);
```

**Step 2: Commit**

```bash
git add migrations/009_subagent_tasks.sql
git commit -m "feat: add subagent_tasks migration"
```

---

### Task 2: SubagentManager core

**Files:**
- Create: `odigos/core/subagent.py`
- Create: `tests/test_subagent.py`

**Context:** The `SubagentManager` manages subagent lifecycle: spawning, execution, result storage, and delivery tracking. It needs a `Database` reference for persistence, a `LLMProvider` and `Tracer` for the child Executor, and a `ToolRegistry` to clone (minus `spawn_subagent`). It also takes an optional `MemoryManager` for memory recall on the instruction.

**Step 1: Write the failing tests**

Create `tests/test_subagent.py`:

```python
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from odigos.core.subagent import SubagentManager
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


def _make_mock_provider(response_content="Done"):
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


def _make_tool_registry():
    registry = ToolRegistry()
    mock_tool = AsyncMock(spec=BaseTool)
    mock_tool.name = "web_search"
    mock_tool.description = "Search the web"
    mock_tool.parameters_schema = {"type": "object", "properties": {}}
    mock_tool.execute = AsyncMock(return_value=ToolResult(success=True, data="results"))
    registry.register(mock_tool)

    # Also register a fake spawn_subagent to test exclusion
    spawn_tool = AsyncMock(spec=BaseTool)
    spawn_tool.name = "spawn_subagent"
    spawn_tool.description = "Spawn a subagent"
    spawn_tool.parameters_schema = {"type": "object", "properties": {}}
    registry.register(spawn_tool)

    return registry


class TestSubagentManager:
    async def test_spawn_creates_db_row(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = _make_mock_provider()
        registry = _make_tool_registry()

        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )
        sub_id = await manager.spawn("Research AI safety", "test:conv-1")

        assert sub_id is not None
        row = await db.fetch_one(
            "SELECT * FROM subagent_tasks WHERE id = ?", (sub_id,)
        )
        assert row is not None
        assert row["instruction"] == "Research AI safety"
        assert row["parent_conversation_id"] == "test:conv-1"
        assert row["status"] == "running"

    async def test_spawn_returns_unique_ids(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = _make_mock_provider()
        registry = _make_tool_registry()

        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )
        id1 = await manager.spawn("Task 1", "test:conv-1")
        id2 = await manager.spawn("Task 2", "test:conv-1")
        assert id1 != id2

    async def test_spawn_enforces_max_concurrent(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = _make_mock_provider()
        registry = _make_tool_registry()

        # Make provider slow so tasks stay running
        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(60)
            return LLMResponse(content="done", model="test", tokens_in=0, tokens_out=0, cost_usd=0)

        provider.complete = slow_complete

        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )

        await manager.spawn("Task 1", "test:conv-1")
        await manager.spawn("Task 2", "test:conv-1")
        await manager.spawn("Task 3", "test:conv-1")

        # 4th should fail
        with pytest.raises(ValueError, match="concurrent"):
            await manager.spawn("Task 4", "test:conv-1")

    async def test_spawn_max_concurrent_per_conversation(self, db):
        """Different conversations have independent limits."""
        await _seed_conversation(db, "test:conv-1")
        await _seed_conversation(db, "test:conv-2")
        provider = _make_mock_provider()
        registry = _make_tool_registry()

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(60)
            return LLMResponse(content="done", model="test", tokens_in=0, tokens_out=0, cost_usd=0)

        provider.complete = slow_complete

        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )

        await manager.spawn("Task 1", "test:conv-1")
        await manager.spawn("Task 2", "test:conv-1")
        await manager.spawn("Task 3", "test:conv-1")

        # Different conversation should still work
        sub_id = await manager.spawn("Task 1", "test:conv-2")
        assert sub_id is not None


class TestSubagentExecution:
    async def test_completed_result_stored(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = _make_mock_provider("Here are the research results.")
        registry = _make_tool_registry()

        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )
        sub_id = await manager.spawn("Research AI safety", "test:conv-1")

        # Wait for background task to complete
        await asyncio.sleep(0.5)

        row = await db.fetch_one(
            "SELECT * FROM subagent_tasks WHERE id = ?", (sub_id,)
        )
        assert row["status"] == "completed"
        assert "research results" in row["result"].lower()
        assert row["completed_at"] is not None

    async def test_timeout_produces_failed(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = AsyncMock()

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(60)
            return LLMResponse(content="late", model="test", tokens_in=0, tokens_out=0, cost_usd=0)

        provider.complete = slow_complete
        registry = _make_tool_registry()

        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )
        sub_id = await manager.spawn("Research", "test:conv-1", timeout=1)

        await asyncio.sleep(2)

        row = await db.fetch_one(
            "SELECT * FROM subagent_tasks WHERE id = ?", (sub_id,)
        )
        assert row["status"] == "failed"
        assert "timed out" in row["result"].lower()

    async def test_exception_produces_failed(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = AsyncMock()
        provider.complete = AsyncMock(side_effect=RuntimeError("LLM crashed"))
        registry = _make_tool_registry()

        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )
        sub_id = await manager.spawn("Research", "test:conv-1")

        await asyncio.sleep(0.5)

        row = await db.fetch_one(
            "SELECT * FROM subagent_tasks WHERE id = ?", (sub_id,)
        )
        assert row["status"] == "failed"
        assert "LLM crashed" in row["result"]


class TestSubagentDelivery:
    async def test_get_completed_returns_undelivered(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = _make_mock_provider("Result here")
        registry = _make_tool_registry()

        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )
        sub_id = await manager.spawn("Task", "test:conv-1")
        await asyncio.sleep(0.5)

        results = await manager.get_completed_all()
        assert len(results) == 1
        assert results[0]["id"] == sub_id

    async def test_mark_delivered(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = _make_mock_provider("Result")
        registry = _make_tool_registry()

        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )
        sub_id = await manager.spawn("Task", "test:conv-1")
        await asyncio.sleep(0.5)

        await manager.mark_delivered(sub_id)

        results = await manager.get_completed_all()
        assert len(results) == 0

    async def test_get_completed_excludes_running(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = AsyncMock()

        async def slow(*args, **kwargs):
            await asyncio.sleep(60)
            return LLMResponse(content="done", model="test", tokens_in=0, tokens_out=0, cost_usd=0)

        provider.complete = slow
        registry = _make_tool_registry()

        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )
        await manager.spawn("Still running", "test:conv-1")
        await asyncio.sleep(0.1)

        results = await manager.get_completed_all()
        assert len(results) == 0


class TestSubagentToolExclusion:
    async def test_restricted_registry_excludes_spawn(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = _make_mock_provider()
        registry = _make_tool_registry()

        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )

        restricted = manager._build_restricted_registry()
        assert restricted.get("spawn_subagent") is None
        assert restricted.get("web_search") is not None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_subagent.py -v`
Expected: FAIL (`odigos.core.subagent` does not exist)

**Step 3: Implement SubagentManager**

Create `odigos/core/subagent.py`:

```python
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.core.executor import Executor
from odigos.core.context import ContextAssembler
from odigos.db import Database
from odigos.providers.base import LLMProvider
from odigos.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from odigos.core.trace import Tracer
    from odigos.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

MAX_CONCURRENT_PER_CONVERSATION = 3
DEFAULT_TIMEOUT = 600


class SubagentManager:
    """Manages subagent lifecycle: spawn, execute, store results."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        tracer: Tracer | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.tool_registry = tool_registry
        self.tracer = tracer
        self.memory_manager = memory_manager
        self._tasks: dict[str, asyncio.Task] = {}

    async def spawn(
        self,
        instruction: str,
        parent_conversation_id: str,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> str:
        """Spawn a subagent. Returns the subagent ID."""
        # Check concurrent limit
        running = await self.db.fetch_one(
            "SELECT COUNT(*) as cnt FROM subagent_tasks "
            "WHERE parent_conversation_id = ? AND status = 'running'",
            (parent_conversation_id,),
        )
        if running and running["cnt"] >= MAX_CONCURRENT_PER_CONVERSATION:
            raise ValueError(
                f"Max concurrent subagents ({MAX_CONCURRENT_PER_CONVERSATION}) "
                f"reached for conversation {parent_conversation_id}"
            )

        subagent_id = f"sub-{uuid.uuid4().hex[:12]}"

        await self.db.execute(
            "INSERT INTO subagent_tasks (id, parent_conversation_id, instruction, status) "
            "VALUES (?, ?, ?, 'running')",
            (subagent_id, parent_conversation_id, instruction),
        )

        task = asyncio.create_task(
            self._run_subagent(subagent_id, instruction, parent_conversation_id, timeout)
        )
        self._tasks[subagent_id] = task
        logger.info(
            "Spawned subagent %s for %s: %s",
            subagent_id, parent_conversation_id, instruction[:100],
        )
        return subagent_id

    async def _run_subagent(
        self,
        subagent_id: str,
        instruction: str,
        parent_conversation_id: str,
        timeout: int,
    ) -> None:
        """Run the subagent executor and store the result."""
        try:
            # Build context
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a subagent executing a delegated task. "
                        "Complete the task and provide a clear, concise result. "
                        "Do not ask questions -- work with what you have."
                    ),
                },
            ]

            # Add memory recall if available
            if self.memory_manager:
                try:
                    memory_context = await self.memory_manager.recall(instruction)
                    if memory_context:
                        messages.append({
                            "role": "system",
                            "content": f"Relevant memory:\n{memory_context}",
                        })
                except Exception:
                    logger.debug("Memory recall failed for subagent", exc_info=True)

            messages.append({"role": "user", "content": instruction})

            # Build restricted tool registry and executor
            restricted_registry = self._build_restricted_registry()
            executor = Executor(
                provider=self.provider,
                context_assembler=None,
                tool_registry=restricted_registry,
                db=self.db,
                tracer=self.tracer,
            )

            # Run with timeout -- call provider.complete directly with messages
            # since we bypass ContextAssembler
            tools = restricted_registry.tool_definitions() if restricted_registry.list() else None

            async with asyncio.timeout(timeout):
                response = await self.provider.complete(messages, tools=tools)

            result_content = response.content or "Subagent completed with no output."

            await self.db.execute(
                "UPDATE subagent_tasks SET status = 'completed', result = ?, "
                "completed_at = ? WHERE id = ?",
                (result_content, datetime.now(timezone.utc).isoformat(), subagent_id),
            )
            logger.info("Subagent %s completed", subagent_id)

        except asyncio.TimeoutError:
            await self.db.execute(
                "UPDATE subagent_tasks SET status = 'failed', "
                "result = 'Subagent timed out', completed_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), subagent_id),
            )
            logger.warning("Subagent %s timed out after %ds", subagent_id, timeout)

        except Exception as e:
            await self.db.execute(
                "UPDATE subagent_tasks SET status = 'failed', result = ?, "
                "completed_at = ? WHERE id = ?",
                (f"Error: {e}", datetime.now(timezone.utc).isoformat(), subagent_id),
            )
            logger.exception("Subagent %s failed", subagent_id)

        finally:
            self._tasks.pop(subagent_id, None)
            if self.tracer:
                status_row = await self.db.fetch_one(
                    "SELECT status FROM subagent_tasks WHERE id = ?", (subagent_id,)
                )
                await self.tracer.emit("subagent_completed", parent_conversation_id, {
                    "subagent_id": subagent_id,
                    "status": status_row["status"] if status_row else "unknown",
                })

    def _build_restricted_registry(self) -> ToolRegistry:
        """Clone tool registry without spawn_subagent."""
        restricted = ToolRegistry()
        for tool in self.tool_registry.list():
            if tool.name != "spawn_subagent":
                restricted.register(tool)
        return restricted

    async def get_completed_all(self) -> list[dict]:
        """Return all completed/failed subagent results not yet delivered."""
        rows = await self.db.fetch_all(
            "SELECT * FROM subagent_tasks "
            "WHERE status IN ('completed', 'failed') AND delivered_at IS NULL "
            "ORDER BY completed_at",
        )
        return [dict(r) for r in rows] if rows else []

    async def mark_delivered(self, subagent_id: str) -> None:
        """Mark a subagent result as delivered to the parent."""
        await self.db.execute(
            "UPDATE subagent_tasks SET delivered_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), subagent_id),
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_subagent.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/core/subagent.py tests/test_subagent.py migrations/009_subagent_tasks.sql
git commit -m "feat: add SubagentManager with spawn, execution, and delivery"
```

---

### Task 3: SpawnSubagentTool

**Files:**
- Create: `odigos/tools/subagent_tool.py`
- Add tests to: `tests/test_subagent.py`

**Context:** This tool wraps `SubagentManager.spawn()` so the LLM can call it. Follow the same pattern as `odigos/tools/skill_tool.py` -- extends `BaseTool`, has `name`, `description`, `parameters_schema`, and `execute()`.

**Step 1: Write the failing tests**

Add to `tests/test_subagent.py`:

```python
from odigos.tools.subagent_tool import SpawnSubagentTool


class TestSpawnSubagentTool:
    async def test_tool_metadata(self):
        manager = AsyncMock()
        tool = SpawnSubagentTool(subagent_manager=manager)
        assert tool.name == "spawn_subagent"
        assert "instruction" in tool.parameters_schema["properties"]
        assert "instruction" in tool.parameters_schema["required"]

    async def test_spawn_success(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = _make_mock_provider("Done")
        registry = _make_tool_registry()
        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )

        tool = SpawnSubagentTool(subagent_manager=manager)
        result = await tool.execute({
            "instruction": "Research AI safety",
            "_conversation_id": "test:conv-1",
        })

        assert result.success is True
        assert "sub-" in result.data

    async def test_spawn_missing_instruction(self):
        manager = AsyncMock()
        tool = SpawnSubagentTool(subagent_manager=manager)
        result = await tool.execute({"_conversation_id": "test:conv-1"})
        assert result.success is False
        assert "instruction" in result.error.lower()

    async def test_spawn_missing_conversation(self):
        manager = AsyncMock()
        tool = SpawnSubagentTool(subagent_manager=manager)
        result = await tool.execute({"instruction": "Do stuff"})
        assert result.success is False

    async def test_spawn_max_concurrent_error(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = AsyncMock()

        async def slow(*args, **kwargs):
            await asyncio.sleep(60)
            return LLMResponse(content="done", model="test", tokens_in=0, tokens_out=0, cost_usd=0)

        provider.complete = slow
        registry = _make_tool_registry()
        manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )

        tool = SpawnSubagentTool(subagent_manager=manager)

        # Spawn 3 (max)
        for i in range(3):
            await tool.execute({
                "instruction": f"Task {i}",
                "_conversation_id": "test:conv-1",
            })

        # 4th should return error, not crash
        result = await tool.execute({
            "instruction": "Task 4",
            "_conversation_id": "test:conv-1",
        })
        assert result.success is False
        assert "concurrent" in result.error.lower()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_subagent.py::TestSpawnSubagentTool -v`
Expected: FAIL (`odigos.tools.subagent_tool` does not exist)

**Step 3: Implement SpawnSubagentTool**

Create `odigos/tools/subagent_tool.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.core.subagent import SubagentManager


class SpawnSubagentTool(BaseTool):
    """Tool that spawns a background subagent to handle a delegated task."""

    name = "spawn_subagent"
    description = (
        "Delegate a task to a background subagent. The subagent will work "
        "independently and report results when done. Use this for tasks that "
        "would take many tool calls and don't need to block the current conversation."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "Clear instruction describing what the subagent should do.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds for the subagent to run (default: 600).",
            },
        },
        "required": ["instruction"],
    }

    def __init__(self, subagent_manager: SubagentManager) -> None:
        self._manager = subagent_manager

    async def execute(self, params: dict) -> ToolResult:
        instruction = params.get("instruction")
        if not instruction:
            return ToolResult(
                success=False, data="",
                error="Missing required parameter: instruction",
            )

        conversation_id = params.get("_conversation_id")
        if not conversation_id:
            return ToolResult(
                success=False, data="",
                error="No conversation context available",
            )

        timeout = params.get("timeout", 600)

        try:
            subagent_id = await self._manager.spawn(
                instruction=instruction,
                parent_conversation_id=conversation_id,
                timeout=timeout,
            )
            return ToolResult(
                success=True,
                data=f"Subagent {subagent_id} spawned. It will work in the background "
                     f"and results will be delivered when ready.",
            )
        except ValueError as e:
            return ToolResult(success=False, data="", error=str(e))
```

**Step 4: Run tests**

Run: `pytest tests/test_subagent.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/tools/subagent_tool.py tests/test_subagent.py
git commit -m "feat: add SpawnSubagentTool"
```

---

### Task 4: Heartbeat integration

**Files:**
- Modify: `odigos/core/heartbeat.py:28-51,76-95`
- Add tests to: `tests/test_subagent.py`

**Context:** The heartbeat already processes reminders and todos in `_tick()`. Add a phase between todos and idle-think that checks for completed subagent results and delivers them as proactive messages via `_send_notification()`. The `SubagentManager` is passed to `Heartbeat.__init__()`.

**Step 1: Write the failing tests**

Add to `tests/test_subagent.py`:

```python
from odigos.core.heartbeat import Heartbeat


class TestSubagentInHeartbeat:
    async def test_heartbeat_delivers_completed_results(self, db):
        await _seed_conversation(db, "test:conv-1")
        provider = _make_mock_provider("Background result")
        registry = _make_tool_registry()

        subagent_manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )
        sub_id = await subagent_manager.spawn("Do research", "test:conv-1")
        await asyncio.sleep(0.5)

        # Verify result is pending
        results = await subagent_manager.get_completed_all()
        assert len(results) == 1

        # Create heartbeat with subagent_manager
        mock_agent = AsyncMock()
        mock_telegram = AsyncMock()
        mock_goal_store = AsyncMock()
        mock_goal_store.list_goals = AsyncMock(return_value=[])

        heartbeat = Heartbeat(
            db=db,
            agent=mock_agent,
            telegram_channel=mock_telegram,
            goal_store=mock_goal_store,
            provider=provider,
            subagent_manager=subagent_manager,
        )

        await heartbeat._tick()

        # Result should now be delivered
        results = await subagent_manager.get_completed_all()
        assert len(results) == 0

        # Notification was sent
        mock_telegram.send_message.assert_called_once()
        call_args = mock_telegram.send_message.call_args
        assert "Subagent result" in call_args[0][1] or "subagent" in str(call_args).lower()

    async def test_heartbeat_no_subagent_results(self, db):
        """Tick completes without error when no subagent results pending."""
        mock_agent = AsyncMock()
        mock_telegram = AsyncMock()
        mock_goal_store = AsyncMock()
        mock_goal_store.list_goals = AsyncMock(return_value=[])
        provider = _make_mock_provider()
        registry = _make_tool_registry()

        subagent_manager = SubagentManager(
            db=db, provider=provider, tool_registry=registry,
        )

        heartbeat = Heartbeat(
            db=db,
            agent=mock_agent,
            telegram_channel=mock_telegram,
            goal_store=mock_goal_store,
            provider=provider,
            subagent_manager=subagent_manager,
        )

        # Should not raise
        await heartbeat._tick()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_subagent.py::TestSubagentInHeartbeat -v`
Expected: FAIL (Heartbeat doesn't accept subagent_manager parameter yet)

**Step 3: Modify Heartbeat**

In `odigos/core/heartbeat.py`:

1. Add TYPE_CHECKING import for SubagentManager:
```python
if TYPE_CHECKING:
    from odigos.channels.telegram import TelegramChannel
    from odigos.core.agent import Agent
    from odigos.core.goal_store import GoalStore
    from odigos.core.subagent import SubagentManager
    from odigos.core.trace import Tracer
    from odigos.providers.base import LLMProvider
```

2. Add `subagent_manager` parameter to `__init__()`:
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
        subagent_manager: SubagentManager | None = None,
    ) -> None:
        # ... existing assignments ...
        self.subagent_manager = subagent_manager
```

3. Add subagent result delivery phase to `_tick()`, between todos and idle-think:
```python
    async def _tick(self) -> None:
        if self.paused:
            return

        did_work = False

        # Phase 1: Fire due reminders
        did_work |= await self._fire_reminders()

        # Phase 2: Work on pending todos
        did_work |= await self._work_todos()

        # Phase 3: Deliver subagent results
        did_work |= await self._deliver_subagent_results()

        # Phase 4: Idle thoughts (only if nothing ran above)
        if not did_work:
            await self._idle_think()

        if self.tracer:
            await self.tracer.emit("heartbeat_tick", None, {
                "did_work": did_work,
            })
```

4. Add the delivery method:
```python
    async def _deliver_subagent_results(self) -> bool:
        if not self.subagent_manager:
            return False

        results = await self.subagent_manager.get_completed_all()
        if not results:
            return False

        for r in results:
            summary = (
                f"[Subagent result] Task: {r['instruction'][:200]}\n\n"
                f"Status: {r['status']}\n"
                f"Result: {r['result']}"
            )
            conv_id = r["parent_conversation_id"]
            await self._send_notification(conv_id, summary[:4000])
            await self.subagent_manager.mark_delivered(r["id"])
            logger.info("Delivered subagent result %s to %s", r["id"], conv_id)

        return True
```

**Step 4: Run tests**

Run: `pytest tests/test_subagent.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add odigos/core/heartbeat.py tests/test_subagent.py
git commit -m "feat: heartbeat delivers subagent results"
```

---

### Task 5: Wire into main.py

**Files:**
- Modify: `odigos/main.py`

**Context:** Create the SubagentManager after the tool registry is fully populated, register SpawnSubagentTool, and pass the manager to Heartbeat.

**Step 1: Add imports and wiring**

In `odigos/main.py`, add import:
```python
from odigos.core.subagent import SubagentManager
```

After all tools are registered and before the Agent is created (around line 193 after skill tools), add:
```python
    # Initialize subagent manager
    subagent_manager = SubagentManager(
        db=_db,
        provider=_router,
        tool_registry=tool_registry,
        tracer=tracer,
        memory_manager=memory_manager,
    )
    logger.info("Subagent manager initialized")

    # Register subagent tool
    from odigos.tools.subagent_tool import SpawnSubagentTool

    spawn_tool = SpawnSubagentTool(subagent_manager=subagent_manager)
    tool_registry.register(spawn_tool)
    logger.info("Subagent tool registered")
```

In the Heartbeat constructor call, add `subagent_manager=subagent_manager`:
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
        subagent_manager=subagent_manager,
    )
```

**Step 2: Run tests**

Run: `pytest tests/test_subagent.py -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add odigos/main.py
git commit -m "feat: wire SubagentManager and SpawnSubagentTool into main.py"
```
