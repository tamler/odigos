CREATE TABLE IF NOT EXISTS user_facts (
    id TEXT PRIMARY KEY,
    fact TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    source TEXT DEFAULT 'extracted',
    confidence REAL DEFAULT 0.8,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_facts_category ON user_facts(category);
