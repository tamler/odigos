-- Plan persistence for decomposed tasks
CREATE TABLE IF NOT EXISTS task_plans (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    steps TEXT NOT NULL,          -- JSON array of {step, task, status, result}
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_plans_conv ON task_plans(conversation_id);

-- Error learning across conversations
CREATE TABLE IF NOT EXISTS tool_errors (
    id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    error_type TEXT,              -- timeout, not_found, validation, permission, unknown
    error_message TEXT,
    query_context TEXT,           -- what the user asked when this failed
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_errors_tool ON tool_errors(tool_name);
