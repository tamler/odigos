# Phase 2 Gaps: Heartbeat System + Code Execution Sandbox

**Date:** 2026-03-05
**Status:** Approved

---

## Goal

Fill the remaining Phase 2 gaps identified in the PRD:
1. **Task scheduling** -- "remind me to X in 2 hours" works
2. **Code execution sandbox** -- run Python/shell in a sandboxed subprocess

These are designed together because the sandbox becomes a tool the heartbeat can invoke.

---

## Decisions Made

- **Sandbox isolation:** subprocess + `ulimit` resource limits (no Docker, no nsjail)
- **Languages:** Python + shell scripts
- **Proactive messages:** Heartbeat sends Telegram messages directly when tasks complete
- **Task creation:** `TaskScheduler` utility class -- single interface for all callers (executor, heartbeat, future agent tool-calling)

---

## 1. Tasks Table

New migration `004_tasks.sql`:

```sql
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,           -- "one_shot", "recurring"
    status TEXT DEFAULT 'pending',-- "pending", "running", "completed", "failed", "cancelled"
    description TEXT,
    payload_json TEXT,            -- task-specific params
    scheduled_at TEXT,            -- ISO timestamp, NULL = run ASAP
    started_at TEXT,
    completed_at TEXT,
    result_json TEXT,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    priority INTEGER DEFAULT 1,  -- 0=DO NOW, 1=DO SOON, 2=DO LATER
    recurrence_json TEXT,         -- {"interval_seconds": 3600}
    conversation_id TEXT,         -- which conversation to send results to
    created_by TEXT DEFAULT 'user'
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_scheduled ON tasks(scheduled_at);
```

---

## 2. TaskScheduler

`odigos/core/scheduler.py` -- central task CRUD utility.

```python
class TaskScheduler:
    def __init__(self, db): ...
    async def create(self, description, delay_seconds=0, recurrence_seconds=None,
                     priority=1, conversation_id=None, created_by="user",
                     payload=None) -> str
    async def cancel(self, task_id) -> bool
    async def list_pending(self, limit=20) -> list[dict]
    async def get(self, task_id) -> dict | None
```

Callers:

| Caller | When | Example |
|--------|------|---------|
| Executor | User says "remind me in 2 hours" | Planner returns `action="schedule"` |
| Heartbeat | Recurring task completes | Re-inserts with next `scheduled_at` |
| Heartbeat | Task produces follow-up | Agent processes task, planner detects scheduling intent |
| Future: Agent tool-calling | Agent decides mid-response to schedule | LLM tool call routed to `scheduler.create()` |

---

## 3. Heartbeat Loop

`odigos/core/heartbeat.py` -- background async loop.

- Wakes every 30 seconds (configurable)
- Fetches pending tasks where `scheduled_at <= now` (or NULL)
- Executes up to `max_tasks_per_tick` (default 5) per cycle
- Task execution: passes task `description` through `agent.handle_message()` as a synthetic message
- On success: marks completed, sends result to Telegram if `conversation_id` set
- On failure: increments `retry_count`, marks `failed` after `max_retries` (default 3), alerts via Telegram
- Recurring tasks: re-insert next occurrence via `TaskScheduler.create()`
- Circuit breaker: max 5 tasks per tick, 30s minimum interval, `/stop` command pauses

---

## 4. Planner Integration

Two new actions in `CLASSIFY_PROMPT`:

**Schedule action:**
```json
{"action": "schedule", "description": "<what to do>", "delay_seconds": 7200, "recurrence_seconds": null, "skill": null}
```

Guidance: `Schedule IS needed for: "remind me", "in X hours", "later today", "tomorrow morning", "every day at", any time-based request.`

The LLM returns `delay_seconds` (relative), not absolute timestamps. Executor computes `scheduled_at = now + delay_seconds`.

**Code action:**
```json
{"action": "code", "code": "<code>", "language": "python|shell", "skill": null}
```

Guidance: `Code IS needed for: math calculations, data processing, running scripts, "calculate", "compute", any request that requires executing code.`

`Plan` dataclass gets `schedule_seconds: int | None` and `recurrence_seconds: int | None`.

Schedule action returns a direct confirmation ("Got it, I'll remind you in 2 hours") without an LLM call.

---

## 5. Code Execution Sandbox

**`odigos/providers/sandbox.py`:**

```python
@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool

class SandboxProvider:
    def __init__(self, timeout=5, max_memory_mb=512, allow_network=False): ...
    async def execute(self, code: str, language: str = "python") -> SandboxResult: ...
```

Sandboxing (Linux):
- `ulimit -t 5` -- CPU time cap
- `ulimit -v 524288` -- memory cap (512MB)
- `unshare --net` -- no network access
- `asyncio.wait_for(timeout=10)` -- wall-clock backstop

macOS dev: skip `unshare`, log warning. `ulimit` works on both.

Languages:
- `python` via `python3 -c "<code>"`
- `shell` via `bash -c "set -euo pipefail; <code>"`

Output truncated at 4000 chars.

**`odigos/tools/code.py`:**

```python
class CodeTool(BaseTool):
    name = "run_code"
    description = "Execute Python or shell code in a sandboxed environment"
```

---

## 6. Wiring (main.py)

- Initialize `TaskScheduler(db)`
- Initialize `SandboxProvider` + `CodeTool`, register in tool registry
- Pass `scheduler` to `Agent` (executor uses it for schedule actions)
- Initialize `Heartbeat(db, agent, telegram_channel, scheduler)`
- Start heartbeat in lifespan, stop on shutdown

Config additions:

```python
class HeartbeatConfig(BaseModel):
    interval_seconds: int = 30
    max_tasks_per_tick: int = 5

class SandboxConfig(BaseModel):
    timeout_seconds: int = 5
    max_memory_mb: int = 512
    allow_network: bool = False
```

---

## 7. Telegram Commands

Simple command handlers in `TelegramChannel` (not routed through agent):

- `/tasks` -- list pending tasks with scheduled times
- `/cancel <id>` -- cancel a task
- `/stop` -- pause heartbeat (emergency stop)
- `/start` -- resume heartbeat

---

## Future: Agent-Initiated Scheduling

`TaskScheduler` is designed as the single interface. When we add LLM tool-calling (Phase 3), the agent emits a tool call that routes to `scheduler.create()`. No redesign needed -- just a new caller for the same method.
