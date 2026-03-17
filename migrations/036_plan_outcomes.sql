CREATE TABLE IF NOT EXISTS plan_outcomes (
    plan_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    outcome_score REAL,
    outcome_summary TEXT,
    evaluated_at TEXT,
    created_at TEXT NOT NULL
);
