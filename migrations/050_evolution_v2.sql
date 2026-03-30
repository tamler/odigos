-- Domain performance tracking (daily rollups per classification)
CREATE TABLE IF NOT EXISTS domain_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    date TEXT NOT NULL,
    avg_score REAL NOT NULL DEFAULT 0.0,
    eval_count INTEGER NOT NULL DEFAULT 0,
    avg_duration_ms REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    UNIQUE(domain, date)
);

-- Promoted evolution parameter overrides (survive restarts)
-- Stored in kv table: key = 'evolution_override:{param_name}', value = new value
