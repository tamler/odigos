ALTER TABLE conversations ADD COLUMN title TEXT;
ALTER TABLE conversations ADD COLUMN archived INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_conversations_archived ON conversations(archived);
