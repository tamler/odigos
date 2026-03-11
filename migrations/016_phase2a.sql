-- Agent registry: known peers on the mesh
CREATE TABLE IF NOT EXISTS agent_registry (
    agent_name TEXT PRIMARY KEY,
    role TEXT,
    description TEXT,
    specialty TEXT,
    netbird_ip TEXT,
    ws_port INTEGER DEFAULT 8001,
    status TEXT DEFAULT 'offline',
    last_seen TEXT,
    capabilities TEXT,
    evolution_score REAL,
    allow_external_evaluation INTEGER DEFAULT 0,
    parent TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Strategist run history
CREATE TABLE IF NOT EXISTS strategist_runs (
    id TEXT PRIMARY KEY,
    evaluations_analyzed INTEGER,
    hypotheses_generated TEXT,
    specialization_proposals TEXT,
    direction_log_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Specialization proposals awaiting user approval
CREATE TABLE IF NOT EXISTS specialization_proposals (
    id TEXT PRIMARY KEY,
    proposed_by TEXT,
    role TEXT NOT NULL,
    specialty TEXT,
    description TEXT NOT NULL,
    rationale TEXT,
    seed_knowledge TEXT,
    status TEXT DEFAULT 'pending',
    approved_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON specialization_proposals(status);

-- Add evaluator_agent column to evaluations table for cross-agent eval tracking
ALTER TABLE evaluations ADD COLUMN evaluator_agent TEXT;
