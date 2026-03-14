-- Agent template index and cache for agency-agents repo
CREATE TABLE IF NOT EXISTS agent_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    division TEXT NOT NULL,
    github_path TEXT NOT NULL UNIQUE,
    cached_content TEXT,
    cached_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_agent_templates_division ON agent_templates(division);
CREATE INDEX IF NOT EXISTS idx_agent_templates_name ON agent_templates(name);
