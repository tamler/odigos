CREATE TABLE IF NOT EXISTS user_profile (
    id TEXT PRIMARY KEY DEFAULT 'owner',
    communication_style TEXT DEFAULT '',
    expertise_areas TEXT DEFAULT '',
    preferences TEXT DEFAULT '',
    recurring_topics TEXT DEFAULT '',
    correction_patterns TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    last_analyzed_at TEXT,
    conversation_count INTEGER DEFAULT 0
);

-- Seed with empty profile
INSERT OR IGNORE INTO user_profile (id) VALUES ('owner');
