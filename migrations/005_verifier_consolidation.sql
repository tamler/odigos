-- Add consolidated_at to corrections (for existing DBs)
ALTER TABLE corrections ADD COLUMN consolidated_at TEXT;

-- Mark pre-existing corrections as pre-migration (cold start safety)
UPDATE corrections SET consolidated_at = 'pre-migration'
WHERE created_at < datetime('now', '-30 days');

-- Skill verification history
CREATE TABLE IF NOT EXISTS skill_verifications (
    id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    scenarios_json TEXT,
    results_json TEXT,
    overall_score REAL,
    escalation_level INTEGER DEFAULT 0,
    diagnostics TEXT,
    model_used TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_skill_verifications_skill
    ON skill_verifications(skill_name);

-- Consolidation audit log
CREATE TABLE IF NOT EXISTS consolidation_log (
    id TEXT PRIMARY KEY,
    axis TEXT NOT NULL,
    corrections_processed INTEGER,
    operations_json TEXT,
    rules_before INTEGER,
    rules_after INTEGER,
    compacted INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
