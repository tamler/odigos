CREATE TABLE IF NOT EXISTS webauthn_credentials (
    id TEXT PRIMARY KEY,
    credential_id BLOB NOT NULL UNIQUE,
    public_key BLOB NOT NULL,
    sign_count INTEGER DEFAULT 0,
    name TEXT DEFAULT 'Passkey',
    created_at TEXT DEFAULT (datetime('now'))
);
