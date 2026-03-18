-- Notebook system: notebooks and entries tables.

CREATE TABLE IF NOT EXISTS notebooks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT DEFAULT 'general',
    collaboration TEXT DEFAULT 'read',
    share_with_agent INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notebook_entries (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    entry_type TEXT DEFAULT 'user',
    status TEXT DEFAULT 'active',
    mood TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notebook_entries_notebook ON notebook_entries(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notebooks_mode ON notebooks(mode);
