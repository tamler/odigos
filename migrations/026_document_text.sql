CREATE TABLE IF NOT EXISTS document_text (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    full_text TEXT NOT NULL
);
