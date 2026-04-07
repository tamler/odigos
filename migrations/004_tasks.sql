-- Ensure tasks table exists (also defined in schema.sql for fresh installs)
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    description TEXT,
    conversation_id TEXT,
    tool_name TEXT,
    external_task_id TEXT,
    arguments_json TEXT,
    result_json TEXT,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);
