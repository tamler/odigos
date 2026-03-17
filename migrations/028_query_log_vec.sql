CREATE VIRTUAL TABLE IF NOT EXISTS query_log_vec USING vec0(
    query_log_rowid INTEGER PRIMARY KEY,
    embedding FLOAT[768]
);
