CREATE TABLE IF NOT EXISTS corrections (
    id TEXT PRIMARY KEY,
    timestamp TEXT DEFAULT (datetime('now')),
    conversation_id TEXT,
    original_response TEXT,
    correction TEXT,
    context TEXT,
    category TEXT,
    applied_count INTEGER DEFAULT 0
);
