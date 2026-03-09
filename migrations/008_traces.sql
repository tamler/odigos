CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    timestamp TEXT DEFAULT (datetime('now')),
    conversation_id TEXT REFERENCES conversations(id),
    event_type TEXT NOT NULL,
    data_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_traces_conversation ON traces(conversation_id);
CREATE INDEX IF NOT EXISTS idx_traces_event_type ON traces(event_type);
CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp);

DROP TABLE IF EXISTS action_log;
