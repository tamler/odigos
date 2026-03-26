-- Key-value store for agent runtime metadata (briefing dates, counters, etc.)
CREATE TABLE IF NOT EXISTS agent_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
