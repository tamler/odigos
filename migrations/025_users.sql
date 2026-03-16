CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    must_change_password INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
