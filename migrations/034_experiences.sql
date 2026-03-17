CREATE TABLE IF NOT EXISTS agent_experiences (
    id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    situation TEXT NOT NULL,
    outcome TEXT NOT NULL,
    lesson TEXT NOT NULL,
    success INTEGER DEFAULT 1,
    times_applied INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experiences_tool ON agent_experiences(tool_name);
