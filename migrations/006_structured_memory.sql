-- Drop old memory tables
DROP TABLE IF EXISTS memory_entries;
DROP TABLE IF EXISTS user_facts;

-- Structured memories
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    keywords_json TEXT DEFAULT '[]',
    tags_json TEXT DEFAULT '[]',
    context_description TEXT,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    conversation_id TEXT,
    confidence REAL DEFAULT 0.8,
    status TEXT DEFAULT 'active',
    superseded_by TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_memories_conversation ON memories(conversation_id);

-- Memory links
CREATE TABLE IF NOT EXISTS memory_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_note_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
    target_note_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL,
    strength REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_note_id, target_note_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_note_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(target_note_id);

-- Evolution queue
CREATE TABLE IF NOT EXISTS evolution_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    existing_memory_id TEXT REFERENCES memories(id),
    new_content TEXT NOT NULL,
    new_source_id TEXT,
    reason TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    processed_at TEXT
);
