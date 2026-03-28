CREATE TABLE IF NOT EXISTS user_profile_v2 (
    id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now'))
);
