-- User data tables -- agent-managed structured data (budgets, logs, trackers)
CREATE TABLE IF NOT EXISTS data_tables (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    columns TEXT NOT NULL,  -- JSON array of column names
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_rows (
    id TEXT PRIMARY KEY,
    table_id TEXT NOT NULL REFERENCES data_tables(id) ON DELETE CASCADE,
    values_json TEXT NOT NULL,  -- JSON array matching column order
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_data_rows_table ON data_rows(table_id, created_at);
