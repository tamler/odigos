# Phase 2 Gaps: Heartbeat + Code Sandbox Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add task scheduling (heartbeat system) and code execution sandbox to fill the remaining Phase 2 gaps.

**Architecture:** A `tasks` table stores scheduled work. A 30-second heartbeat loop picks up pending tasks and executes them through the agent. A subprocess-based sandbox with `ulimit` resource limits runs Python/shell code. Both integrate through the existing planner/executor pipeline.

**Tech Stack:** asyncio, subprocess, aiosqlite, python-telegram-bot

---

### Task 1: Tasks Table Migration

**Files:**
- Create: `migrations/004_tasks.sql`
- Test: `tests/test_tasks_migration.py`

**Step 1: Write the failing test**

```python
# tests/test_tasks_migration.py
import pytest
import pytest_asyncio
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path)
    await d.initialize()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_tasks_table_exists(db):
    """The tasks table should exist after migrations run."""
    result = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
    )
    assert result is not None
    assert result["name"] == "tasks"


@pytest.mark.asyncio
async def test_tasks_table_columns(db):
    """The tasks table should have all required columns."""
    rows = await db.fetch_all("PRAGMA table_info(tasks)")
    columns = {row["name"] for row in rows}
    expected = {
        "id", "type", "status", "description", "payload_json",
        "scheduled_at", "started_at", "completed_at", "result_json",
        "error", "retry_count", "max_retries", "priority",
        "recurrence_json", "conversation_id", "created_by",
    }
    assert expected.issubset(columns)


@pytest.mark.asyncio
async def test_tasks_insert_and_query(db):
    """Basic insert and query on the tasks table."""
    await db.execute(
        "INSERT INTO tasks (id, type, description) VALUES (?, ?, ?)",
        ("t1", "one_shot", "Test task"),
    )
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", ("t1",))
    assert row is not None
    assert row["status"] == "pending"
    assert row["priority"] == 1
    assert row["retry_count"] == 0
    assert row["max_retries"] == 3
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tasks_migration.py -v`
Expected: FAIL with "no such table: tasks"

**Step 3: Write the migration**

```sql
-- migrations/004_tasks.sql
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    description TEXT,
    payload_json TEXT,
    scheduled_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    result_json TEXT,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    priority INTEGER DEFAULT 1,
    recurrence_json TEXT,
    conversation_id TEXT,
    created_by TEXT DEFAULT 'user'
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_scheduled ON tasks(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tasks_migration.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add migrations/004_tasks.sql tests/test_tasks_migration.py
git commit -m "feat: add tasks table migration (004)"
```

---

### Task 2: TaskScheduler

**Files:**
- Create: `odigos/core/scheduler.py`
- Test: `tests/test_scheduler.py`

**Step 1: Write the failing test**

```python
# tests/test_scheduler.py
import pytest
import pytest_asyncio
from odigos.core.scheduler import TaskScheduler
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path)
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def scheduler(db):
    return TaskScheduler(db=db)


@pytest.mark.asyncio
async def test_create_one_shot_task(scheduler, db):
    task_id = await scheduler.create(description="Say hello")
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row is not None
    assert row["type"] == "one_shot"
    assert row["status"] == "pending"
    assert row["description"] == "Say hello"
    assert row["scheduled_at"] is not None  # immediate = now


@pytest.mark.asyncio
async def test_create_delayed_task(scheduler, db):
    task_id = await scheduler.create(description="Remind me", delay_seconds=3600)
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row is not None
    # scheduled_at should be roughly 1 hour from now
    assert row["scheduled_at"] is not None


@pytest.mark.asyncio
async def test_create_recurring_task(scheduler, db):
    task_id = await scheduler.create(
        description="Check email", recurrence_seconds=1800
    )
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["type"] == "recurring"
    assert '"interval_seconds": 1800' in row["recurrence_json"]


@pytest.mark.asyncio
async def test_cancel_task(scheduler, db):
    task_id = await scheduler.create(description="Cancel me")
    result = await scheduler.cancel(task_id)
    assert result is True
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_nonexistent_returns_false(scheduler):
    result = await scheduler.cancel("nonexistent-id")
    assert result is False


@pytest.mark.asyncio
async def test_list_pending(scheduler):
    await scheduler.create(description="Task A")
    await scheduler.create(description="Task B", delay_seconds=99999)
    # Task B is far in the future, but list_pending returns all pending tasks
    tasks = await scheduler.list_pending()
    assert len(tasks) == 2


@pytest.mark.asyncio
async def test_get_task(scheduler):
    task_id = await scheduler.create(description="Get me")
    task = await scheduler.get(task_id)
    assert task is not None
    assert task["description"] == "Get me"


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(scheduler):
    task = await scheduler.get("nonexistent-id")
    assert task is None


@pytest.mark.asyncio
async def test_create_with_priority(scheduler, db):
    task_id = await scheduler.create(description="Urgent", priority=0)
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["priority"] == 0


@pytest.mark.asyncio
async def test_create_with_conversation_id(scheduler, db):
    task_id = await scheduler.create(
        description="Reply", conversation_id="telegram:12345"
    )
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["conversation_id"] == "telegram:12345"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'odigos.core.scheduler'"

**Step 3: Write the implementation**

```python
# odigos/core/scheduler.py
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta

from odigos.db import Database

logger = logging.getLogger(__name__)


