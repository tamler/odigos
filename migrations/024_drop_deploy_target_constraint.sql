-- Relax deploy_target column: remove NOT NULL and FK constraint.
-- The deploy_targets feature was never implemented; this lets existing
-- rows keep their data while new inserts omit deploy_target.

CREATE TABLE IF NOT EXISTS spawned_agents_new (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    description TEXT,
    deploy_target TEXT DEFAULT '',
    proposal_id TEXT,
    config_snapshot TEXT,
    status TEXT DEFAULT 'deploying',
    deployed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

INSERT INTO spawned_agents_new
    SELECT id, agent_name, role, description, deploy_target, proposal_id,
           config_snapshot, status, deployed_at, created_at
    FROM spawned_agents;

DROP TABLE spawned_agents;
ALTER TABLE spawned_agents_new RENAME TO spawned_agents;
CREATE INDEX IF NOT EXISTS idx_spawned_status ON spawned_agents(status);
