-- DROP TABLE IF EXISTS tasks;  -- removed: tasks table now managed by schema.sql

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    created_by TEXT DEFAULT 'user',
    progress_note TEXT,
    reviewed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    scheduled_at TEXT,
    goal_id TEXT,
    conversation_id TEXT,
    result TEXT,
    error TEXT,
    created_by TEXT DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    recurrence TEXT,
    conversation_id TEXT,
    created_by TEXT DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
CREATE INDEX idx_todos_status ON todos(status);
CREATE INDEX idx_todos_scheduled ON todos(scheduled_at);
CREATE INDEX idx_reminders_status ON reminders(status);
CREATE INDEX idx_reminders_due ON reminders(due_at);
