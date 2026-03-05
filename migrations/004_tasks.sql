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
