-- Index on conversations.last_message_at for ORDER BY queries in context assembly
CREATE INDEX IF NOT EXISTS idx_conversations_last_message_at ON conversations (last_message_at);
