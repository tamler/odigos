-- Extend tasks table for sub-agent support
ALTER TABLE tasks ADD COLUMN persona TEXT;
ALTER TABLE tasks ADD COLUMN parent_task_id TEXT;
ALTER TABLE tasks ADD COLUMN concurrency_key TEXT DEFAULT 'default';
ALTER TABLE tasks ADD COLUMN max_runtime_seconds INTEGER DEFAULT 600;
ALTER TABLE tasks ADD COLUMN cancel_requested INTEGER DEFAULT 0;
ALTER TABLE tasks ADD COLUMN started_at TEXT;
ALTER TABLE tasks ADD COLUMN artifact_path TEXT;
ALTER TABLE tasks ADD COLUMN duration_ms INTEGER;
ALTER TABLE tasks ADD COLUMN cost_usd REAL;

CREATE INDEX IF NOT EXISTS idx_tasks_type_status ON tasks(type, status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);

-- Add parent_conversation_id to conversations
ALTER TABLE conversations ADD COLUMN parent_conversation_id TEXT;
CREATE INDEX IF NOT EXISTS idx_conversations_parent ON conversations(parent_conversation_id);
