-- Memory entries: metadata for stored memories (replaces ChromaDB metadatas)
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    content_preview TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    when_to_use TEXT DEFAULT '',
    memory_type TEXT DEFAULT 'general',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memory_entries_source_type ON memory_entries(source_type);
CREATE INDEX IF NOT EXISTS idx_memory_entries_source_id ON memory_entries(source_id);
CREATE INDEX IF NOT EXISTS idx_memory_entries_memory_type ON memory_entries(memory_type);

-- Vector table: sqlite-vec HNSW index for 768-d embeddings
CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[768]
);

-- FTS5 full-text index over content_preview and when_to_use
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content_preview,
    when_to_use,
    content='memory_entries',
    content_rowid='rowid'
);

-- Triggers to keep FTS5 in sync with memory_entries
CREATE TRIGGER IF NOT EXISTS memory_entries_ai AFTER INSERT ON memory_entries BEGIN
    INSERT INTO memory_fts(rowid, content_preview, when_to_use)
    VALUES (new.rowid, new.content_preview, new.when_to_use);
END;

CREATE TRIGGER IF NOT EXISTS memory_entries_ad AFTER DELETE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content_preview, when_to_use)
    VALUES ('delete', old.rowid, old.content_preview, old.when_to_use);
END;

CREATE TRIGGER IF NOT EXISTS memory_entries_au AFTER UPDATE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content_preview, when_to_use)
    VALUES ('delete', old.rowid, old.content_preview, old.when_to_use);
    INSERT INTO memory_fts(rowid, content_preview, when_to_use)
    VALUES (new.rowid, new.content_preview, new.when_to_use);
END;
