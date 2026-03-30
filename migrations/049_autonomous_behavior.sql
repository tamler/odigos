-- Goal and status columns on task_plans for autonomous plan execution
ALTER TABLE task_plans ADD COLUMN goal TEXT;
ALTER TABLE task_plans ADD COLUMN status TEXT DEFAULT 'in_progress';

-- Heartbeat session log for idle work persistence
CREATE TABLE IF NOT EXISTS heartbeat_sessions (
    id TEXT PRIMARY KEY,
    goal_id TEXT,
    todo_id TEXT,
    plan_id TEXT,
    conversation_id TEXT,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
