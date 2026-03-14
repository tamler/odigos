-- Contact cards: scoped API keys for agent-to-agent relationships
CREATE TABLE IF NOT EXISTS contact_cards (
    id TEXT PRIMARY KEY,
    card_key TEXT NOT NULL UNIQUE,
    card_type TEXT NOT NULL CHECK (card_type IN ('connect', 'subscribe', 'invite')),
    issued_to TEXT,
    permissions TEXT NOT NULL DEFAULT 'mesh',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked', 'expired')),
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT,
    revoked_at TEXT,
    last_used_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_contact_cards_key ON contact_cards(card_key);
CREATE INDEX IF NOT EXISTS idx_contact_cards_status ON contact_cards(status);

-- Accepted cards: imported from other agents
CREATE TABLE IF NOT EXISTS accepted_cards (
    id TEXT PRIMARY KEY,
    card_type TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    host TEXT NOT NULL,
    ws_port INTEGER DEFAULT 8001,
    card_key TEXT NOT NULL,
    feed_url TEXT,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'muted', 'revoked')),
    accepted_at TEXT DEFAULT (datetime('now')),
    last_connected_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_accepted_cards_agent ON accepted_cards(agent_name);
CREATE INDEX IF NOT EXISTS idx_accepted_cards_status ON accepted_cards(status);

-- Feed entries: published by this agent
CREATE TABLE IF NOT EXISTS feed_entries (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
