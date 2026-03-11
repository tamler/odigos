-- Add response tracking for task delegation
ALTER TABLE peer_messages ADD COLUMN response_to TEXT;
ALTER TABLE peer_messages ADD COLUMN task_status TEXT DEFAULT NULL;

-- Deploy targets for specialist spawning
CREATE TABLE IF NOT EXISTS deploy_targets (
    name TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT 'docker',
    ssh_user TEXT DEFAULT 'root',
    ssh_key_path TEXT,
    status TEXT DEFAULT 'available',
    last_used_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Track spawned specialists
CREATE TABLE IF NOT EXISTS spawned_agents (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    description TEXT,
    deploy_target TEXT NOT NULL,
    proposal_id TEXT,
    config_snapshot TEXT,
    status TEXT DEFAULT 'deploying',
    deployed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (deploy_target) REFERENCES deploy_targets(name)
);
CREATE INDEX IF NOT EXISTS idx_spawned_status ON spawned_agents(status);
