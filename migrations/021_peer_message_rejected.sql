-- Add 'rejected' status for messages blocked by prompt injection filter.
-- SQLite doesn't support ALTER CHECK, so we recreate the constraint-free
-- approach: the CHECK is on the original CREATE TABLE which already exists.
-- We just need to ensure the column accepts the new value.
-- SQLite CHECK constraints are validated on INSERT, so we drop and recreate.

CREATE TABLE IF NOT EXISTS peer_messages_new (
    message_id TEXT PRIMARY KEY,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    peer_name TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'message',
    content TEXT NOT NULL,
    metadata_json TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'sent', 'delivered', 'failed', 'received', 'processed', 'expired', 'rejected')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    delivered_at TEXT,
    conversation_id TEXT,
    response_to TEXT,
    task_status TEXT
);

INSERT OR IGNORE INTO peer_messages_new
    SELECT message_id, direction, peer_name, message_type, content, metadata_json,
           status, created_at, delivered_at, conversation_id, response_to, task_status
    FROM peer_messages;

DROP TABLE IF EXISTS peer_messages;
ALTER TABLE peer_messages_new RENAME TO peer_messages;

CREATE INDEX IF NOT EXISTS idx_peer_messages_peer ON peer_messages(peer_name);
CREATE INDEX IF NOT EXISTS idx_peer_messages_status ON peer_messages(status);
CREATE INDEX IF NOT EXISTS idx_peer_messages_direction ON peer_messages(direction);
