ALTER TABLE documents ADD COLUMN conversation_id TEXT;
ALTER TABLE documents ADD COLUMN file_path TEXT;
ALTER TABLE documents ADD COLUMN file_size INTEGER;
ALTER TABLE documents ADD COLUMN content_hash TEXT;
ALTER TABLE documents ADD COLUMN status TEXT NOT NULL DEFAULT 'ingested';

CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
