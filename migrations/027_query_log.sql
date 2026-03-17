CREATE TABLE IF NOT EXISTS query_log (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    conversation_id TEXT NOT NULL,
    message_id TEXT,
    classification TEXT NOT NULL,
    classifier_tier INTEGER DEFAULT 1,
    classifier_confidence REAL,
    entities TEXT,
    search_queries TEXT,
    sub_questions TEXT,
    tools_used TEXT,
    duration_ms INTEGER,
    evaluation_score REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_query_log_classification ON query_log(classification);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at);
