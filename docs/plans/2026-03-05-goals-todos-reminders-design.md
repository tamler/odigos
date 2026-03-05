# Goals, Todos, Reminders: Replacing the Task Queue

**Date:** 2026-03-05
**Status:** Approved

## Summary

Replace the generic `tasks` table and `TaskScheduler` with three semantically distinct concepts: goals (long-lived aspirations), todos (concrete work items), and reminders (time-triggered notifications). The heartbeat becomes the agent's idle mind -- it checks reminders first, works on todos, and when nothing is pressing, reviews goals and decides if there's something useful to do.

## Motivation

The current task system tries to be everything: scheduler, job queue, reminder, recurring task. The PRD update recognizes that these are three different things with different cadences:

- **Goals** -- reviewed during idle time, long-lived
- **Todos** -- checked every heartbeat tick, concrete and actionable
- **Reminders** -- fired when due, time-triggered notifications

The skills system handles *how* to do things. Goals/todos/reminders handle *what* to think about and *when*. The LLM bridges the two.

## Schema

### goals
```sql
CREATE TABLE goals (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'active',    -- active, paused, completed, archived
    created_by TEXT DEFAULT 'user',  -- user, agent
    progress_note TEXT,              -- agent's latest reflection on progress
    reviewed_at TEXT,                -- last time the agent thought about this
    created_at TEXT DEFAULT (datetime('now'))
);
```

### todos
```sql
CREATE TABLE todos (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'pending',   -- pending, running, completed, failed
    scheduled_at TEXT,               -- NULL = do it now, otherwise wait
    goal_id TEXT,                    -- optional link to a goal
    conversation_id TEXT,            -- for sending results back
    result TEXT,
    error TEXT,
    created_by TEXT DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now'))
);
```

### reminders
```sql
CREATE TABLE reminders (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT DEFAULT 'pending',   -- pending, fired, cancelled
    recurrence TEXT,                 -- NULL or e.g. "daily", "weekly", "every 3600s"
    conversation_id TEXT,
    created_by TEXT DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now'))
);
```

Migration 006 drops the old `tasks` table and creates these three. No retry columns -- if a todo fails, the agent decides whether to try again.

## Heartbeat Loop

Priority-ordered tick every 30 seconds:

1. **Fire due reminders** -- `WHERE due_at <= now AND status = 'pending'`. Mark fired. Send enriched Telegram notification (LLM adds context from memories before sending). Reinsert recurring reminders.
2. **Work on pending todos** -- `WHERE status = 'pending' AND (scheduled_at IS NULL OR scheduled_at <= now)` limit 3. Execute through `agent.handle_message()`. Mark completed/failed. Notify linked conversation.
3. **Idle thoughts** -- only if nothing above ran, and at most every 15 minutes. Load active goals, call LLM: "Here are your current goals. Is there anything useful you could do right now?" LLM can create a todo, update a goal's progress_note, or do nothing.

## Planner Changes

The `schedule` action splits into three intents:

- `{"action": "remind", "description": "...", "due_at_seconds": N}` -- time-triggered notification
- `{"action": "todo", "description": "...", "delay_seconds": 0}` -- concrete work item
- `{"action": "goal", "description": "..."}` -- long-lived aspiration

The LLM classifies based on context. "Remind me" = reminder. "Do X in 2 hours" = todo. "I want to X" = goal.

## Executor Changes

Each new action bypasses the LLM (same pattern as current schedule handler):
- `remind` → insert into reminders, return confirmation
- `todo` → insert into todos, return confirmation
- `goal` → insert into goals, return confirmation

## GoalStore

Replaces `TaskScheduler`. Single class with CRUD for all three tables:
- `create_goal()`, `list_goals()`, `update_goal()`
- `create_todo()`, `list_todos()`, `complete_todo()`, `fail_todo()`
- `create_reminder()`, `list_reminders()`, `cancel_reminder()`
- `cancel(id)` -- works across all three tables

## Telegram Commands

- `/goals` -- list active goals
- `/todos` -- list pending todos
- `/reminders` -- list pending reminders
- `/cancel <id>` -- prefix match across all three tables
- `/stop` / `/start` -- pause/resume heartbeat (unchanged)
- `/status` -- unchanged (budget + heartbeat)

## Notification Behavior

- Reminders: always notify immediately
- Todos: notify linked conversation on completion/failure
- Idle thoughts: agent judges importance. High-value discoveries notify immediately. Low-value observations stored as progress_note on the goal.

## What Gets Removed

- `odigos/core/scheduler.py` -- replaced by GoalStore
- `odigos/core/heartbeat.py` -- rewritten
- `migrations/004_tasks.sql` -- replaced by migration 006
- `tests/test_scheduler.py`, `tests/test_heartbeat.py` -- replaced

## What Changes

- `executor.py` -- schedule handler → remind/todo/goal handlers
- `planner.py` -- CLASSIFY_PROMPT updated, Plan dataclass updated
- `agent.py` -- scheduler param → goal_store param
- `telegram.py` -- new commands, updated params
- `main.py` -- wire GoalStore and rewritten Heartbeat
- `config.py` -- add idle_think_interval (default 900s)
- `test_core.py` -- update schedule/planner tests

## Config Addition

```python
class HeartbeatConfig:
    interval_seconds: int = 30
    max_todos_per_tick: int = 3
    idle_think_interval: int = 900  # 15 minutes between idle thoughts
```
