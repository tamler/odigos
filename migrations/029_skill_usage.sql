CREATE TABLE IF NOT EXISTS skill_usage (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    message_id TEXT,
    skill_name TEXT NOT NULL,
    skill_type TEXT DEFAULT 'text',  -- 'text' or 'code'
    success INTEGER DEFAULT 1,       -- 1 = used successfully, 0 = error
    evaluation_score REAL,           -- linked after evaluator runs
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_usage_skill ON skill_usage(skill_name);
CREATE INDEX IF NOT EXISTS idx_skill_usage_created ON skill_usage(created_at);
