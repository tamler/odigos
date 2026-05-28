-- Track per-call cost for paid tools (Whisper STT, Kie.ai image, Kie.ai music, etc.)
-- so they aggregate into the same daily/monthly budget cap as LLM token cost.
-- See docs/superpowers/specs/2026-04-16-unified-cost-tracking-note.md.
CREATE TABLE IF NOT EXISTS tool_costs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    source TEXT NOT NULL,       -- 'whisper', 'kie_image', 'kie_music', etc. (one per provider)
    tool_name TEXT,
    cost_usd REAL NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tool_costs_created ON tool_costs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_costs_source ON tool_costs(source);
