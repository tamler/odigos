# Subagent Spawning Design

**Date:** 2026-03-09
**Status:** Approved
**Phase:** 3, item #6

## Context

Some tasks shouldn't block the main conversation (e.g., multi-step research, background processing). Subagents let the main agent delegate work to isolated background tasks. The architecture (section 4.15) describes this as depth-limited delegation.

## Decisions

1. **Tool-based spawning** -- LLM calls `spawn_subagent` tool to delegate work. The delegation decision is the LLM's.
2. **Results stored in DB, delivered on next turn** -- Subagent writes result to `subagent_tasks` table. Heartbeat picks up completed results and delivers them as proactive messages.
3. **No conversation overhead** -- Subagents don't create conversations or persist messages. They run the Executor, produce a result, and traces capture the details.
4. **No tool restrictions (for now)** -- Subagents get all tools except `spawn_subagent` itself. Restriction mechanism can be added later.
5. **Heartbeat delivers results** -- Completed results are processed during heartbeat tick, same pattern as reminders.

## Components

### 1. SubagentManager (`odigos/core/subagent.py`)

```python
class SubagentManager:
    async def spawn(instruction, parent_conversation_id, timeout=600) -> str
    async def _run_subagent(subagent_id, instruction, parent_conversation_id, timeout)
    async def get_completed(parent_conversation_id) -> list[dict]
    async def get_completed_all() -> list[dict]
    async def mark_delivered(subagent_id)
```

**spawn():**
1. Check concurrent count for conversation -- if >= 3, return error
2. Insert `subagent_tasks` row (status=running)
3. Build restricted tool registry (clone parent's, remove spawn_subagent)
4. `asyncio.create_task(_run_subagent(...))`
5. Return subagent ID

**_run_subagent():**
1. Build context: system message with instruction + memory recall results
2. Create fresh Executor with restricted tools, same provider/tracer
3. Wrap in `asyncio.wait_for(executor.execute(...), timeout)`
4. On success: status=completed, result=response content
5. On timeout/exception: status=failed, result=error message
6. Emit trace event `subagent_completed`

No ContextAssembler -- builds a simple messages list directly.

### 2. SpawnSubagentTool (`odigos/tools/subagent_tool.py`)

Tool wrapping `SubagentManager.spawn()`. Parameters: `instruction` (required string), `timeout` (optional int, default 600).

### 3. Database migration

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

### 4. Heartbeat integration

In `_tick()`, after reminders and todos:
- Call `subagent_manager.get_completed_all()`
- For each result, deliver as proactive message via `_send_proactive()`
- Call `mark_delivered(subagent_id)`

### 5. Constraints

- Max depth: 1 (spawn_subagent excluded from subagent tool set)
- Max concurrent per conversation: 3
- Default timeout: 600s (10 min)
- Subagent gets: instruction, memory recall, all tools minus spawn_subagent
- Subagent does NOT get: parent conversation history

### 6. Testing

- **TestSubagentManager** -- spawn creates row, returns ID, enforces max 3 concurrent, get_completed/mark_delivered work correctly
- **TestSubagentExecution** -- mock executor, verify result stored on completion/timeout/exception
- **TestSpawnSubagentTool** -- tool metadata, calls manager.spawn, returns ID
- **TestSubagentInHeartbeat** -- completed results delivered and marked
- **TestSubagentToolExclusion** -- restricted registry excludes spawn_subagent
