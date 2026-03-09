CREATE TABLE IF NOT EXISTS subagent_tasks (
    id TEXT PRIMARY KEY,
    parent_conversation_id TEXT NOT NULL REFERENCES conversations(id),
    instruction TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    result TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    delivered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_subagent_parent ON subagent_tasks(parent_conversation_id);
CREATE INDEX IF NOT EXISTS idx_subagent_status ON subagent_tasks(status);
