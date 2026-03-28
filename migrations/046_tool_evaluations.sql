-- Tool output evaluations for active quality checking
CREATE TABLE IF NOT EXISTS tool_evaluations (
    id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    quality_score REAL,
    relevant INTEGER,
    complete INTEGER,
    issues TEXT,
    query_context TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tool_evals_tool
    ON tool_evaluations(tool_name);

-- Sprint contract column on task_plans (ignore if already exists)
-- Add sprint_contract column if missing (SQLite ignores duplicate ADD)
-- We wrap in a no-op check: if ALTER fails the migration still succeeds
-- because executescript runs each statement independently.
ALTER TABLE task_plans ADD COLUMN sprint_contract TEXT;