class TaskScheduler:
    """Central task CRUD. Any component can create/query/cancel tasks."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(
        self,
        description: str,
        delay_seconds: int = 0,
        recurrence_seconds: int | None = None,
        priority: int = 1,
        conversation_id: str | None = None,
        created_by: str = "user",
        payload: dict | None = None,
    ) -> str:
        """Insert a task. Returns task ID."""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        scheduled_at = (now + timedelta(seconds=delay_seconds)).isoformat()
        task_type = "recurring" if recurrence_seconds else "one_shot"
        recurrence_json = (
            json.dumps({"interval_seconds": recurrence_seconds})
            if recurrence_seconds
            else None
        )
        payload_json = json.dumps(payload) if payload else None

        await self.db.execute(
            "INSERT INTO tasks (id, type, status, description, payload_json, "
            "scheduled_at, priority, recurrence_json, conversation_id, created_by) "
            "VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                task_type,
                description,
                payload_json,
                scheduled_at,
                priority,
                recurrence_json,
                conversation_id,
                created_by,
            ),
        )
        logger.info("Created task %s: %s (scheduled: %s)", task_id, description, scheduled_at)
        return task_id

    async def cancel(self, task_id: str) -> bool:
        """Cancel a pending task. Returns True if found and cancelled."""
        row = await self.db.fetch_one(
            "SELECT id FROM tasks WHERE id = ? AND status = 'pending'", (task_id,)
        )
        if not row:
            return False
        await self.db.execute(
            "UPDATE tasks SET status = 'cancelled' WHERE id = ?", (task_id,)
        )
        logger.info("Cancelled task %s", task_id)
        return True

    async def list_pending(self, limit: int = 20) -> list[dict]:
        """List pending tasks, ordered by priority + scheduled_at."""
        return await self.db.fetch_all(
            "SELECT * FROM tasks WHERE status = 'pending' "
            "ORDER BY priority ASC, scheduled_at ASC LIMIT ?",
            (limit,),
        )

    async def get(self, task_id: str) -> dict | None:
        """Get a single task by ID."""
        return await self.db.fetch_one(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        )
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS (10 tests)

**Step 5: Commit**

```bash
git add odigos/core/scheduler.py tests/test_scheduler.py
git commit -m "feat: add TaskScheduler for task CRUD"
```

---

### Task 3: SandboxProvider

**Files:**
- Create: `odigos/providers/sandbox.py`
- Test: `tests/test_sandbox.py`

**Step 1: Write the failing test**

```python
# tests/test_sandbox.py
import pytest
import pytest_asyncio
from odigos.providers.sandbox import SandboxProvider, SandboxResult


@pytest_asyncio.fixture
async def sandbox():
    return SandboxProvider(timeout=5, max_memory_mb=512, allow_network=False)


@pytest.mark.asyncio
async def test_python_hello_world(sandbox):
    result = await sandbox.execute("print('hello')", language="python")
    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.timed_out is False


@pytest.mark.asyncio
async def test_shell_echo(sandbox):
    result = await sandbox.execute("echo hello", language="shell")
    assert result.exit_code == 0
    assert "hello" in result.stdout


@pytest.mark.asyncio
async def test_python_stderr(sandbox):
    result = await sandbox.execute("import sys; sys.stderr.write('err')", language="python")
    assert "err" in result.stderr


@pytest.mark.asyncio
async def test_python_syntax_error(sandbox):
    result = await sandbox.execute("def", language="python")
    assert result.exit_code != 0


@pytest.mark.asyncio
async def test_timeout_kills_process(sandbox):
    sb = SandboxProvider(timeout=1, max_memory_mb=512)
    result = await sb.execute("import time; time.sleep(10); print('done')", language="python")
    assert result.timed_out is True
    assert result.exit_code != 0


@pytest.mark.asyncio
async def test_output_truncation(sandbox):
    sb = SandboxProvider(timeout=5, max_memory_mb=512, max_output_chars=50)
    result = await sb.execute("print('x' * 200)", language="python")
    assert len(result.stdout) <= 80  # 50 + truncation notice


@pytest.mark.asyncio
async def test_unsupported_language(sandbox):
    result = await sandbox.execute("console.log('hi')", language="javascript")
    assert result.exit_code != 0
    assert "Unsupported" in result.stderr


@pytest.mark.asyncio
async def test_shell_pipefail(sandbox):
    """Shell scripts should fail on errors (set -euo pipefail)."""
    result = await sandbox.execute("false", language="shell")
    assert result.exit_code != 0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sandbox.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'odigos.providers.sandbox'"

**Step 3: Write the implementation**

```python
# odigos/providers/sandbox.py
from __future__ import annotations

import asyncio
import logging
import platform
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_IS_LINUX = platform.system() == "Linux"


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


class SandboxProvider:
    """Runs code in a sandboxed subprocess with resource limits."""

    def __init__(
        self,
        timeout: int = 5,
        max_memory_mb: int = 512,
        allow_network: bool = False,
        max_output_chars: int = 4000,
    ) -> None:
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.allow_network = allow_network
        self.max_output_chars = max_output_chars

    async def execute(self, code: str, language: str = "python") -> SandboxResult:
        """Run code in a sandboxed subprocess."""
        if language == "python":
            cmd = self._build_python_cmd(code)
        elif language == "shell":
            cmd = self._build_shell_cmd(code)
        else:
            return SandboxResult(
                stdout="",
                stderr=f"Unsupported language: {language}",
                exit_code=1,
                timed_out=False,
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout + 5
            )
            stdout = self._truncate(stdout_bytes.decode(errors="replace"))
            stderr = self._truncate(stderr_bytes.decode(errors="replace"))
            return SandboxResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode or 0,
                timed_out=False,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(
                stdout="",
                stderr="Execution timed out",
                exit_code=-1,
                timed_out=True,
            )
        except Exception as e:
            logger.exception("Sandbox execution failed")
            return SandboxResult(
                stdout="",
                stderr=str(e),
                exit_code=-1,
                timed_out=False,
            )

    def _build_python_cmd(self, code: str) -> list[str]:
        limits = self._resource_prefix()
        return [*limits, "python3", "-c", code]

    def _build_shell_cmd(self, code: str) -> list[str]:
        limits = self._resource_prefix()
        return [*limits, "bash", "-c", f"set -euo pipefail; {code}"]

    def _resource_prefix(self) -> list[str]:
        """Build ulimit + optional unshare prefix."""
        memory_kb = self.max_memory_mb * 1024
        parts = [
            "bash", "-c",
            f"ulimit -t {self.timeout} -v {memory_kb}; exec \"$@\"",
            "--",
        ]
        if _IS_LINUX and not self.allow_network:
            return ["unshare", "--net", *parts]
        if not _IS_LINUX:
            logger.debug("Skipping unshare on %s (not Linux)", platform.system())
        return parts

    def _truncate(self, text: str) -> str:
        if len(text) > self.max_output_chars:
            return text[: self.max_output_chars] + "\n[output truncated]"
        return text
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sandbox.py -v`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add odigos/providers/sandbox.py tests/test_sandbox.py
git commit -m "feat: add SandboxProvider for code execution"
```

---

### Task 4: CodeTool

**Files:**
- Create: `odigos/tools/code.py`
- Test: `tests/test_code_tool.py`

**Step 1: Write the failing test**

```python
# tests/test_code_tool.py
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from odigos.providers.sandbox import SandboxResult
from odigos.tools.code import CodeTool


@pytest_asyncio.fixture
async def mock_sandbox():
    sb = MagicMock()
    sb.execute = AsyncMock(
        return_value=SandboxResult(stdout="42\n", stderr="", exit_code=0, timed_out=False)
    )
    return sb


@pytest_asyncio.fixture
async def code_tool(mock_sandbox):
    return CodeTool(sandbox=mock_sandbox)


@pytest.mark.asyncio
async def test_tool_name(code_tool):
    assert code_tool.name == "run_code"


@pytest.mark.asyncio
async def test_execute_python(code_tool, mock_sandbox):
    result = await code_tool.execute({"code": "print(42)", "language": "python"})
    assert result.success is True
    assert "42" in result.data
    mock_sandbox.execute.assert_called_once_with("print(42)", language="python")


@pytest.mark.asyncio
async def test_execute_shell(code_tool, mock_sandbox):
    result = await code_tool.execute({"code": "echo hi", "language": "shell"})
    assert result.success is True
    mock_sandbox.execute.assert_called_once_with("echo hi", language="shell")


@pytest.mark.asyncio
async def test_defaults_to_python(code_tool, mock_sandbox):
    await code_tool.execute({"code": "print(1)"})
    mock_sandbox.execute.assert_called_once_with("print(1)", language="python")


@pytest.mark.asyncio
async def test_missing_code_returns_error(code_tool):
    result = await code_tool.execute({})
    assert result.success is False
    assert "code" in result.error.lower()


@pytest.mark.asyncio
async def test_execution_failure(mock_sandbox):
    mock_sandbox.execute = AsyncMock(
        return_value=SandboxResult(stdout="", stderr="NameError", exit_code=1, timed_out=False)
    )
    tool = CodeTool(sandbox=mock_sandbox)
    result = await tool.execute({"code": "bad_code"})
    assert result.success is False
    assert "NameError" in result.error


@pytest.mark.asyncio
async def test_timeout_failure(mock_sandbox):
    mock_sandbox.execute = AsyncMock(
        return_value=SandboxResult(stdout="", stderr="timed out", exit_code=-1, timed_out=True)
    )
    tool = CodeTool(sandbox=mock_sandbox)
    result = await tool.execute({"code": "while True: pass"})
    assert result.success is False
    assert "timed out" in result.error.lower()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_code_tool.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'odigos.tools.code'"

**Step 3: Write the implementation**

```python
# odigos/tools/code.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.providers.sandbox import SandboxProvider

logger = logging.getLogger(__name__)


class CodeTool(BaseTool):
    """Execute Python or shell code in a sandboxed environment."""

    name = "run_code"
    description = "Execute Python or shell code in a sandboxed environment with resource limits"

    def __init__(self, sandbox: SandboxProvider) -> None:
        self.sandbox = sandbox

    async def execute(self, params: dict) -> ToolResult:
        code = params.get("code", "")
        if not code:
            return ToolResult(success=False, data="", error="No code provided")

        language = params.get("language", "python")

        result = await self.sandbox.execute(code, language=language)

        if result.timed_out:
            return ToolResult(
                success=False,
                data=result.stdout,
                error=f"Code execution timed out. stderr: {result.stderr}",
            )

        if result.exit_code != 0:
            return ToolResult(
                success=False,
                data=result.stdout,
                error=result.stderr or f"Process exited with code {result.exit_code}",
            )

        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]: {result.stderr}"
        return ToolResult(success=True, data=output)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_code_tool.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add odigos/tools/code.py tests/test_code_tool.py
git commit -m "feat: add CodeTool wrapping SandboxProvider"
```

---

### Task 5: Planner — Add Schedule and Code Actions

**Files:**
- Modify: `odigos/core/planner.py:14-39` (CLASSIFY_PROMPT and Plan dataclass)
- Test: `tests/test_core.py` (add new test classes)

**Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
class TestPlannerScheduleAction:
    @pytest.mark.asyncio
    async def test_schedule_action_parsed(self, mock_provider):
        mock_provider.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"action": "schedule", "description": "check email", "delay_seconds": 3600}',
                model="test",
            )
        )
        planner = Planner(provider=mock_provider)
        plan = await planner.plan("remind me to check email in 1 hour")
        assert plan.action == "schedule"
        assert plan.schedule_seconds == 3600
        assert plan.tool_params["description"] == "check email"

    @pytest.mark.asyncio
    async def test_recurring_schedule(self, mock_provider):
        mock_provider.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"action": "schedule", "description": "check email", "delay_seconds": 0, "recurrence_seconds": 3600}',
                model="test",
            )
        )
        planner = Planner(provider=mock_provider)
        plan = await planner.plan("check my email every hour")
        assert plan.action == "schedule"
        assert plan.recurrence_seconds == 3600


class TestPlannerCodeAction:
    @pytest.mark.asyncio
    async def test_code_action_parsed(self, mock_provider):
        mock_provider.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"action": "code", "code": "print(2+2)", "language": "python"}',
                model="test",
            )
        )
        planner = Planner(provider=mock_provider)
        plan = await planner.plan("calculate 2+2")
        assert plan.action == "code"
        assert plan.tool_params["code"] == "print(2+2)"
        assert plan.tool_params["language"] == "python"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_core.py::TestPlannerScheduleAction -v && python -m pytest tests/test_core.py::TestPlannerCodeAction -v`
Expected: FAIL (Plan has no attribute `schedule_seconds`)

**Step 3: Update planner.py**

In `odigos/core/planner.py`:

Update `CLASSIFY_PROMPT` (line 14-30) to add two new action lines and guidance:

After the document action line (line 19), add:
```
- If the user wants to schedule a task or set a reminder: {"action": "schedule", "description": "<what to do>", "delay_seconds": <seconds from now>, "recurrence_seconds": <repeat interval or null>, "skill": "<skill or null>"}
- If code execution is needed: {"action": "code", "code": "<python or shell code>", "language": "python|shell", "skill": "<skill or null>"}
```

After the Document guidance line (line 29), add:
```
Schedule IS needed for: "remind me", "in X hours", "later today", "tomorrow morning", "every day at", any time-based request. For delay_seconds, calculate the number of seconds from now (e.g., "in 2 hours" = 7200).
Code IS needed for: math calculations, data processing, running scripts, "calculate", "compute", any request that requires executing code to produce a result.
```

Update `Plan` dataclass (line 33-38) to add new fields:

```python
@dataclass
class Plan:
    action: str  # "respond", "search", "scrape", "document", "schedule", "code"
    requires_tools: bool = False
    tool_params: dict = field(default_factory=dict)
    skill: str | None = None
    schedule_seconds: int | None = None
    recurrence_seconds: int | None = None
```

In the `plan()` method (after the document block, around line 91), add handlers:

```python
            if action == "schedule":
                description = result.get("description", message_content)
                delay = result.get("delay_seconds", 0)
                recurrence = result.get("recurrence_seconds")
                return Plan(
                    action="schedule",
                    tool_params={"description": description},
                    skill=skill,
                    schedule_seconds=int(delay) if delay else 0,
                    recurrence_seconds=int(recurrence) if recurrence else None,
                )

            if action == "code":
                code = result.get("code", "")
                language = result.get("language", "python")
                if code:
                    return Plan(
                        action="code",
                        requires_tools=True,
                        tool_params={"code": code, "language": language},
                        skill=skill,
                    )
```

Also increase `max_tokens` from 100 to 200 (line 57) to accommodate the code in JSON responses.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_core.py -v`
Expected: All tests PASS (existing + new)

**Step 5: Commit**

```bash
git add odigos/core/planner.py tests/test_core.py
git commit -m "feat: add schedule and code actions to planner"
```

---

### Task 6: Executor — Handle Schedule and Code Actions

**Files:**
- Modify: `odigos/core/executor.py:26-95` (Executor class)
- Modify: `odigos/core/agent.py:20-51` (pass scheduler to executor)
- Test: `tests/test_core.py` (add new test classes)

**Step 1: Write the failing tests**

Add to `tests/test_core.py`:

```python
class TestExecutorScheduleAction:
    @pytest.mark.asyncio
    async def test_schedule_creates_task_and_returns_confirmation(self):
        mock_provider = MagicMock()
        mock_assembler = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.create = AsyncMock(return_value="task-123")

        executor = Executor(
            provider=mock_provider,
            context_assembler=mock_assembler,
            scheduler=mock_scheduler,
        )

        plan = Plan(
            action="schedule",
            tool_params={"description": "check email"},
            schedule_seconds=3600,
        )

        result = await executor.execute("conv1", "remind me in 1 hour to check email", plan=plan)
        assert result.response.content  # should have confirmation text
        assert "check email" in result.response.content.lower() or "1 hour" in result.response.content.lower() or "scheduled" in result.response.content.lower()
        mock_scheduler.create.assert_called_once()


class TestExecutorCodeAction:
    @pytest.mark.asyncio
    async def test_code_action_uses_run_code_tool(self):
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(
            return_value=LLMResponse(content="The answer is 42", model="test")
        )
        mock_assembler = MagicMock()
        mock_assembler.build = AsyncMock(
            return_value=[{"role": "system", "content": "You are helpful"}]
        )

        mock_tool = MagicMock()
        mock_tool.execute = AsyncMock(
            return_value=ToolResult(success=True, data="42\n")
        )

        mock_registry = MagicMock()
        mock_registry.get = MagicMock(return_value=mock_tool)

        executor = Executor(
            provider=mock_provider,
            context_assembler=mock_assembler,
            tool_registry=mock_registry,
        )

        plan = Plan(
            action="code",
            requires_tools=True,
            tool_params={"code": "print(42)", "language": "python"},
        )

        result = await executor.execute("conv1", "calculate 42", plan=plan)
        mock_registry.get.assert_called_with("run_code")
        assert result.response.content == "The answer is 42"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_core.py::TestExecutorScheduleAction -v && python -m pytest tests/test_core.py::TestExecutorCodeAction -v`
Expected: FAIL (Executor doesn't accept `scheduler` param)

**Step 3: Update executor.py and agent.py**

In `odigos/core/executor.py`:

Add import at top:
```python
from odigos.providers.base import LLMResponse
```

Add `scheduler` param to `__init__` (add after `skill_registry` param):
```python
    def __init__(
        self,
        provider: LLMProvider,
        context_assembler: ContextAssembler,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        scheduler: TaskScheduler | None = None,
    ) -> None:
        ...
        self.scheduler = scheduler
```

Add to TYPE_CHECKING block:
```python
    from odigos.core.scheduler import TaskScheduler
```

Add `"code": "run_code"` to `_ACTION_TOOLS` dict (line 59-63).

Add schedule handling before the tool execution block (before `tool_name = _ACTION_TOOLS.get(plan.action)`):

```python
        # Handle schedule action directly (no LLM call needed)
        if plan.action == "schedule" and self.scheduler:
            description = plan.tool_params.get("description", "")
            task_id = await self.scheduler.create(
                description=description,
                delay_seconds=plan.schedule_seconds or 0,
                recurrence_seconds=plan.recurrence_seconds,
                conversation_id=conversation_id,
            )
            if plan.recurrence_seconds:
                interval = plan.recurrence_seconds
                unit = "seconds"
                if interval >= 3600:
                    interval = interval // 3600
                    unit = "hour" if interval == 1 else "hours"
                elif interval >= 60:
                    interval = interval // 60
                    unit = "minute" if interval == 1 else "minutes"
                confirmation = f"Scheduled recurring task: {description} (every {interval} {unit})"
            elif plan.schedule_seconds and plan.schedule_seconds > 0:
                delay = plan.schedule_seconds
                if delay >= 3600:
                    time_str = f"{delay // 3600} hour{'s' if delay >= 7200 else ''}"
                elif delay >= 60:
                    time_str = f"{delay // 60} minute{'s' if delay >= 120 else ''}"
                else:
                    time_str = f"{delay} second{'s' if delay != 1 else ''}"
                confirmation = f"Got it, I'll do that in {time_str}: {description}"
            else:
                confirmation = f"Task scheduled: {description}"

            return ExecuteResult(
                response=LLMResponse(content=confirmation, model="system")
            )
```

In `odigos/core/agent.py`:

Add `scheduler` param to `__init__`:
```python
    def __init__(
        self,
        ...
        scheduler: TaskScheduler | None = None,
    ) -> None:
```

Pass it to Executor:
```python
        self.executor = Executor(
            provider,
            self.context_assembler,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            scheduler=scheduler,
        )
```

Add to TYPE_CHECKING:
```python
    from odigos.core.scheduler import TaskScheduler
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_core.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add odigos/core/executor.py odigos/core/agent.py tests/test_core.py
git commit -m "feat: handle schedule and code actions in executor"
```

---

### Task 7: Heartbeat Loop

**Files:**
- Create: `odigos/core/heartbeat.py`
- Test: `tests/test_heartbeat.py`

**Step 1: Write the failing test**

```python
# tests/test_heartbeat.py
import asyncio
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from odigos.core.heartbeat import Heartbeat
from odigos.core.scheduler import TaskScheduler
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path):
    d = Database(tmp_db_path)
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def scheduler(db):
    return TaskScheduler(db=db)


@pytest_asyncio.fixture
async def mock_agent():
    agent = MagicMock()
    agent.handle_message = AsyncMock(return_value="Task completed")
    return agent


@pytest_asyncio.fixture
async def mock_telegram():
    tg = MagicMock()
    tg.send_message = AsyncMock()
    return tg


@pytest_asyncio.fixture
async def heartbeat(db, mock_agent, mock_telegram, scheduler):
    return Heartbeat(
        db=db,
        agent=mock_agent,
        telegram_channel=mock_telegram,
        scheduler=scheduler,
        interval=0.1,  # fast for testing
    )


@pytest.mark.asyncio
async def test_tick_executes_pending_task(heartbeat, scheduler, mock_agent, db):
    """A pending task with scheduled_at in the past should be executed."""
    task_id = await scheduler.create(description="Say hello", delay_seconds=0)
    await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] in ("completed", "failed")
    mock_agent.handle_message.assert_called_once()


@pytest.mark.asyncio
async def test_tick_skips_future_tasks(heartbeat, scheduler, mock_agent):
    """A task scheduled far in the future should not be executed."""
    await scheduler.create(description="Future task", delay_seconds=99999)
    await heartbeat._tick()
    mock_agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_tick_marks_completed(heartbeat, scheduler, db):
    task_id = await scheduler.create(description="Complete me")
    await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] == "completed"
    assert row["completed_at"] is not None


@pytest.mark.asyncio
async def test_tick_handles_failure_and_retries(heartbeat, scheduler, mock_agent, db):
    mock_agent.handle_message = AsyncMock(side_effect=RuntimeError("boom"))
    task_id = await scheduler.create(description="Fail task")
    await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] == "pending"  # still pending, retry_count incremented
    assert row["retry_count"] == 1


@pytest.mark.asyncio
async def test_task_marked_failed_after_max_retries(heartbeat, scheduler, mock_agent, db):
    mock_agent.handle_message = AsyncMock(side_effect=RuntimeError("boom"))
    task_id = await scheduler.create(description="Always fails")
    # Exhaust retries (default max_retries = 3)
    for _ in range(4):
        await heartbeat._tick()
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] == "failed"


@pytest.mark.asyncio
async def test_recurring_task_reinserts(heartbeat, scheduler, db):
    task_id = await scheduler.create(
        description="Recurring", recurrence_seconds=60
    )
    await heartbeat._tick()
    # Original should be completed
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert row["status"] == "completed"
    # A new pending task should exist
    pending = await scheduler.list_pending()
    assert len(pending) == 1
    assert pending[0]["id"] != task_id
    assert pending[0]["description"] == "Recurring"


@pytest.mark.asyncio
async def test_sends_telegram_message_on_completion(heartbeat, scheduler, mock_telegram, db):
    # Create a conversation row first (FK constraint)
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        ("telegram:42", "telegram"),
    )
    await scheduler.create(
        description="Remind about meeting",
        conversation_id="telegram:42",
    )
    await heartbeat._tick()
    mock_telegram.send_message.assert_called_once()
    call_args = mock_telegram.send_message.call_args
    assert "42" in str(call_args)  # chat_id extracted from conversation_id


@pytest.mark.asyncio
async def test_start_and_stop(heartbeat):
    await heartbeat.start()
    assert heartbeat._task is not None
    assert not heartbeat._task.done()
    await heartbeat.stop()
    # Give it a moment to cancel
    await asyncio.sleep(0.05)
    assert heartbeat._task.cancelled() or heartbeat._task.done()


@pytest.mark.asyncio
async def test_max_tasks_per_tick(heartbeat, scheduler, mock_agent):
    """Should only execute max_tasks_per_tick tasks per cycle."""
    heartbeat._max_tasks_per_tick = 2
    for i in range(5):
        await scheduler.create(description=f"Task {i}")
    await heartbeat._tick()
    assert mock_agent.handle_message.call_count == 2


@pytest.mark.asyncio
async def test_paused_heartbeat_skips_execution(heartbeat, scheduler, mock_agent):
    heartbeat.paused = True
    await scheduler.create(description="Should be skipped")
    await heartbeat._tick()
    mock_agent.handle_message.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_heartbeat.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'odigos.core.heartbeat'"

**Step 3: Write the implementation**

```python
# odigos/core/heartbeat.py
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage
from odigos.db import Database

if TYPE_CHECKING:
    from odigos.channels.telegram import TelegramChannel
    from odigos.core.agent import Agent
    from odigos.core.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class Heartbeat:
    """Background loop that executes scheduled tasks."""

    def __init__(
        self,
        db: Database,
        agent: Agent,
        telegram_channel: TelegramChannel,
        scheduler: TaskScheduler,
        interval: float = 30,
        max_tasks_per_tick: int = 5,
    ) -> None:
        self.db = db
        self.agent = agent
        self.telegram_channel = telegram_channel
        self.scheduler = scheduler
        self._interval = interval
        self._max_tasks_per_tick = max_tasks_per_tick
        self._task: asyncio.Task | None = None
        self.paused: bool = False

    async def start(self) -> None:
        """Start the heartbeat as a background asyncio task."""
        self._task = asyncio.create_task(self._loop())
        logger.info("Heartbeat started (interval: %.1fs)", self._interval)

    async def stop(self) -> None:
        """Cancel the loop gracefully."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Heartbeat stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Heartbeat tick failed")
            await asyncio.sleep(self._interval)

    async def _tick(self) -> None:
        """One heartbeat cycle: fetch and execute pending tasks."""
        if self.paused:
            return

        now = datetime.now(timezone.utc).isoformat()
        tasks = await self.db.fetch_all(
            "SELECT * FROM tasks WHERE status = 'pending' "
            "AND (scheduled_at IS NULL OR scheduled_at <= ?) "
            "ORDER BY priority ASC, scheduled_at ASC LIMIT ?",
            (now, self._max_tasks_per_tick),
        )

        for task in tasks:
            await self._execute_task(task)

    async def _execute_task(self, task: dict) -> None:
        task_id = task["id"]
        description = task["description"] or ""

        # Mark as running
        await self.db.execute(
            "UPDATE tasks SET status = 'running', started_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )

        try:
            # Create a synthetic message for the agent
            message = UniversalMessage(
                id=str(uuid.uuid4()),
                channel="heartbeat",
                sender="system",
                content=description,
                timestamp=datetime.now(timezone.utc),
                metadata={"task_id": task_id},
            )

            result = await self.agent.handle_message(message)

            # Mark completed
            await self.db.execute(
                "UPDATE tasks SET status = 'completed', completed_at = ?, "
                "result_json = ? WHERE id = ?",
                (
                    datetime.now(timezone.utc).isoformat(),
                    result[:4000] if result else None,
                    task_id,
                ),
            )
            logger.info("Task %s completed: %s", task_id, description[:50])

            # Send result via Telegram if conversation_id is set
            if task.get("conversation_id"):
                await self._send_result(task["conversation_id"], description, result)

            # Re-insert if recurring
            if task.get("recurrence_json"):
                await self._reinsert_recurring(task)

        except Exception as e:
            retry_count = (task.get("retry_count") or 0) + 1
            max_retries = task.get("max_retries") or 3

            if retry_count >= max_retries:
                await self.db.execute(
                    "UPDATE tasks SET status = 'failed', error = ?, retry_count = ? WHERE id = ?",
                    (str(e), retry_count, task_id),
                )
                logger.error("Task %s failed permanently after %d retries: %s", task_id, retry_count, e)
                # Alert via Telegram if conversation_id set
                if task.get("conversation_id"):
                    await self._send_result(
                        task["conversation_id"],
                        description,
                        f"Task failed after {retry_count} attempts: {e}",
                    )
            else:
                await self.db.execute(
                    "UPDATE tasks SET status = 'pending', error = ?, retry_count = ? WHERE id = ?",
                    (str(e), retry_count, task_id),
                )
                logger.warning("Task %s failed (attempt %d/%d): %s", task_id, retry_count, max_retries, e)

    async def _send_result(self, conversation_id: str, description: str, result: str) -> None:
        """Send task result to the user via Telegram."""
        try:
            # Extract chat_id from conversation_id (format: "telegram:<chat_id>")
            parts = conversation_id.split(":", 1)
            if len(parts) == 2 and parts[0] == "telegram":
                chat_id = int(parts[1])
                message = f"Task completed: {description}\n\n{result}"
                await self.telegram_channel.send_message(chat_id, message[:4000])
        except Exception:
            logger.exception("Failed to send task result via Telegram")

    async def _reinsert_recurring(self, task: dict) -> None:
        """Re-insert a recurring task with the next scheduled_at."""
        import json

        recurrence = json.loads(task["recurrence_json"])
        interval = recurrence.get("interval_seconds", 3600)
        await self.scheduler.create(
            description=task["description"],
            delay_seconds=interval,
            recurrence_seconds=interval,
            priority=task.get("priority", 1),
            conversation_id=task.get("conversation_id"),
            created_by="heartbeat",
        )
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_heartbeat.py -v`
Expected: PASS (10 tests)

**Step 5: Commit**

```bash
git add odigos/core/heartbeat.py tests/test_heartbeat.py
git commit -m "feat: add Heartbeat loop for task execution"
```

---

### Task 8: TelegramChannel — Add send_message and Commands

**Files:**
- Modify: `odigos/channels/telegram.py:18-143` (add send_message method + command handlers)
- Test: `tests/test_telegram_commands.py`

**Step 1: Write the failing test**

```python
# tests/test_telegram_commands.py
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_send_message():
    """TelegramChannel.send_message should call bot.send_message."""
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    channel = TelegramChannel(token="fake", agent=agent)

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    await channel.send_message(chat_id=12345, text="Hello!")
    mock_bot.send_message.assert_called_once_with(chat_id=12345, text="Hello!")


@pytest.mark.asyncio
async def test_tasks_command():
    """The /tasks command should list pending tasks."""
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    scheduler = MagicMock()
    scheduler.list_pending = AsyncMock(return_value=[
        {"id": "abc", "description": "Check email", "scheduled_at": "2026-03-05T10:00:00", "priority": 1},
    ])

    channel = TelegramChannel(token="fake", agent=agent, scheduler=scheduler)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_tasks_command(update, context)
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "Check email" in call_text


@pytest.mark.asyncio
async def test_cancel_command():
    """The /cancel command should cancel a task."""
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    scheduler = MagicMock()
    scheduler.cancel = AsyncMock(return_value=True)

    channel = TelegramChannel(token="fake", agent=agent, scheduler=scheduler)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.text = "/cancel abc-123"
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["abc-123"]

    await channel._handle_cancel_command(update, context)
    scheduler.cancel.assert_called_once_with("abc-123")
    call_text = update.effective_message.reply_text.call_args[0][0]
    assert "cancelled" in call_text.lower()


@pytest.mark.asyncio
async def test_stop_command_pauses_heartbeat():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    heartbeat = MagicMock()
    heartbeat.paused = False

    channel = TelegramChannel(token="fake", agent=agent, heartbeat=heartbeat)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_stop_command(update, context)
    assert heartbeat.paused is True


@pytest.mark.asyncio
async def test_start_command_resumes_heartbeat():
    from odigos.channels.telegram import TelegramChannel

    agent = MagicMock()
    heartbeat = MagicMock()
    heartbeat.paused = True

    channel = TelegramChannel(token="fake", agent=agent, heartbeat=heartbeat)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()

    await channel._handle_start_command(update, context)
    assert heartbeat.paused is False
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_commands.py -v`
Expected: FAIL (TelegramChannel doesn't have send_message or command handlers)

**Step 3: Update telegram.py**

Add `scheduler` and `heartbeat` params to `__init__`:
```python
    def __init__(
        self,
        token: str,
        agent: Agent,
        mode: str = "polling",
        webhook_url: str = "",
        scheduler=None,
        heartbeat=None,
    ) -> None:
        ...
        self.scheduler = scheduler
        self.heartbeat = heartbeat
```

Add `send_message` method:
```python
    async def send_message(self, chat_id: int, text: str) -> None:
        """Send a message to a specific chat."""
        if self._app:
            await self._app.bot.send_message(chat_id=chat_id, text=text)
```

In `start()`, add command handlers before the text handler:
```python
        from telegram.ext import CommandHandler
        self._app.add_handler(CommandHandler("tasks", self._handle_tasks_command))
        self._app.add_handler(CommandHandler("cancel", self._handle_cancel_command))
        self._app.add_handler(CommandHandler("stop", self._handle_stop_command))
        self._app.add_handler(CommandHandler("start", self._handle_start_command))
```

Add command handler methods:
```python
    async def _handle_tasks_command(self, update: Update, context) -> None:
        """List pending tasks."""
        if not self.scheduler:
            await update.effective_message.reply_text("Task scheduler not available.")
            return
        tasks = await self.scheduler.list_pending(limit=10)
        if not tasks:
            await update.effective_message.reply_text("No pending tasks.")
            return
        lines = []
        for t in tasks:
            sched = t.get("scheduled_at", "now")[:16] if t.get("scheduled_at") else "ASAP"
            lines.append(f"- [{t['id'][:8]}] {t['description']} (at {sched})")
        await update.effective_message.reply_text("Pending tasks:\n" + "\n".join(lines))

    async def _handle_cancel_command(self, update: Update, context) -> None:
        """Cancel a task by ID."""
        if not self.scheduler:
            await update.effective_message.reply_text("Task scheduler not available.")
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /cancel <task_id>")
            return
        task_id = context.args[0]
        result = await self.scheduler.cancel(task_id)
        if result:
            await update.effective_message.reply_text(f"Task {task_id[:8]} cancelled.")
        else:
            await update.effective_message.reply_text(f"Task {task_id[:8]} not found or already completed.")

    async def _handle_stop_command(self, update: Update, context) -> None:
        """Pause the heartbeat."""
        if self.heartbeat:
            self.heartbeat.paused = True
            await update.effective_message.reply_text("Heartbeat paused.")
        else:
            await update.effective_message.reply_text("Heartbeat not available.")

    async def _handle_start_command(self, update: Update, context) -> None:
        """Resume the heartbeat."""
        if self.heartbeat:
            self.heartbeat.paused = False
            await update.effective_message.reply_text("Heartbeat resumed.")
        else:
            await update.effective_message.reply_text("Heartbeat not available.")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_telegram_commands.py -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add odigos/channels/telegram.py tests/test_telegram_commands.py
git commit -m "feat: add send_message and Telegram commands for task management"
```

---

### Task 9: Config Updates

**Files:**
- Modify: `odigos/config.py:37-75` (add HeartbeatConfig, SandboxConfig)
- Test: `tests/test_config.py` (if exists, add tests; otherwise test inline)

**Step 1: Write the failing test**

```python
# tests/test_config_new.py
import pytest
from odigos.config import Settings


def test_heartbeat_config_defaults():
    s = Settings(telegram_bot_token="t", openrouter_api_key="k")
    assert s.heartbeat.interval_seconds == 30
    assert s.heartbeat.max_tasks_per_tick == 5


def test_sandbox_config_defaults():
    s = Settings(telegram_bot_token="t", openrouter_api_key="k")
    assert s.sandbox.timeout_seconds == 5
    assert s.sandbox.max_memory_mb == 512
    assert s.sandbox.allow_network is False


def test_heartbeat_config_override():
    s = Settings(
        telegram_bot_token="t",
        openrouter_api_key="k",
        heartbeat={"interval_seconds": 60, "max_tasks_per_tick": 10},
    )
    assert s.heartbeat.interval_seconds == 60
    assert s.heartbeat.max_tasks_per_tick == 10


def test_sandbox_config_override():
    s = Settings(
        telegram_bot_token="t",
        openrouter_api_key="k",
        sandbox={"timeout_seconds": 10, "max_memory_mb": 1024, "allow_network": True},
    )
    assert s.sandbox.timeout_seconds == 10
    assert s.sandbox.max_memory_mb == 1024
    assert s.sandbox.allow_network is True
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_new.py -v`
Expected: FAIL (Settings has no `heartbeat` or `sandbox` attribute)

**Step 3: Update config.py**

Add after `SkillsConfig` class (line 55-56):

```python
class HeartbeatConfig(BaseModel):
    interval_seconds: int = 30
    max_tasks_per_tick: int = 5


class SandboxConfig(BaseModel):
    timeout_seconds: int = 5
    max_memory_mb: int = 512
    allow_network: bool = False
```

Add to `Settings` class (after `skills` field):
```python
    heartbeat: HeartbeatConfig = HeartbeatConfig()
    sandbox: SandboxConfig = SandboxConfig()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config_new.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add odigos/config.py tests/test_config_new.py
git commit -m "feat: add HeartbeatConfig and SandboxConfig"
```

---

### Task 10: Wire Everything in main.py

**Files:**
- Modify: `odigos/main.py:1-214` (add scheduler, sandbox, heartbeat initialization)

**Step 1: Write the failing test**

This is a wiring task, so we verify with an integration-style import test:

```python
# tests/test_main_wiring.py
import pytest


def test_all_new_modules_importable():
    """Verify all new modules can be imported without errors."""
    from odigos.core.scheduler import TaskScheduler
    from odigos.core.heartbeat import Heartbeat
    from odigos.providers.sandbox import SandboxProvider
    from odigos.tools.code import CodeTool

    assert TaskScheduler is not None
    assert Heartbeat is not None
    assert SandboxProvider is not None
    assert CodeTool is not None
```

**Step 2: Run test to verify it passes** (should pass already, but confirms nothing is broken)

Run: `python -m pytest tests/test_main_wiring.py -v`
Expected: PASS

**Step 3: Update main.py**

Add module-level references after existing ones (around line 36):
```python
_heartbeat = None
```

In `lifespan()`, update global declaration (line 42):
```python
    global _db, _provider, _embedder, _telegram, _searxng, _scraper, _router, _heartbeat
```

After the doc_tool registration (after line 134), add sandbox initialization:
```python
    # Initialize code sandbox
    from odigos.providers.sandbox import SandboxProvider
    from odigos.tools.code import CodeTool

    sandbox = SandboxProvider(
        timeout=settings.sandbox.timeout_seconds,
        max_memory_mb=settings.sandbox.max_memory_mb,
        allow_network=settings.sandbox.allow_network,
    )
    code_tool = CodeTool(sandbox=sandbox)
    tool_registry.register(code_tool)
    logger.info("Code sandbox initialized (timeout: %ds, memory: %dMB)",
                settings.sandbox.timeout_seconds, settings.sandbox.max_memory_mb)
```

After skill_registry initialization (after line 139), add scheduler:
```python
    # Initialize task scheduler
    from odigos.core.scheduler import TaskScheduler

    scheduler = TaskScheduler(db=_db)
    logger.info("Task scheduler initialized")
```

Update Agent initialization to include scheduler (around line 147):
```python
    agent = Agent(
        db=_db,
        provider=_router,
        agent_name=settings.agent.name,
        memory_manager=memory_manager,
        personality_path=settings.personality.path,
        planner_provider=_router,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        cost_fetcher=_delayed_cost_fetcher,
        scheduler=scheduler,
    )
```

After Telegram initialization and start (after line 167), add heartbeat:
```python
    # Initialize heartbeat
    from odigos.core.heartbeat import Heartbeat

    _heartbeat = Heartbeat(
        db=_db,
        agent=agent,
        telegram_channel=_telegram,
        scheduler=scheduler,
        interval=settings.heartbeat.interval_seconds,
        max_tasks_per_tick=settings.heartbeat.max_tasks_per_tick,
    )
    await _heartbeat.start()
    logger.info("Heartbeat started (interval: %ds)", settings.heartbeat.interval_seconds)

    # Wire scheduler and heartbeat back to Telegram for commands
    _telegram.scheduler = scheduler
    _telegram.heartbeat = _heartbeat
```

In shutdown section (before Telegram stop, around line 174), add heartbeat stop:
```python
    if _heartbeat:
        await _heartbeat.stop()
```

**Step 4: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add odigos/main.py tests/test_main_wiring.py
git commit -m "feat: wire scheduler, sandbox, and heartbeat in main.py"
```

---

### Task 11: Full Integration Verification

**Files:**
- No new files — verification only

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

**Step 2: Run linter**

Run: `ruff check odigos/ tests/`
Expected: No errors

**Step 3: Verify imports**

Run: `python -c "from odigos.core.scheduler import TaskScheduler; from odigos.core.heartbeat import Heartbeat; from odigos.providers.sandbox import SandboxProvider; from odigos.tools.code import CodeTool; print('All imports OK')"`
Expected: "All imports OK"

**Step 4: Verify migration applies cleanly**

Run: `python -c "import asyncio; from odigos.db import Database; db = Database(':memory:'); asyncio.run(db.initialize()); print('Migrations OK')"`
Expected: "Migrations OK"

**Step 5: Commit** (only if any fixups were needed)

```bash
git add -A
git commit -m "fix: integration fixes for Phase 2 gaps"
```
