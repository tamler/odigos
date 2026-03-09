# Observability Design

**Date:** 2026-03-08
**Status:** Approved
**Phase:** 3, item #4

## Context

The architecture describes a `trace.emit()` system at agent decision points as the foundation for the hook/plugin lifecycle (Phase 3 item #5). The existing `action_log` table tracks tool calls but nothing else. This feature builds the full trace infrastructure so hooks can subscribe to a unified event stream.

## Decisions

1. **Infrastructure only** -- no user-facing metrics or dashboards in this pass.
2. **DB-persisted** -- traces go to a `traces` table in SQLite. Hooks subscribe later; historical data is queryable.
3. **Replaces action_log** -- `trace.emit()` subsumes `action_log`. Tool calls become one trace type among many. Single table, single pattern.
4. **Full instrumentation** -- agent, executor, reflector, and heartbeat all emit traces.

## Components

### 1. Trace module

New `odigos/core/trace.py` with a `Tracer` class:

```python
class Tracer:
    def __init__(self, db: Database) -> None: ...
    async def emit(self, event_type: str, conversation_id: str | None, data: dict) -> str: ...
```

`emit()` inserts a row into the `traces` table and returns the trace ID. `data` is a freeform dict serialized as JSON.

Implemented event types: `step_start`, `tool_call`, `tool_result`, `response`, `timeout`, `budget_exceeded`, `reflection`, `correction_detected`, `entity_extracted`, `heartbeat_tick`.

Deferred event types (no clear emission point yet): `step_end` (redundant with `response`), `planner_decision` (no separate planner exists), `goal_processed` (heartbeat tracks at tick level), `warning`.

### 2. Database migration

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

### 3. Instrumentation sites

**Agent (`_run()`):**
- `step_start` -- message arrives (user message preview)
- `response` -- final response ready (token counts, cost, model)
- `timeout` -- on TimeoutError
- `budget_exceeded` -- budget check fails

**Executor (`execute()`, replacing `_log_action()`):**
- `tool_call` -- before tool execution (tool name, params, active skill)
- `tool_result` -- after tool execution (success/failure, error, duration)
- `planner_decision` -- planner selects next action

**Reflector (`reflect()`):**
- `reflection` -- reflection completes (message stored)
- `correction_detected` -- correction block parsed
- `entity_extracted` -- entities parsed

**Heartbeat (`_tick()`):**
- `heartbeat_tick` -- each cycle (goals/todos processed count)

### 4. Migration of existing code

- Executor's `_log_action()` replaced by `tracer.emit("tool_call", ...)` and `tracer.emit("tool_result", ...)`
- `tests/test_action_log.py` rewritten as `tests/test_trace.py`
- `Tracer` created in `main.py`, threaded through Agent -> Executor, Reflector. Heartbeat gets its own reference.

### 5. Testing

- **TestTracer** -- unit tests for emit(): inserts row, returns ID, serializes data_json, handles None conversation_id.
- **TestTracerInExecutor** -- tool_call and tool_result traces (replaces action_log tests). Active skill context captured.
- **TestTracerInAgent** -- step_start, response, timeout, budget_exceeded traces.
- **TestTracerInReflector** -- reflection, correction_detected, entity_extracted traces.
