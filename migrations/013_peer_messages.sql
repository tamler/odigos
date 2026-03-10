CREATE TABLE IF NOT EXISTS peer_messages (
    message_id TEXT PRIMARY KEY,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    peer_name TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'message',
    content TEXT NOT NULL,
    metadata_json TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'sent', 'delivered', 'failed', 'received', 'processed')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    delivered_at TEXT,
    conversation_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_peer_messages_peer ON peer_messages(peer_name);
CREATE INDEX IF NOT EXISTS idx_peer_messages_status ON peer_messages(status);
CREATE INDEX IF NOT EXISTS idx_peer_messages_direction ON peer_messages(direction);
