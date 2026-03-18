-- Unified scheduling table for one-shot and recurring tasks.
-- Replaces the separate reminders + cron_entries approach with a single table.

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'once',   -- 'once' or 'recurring'
    schedule TEXT,                        -- cron expression for recurring, ISO datetime for once
    action TEXT NOT NULL,                 -- what to do (message content, reminder text, etc.)
    action_type TEXT DEFAULT 'remind',   -- 'remind', 'execute', 'notify'
    conversation_id TEXT,
    goal_id TEXT,                         -- optional link to a goal
    enabled INTEGER DEFAULT 1,
    last_run_at TEXT,
    next_run_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next ON scheduled_tasks(next_run_at);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_type ON scheduled_tasks(type);
