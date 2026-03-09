-- Approval gate: log every approval decision for agent learning
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    tool_name TEXT NOT NULL,
    arguments_json TEXT,
    decision TEXT NOT NULL DEFAULT 'pending',  -- pending, approved, denied, timeout
    chat_id INTEGER,
    requested_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_decision ON approvals(decision);
CREATE INDEX IF NOT EXISTS idx_approvals_tool ON approvals(tool_name);
