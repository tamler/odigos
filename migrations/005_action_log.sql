-- Action log: tracks planner decisions and tool executions
CREATE TABLE IF NOT EXISTS action_log (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    action_type TEXT NOT NULL,
    action_name TEXT,
    details_json TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_action_log_conversation ON action_log(conversation_id);
CREATE INDEX IF NOT EXISTS idx_action_log_timestamp ON action_log(timestamp);
