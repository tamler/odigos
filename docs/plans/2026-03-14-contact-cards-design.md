# Agent Contact Cards Design

**Date:** 2026-03-14
**Status:** Approved

## Goal

Replace the current shared-API-key peer authentication with a contact card system that provides per-relationship scoped keys, granular revocation, and a portable format for establishing agent-to-agent relationships. Add a lightweight RSS feed publisher so agents can share data with subscribers without granting mesh access.

## Context

The current mesh networking has security gaps:
- All peers share a single global `api_key` -- revoking one peer means changing the key for everyone
- `PeerConfig.api_key` exists but is never used
- No way to grant read-only access (subscribe without mesh join)
- No portable way to exchange connection credentials between agents
- No feed publishing capability (only consumption via `read_feed` tool)
- Mesh defaults to disabled (`mesh.enabled: false`) as of this design

## Card Types

| Type | Grants | Use Case |
|------|--------|----------|
| `connect` | Full bidirectional mesh messaging | "This is my systems agent, let's talk" |
| `subscribe` | Read-only access to issuer's RSS feed | "I want this agent's daily digests" |
| `invite` | Pre-authorized mesh join for spawned agents | "Here's your card, join my mesh when you boot" |

## Card Data Model

```yaml
version: 1
type: connect                     # connect | subscribe | invite
agent_name: "SysWatch"
host: "100.64.0.5"               # NetBird IP or hostname
ws_port: 8001
card_key: "card-sk-a1b2c3..."    # Scoped API key for this relationship
capabilities: ["monitoring", "alerting"]
feed_url: null                    # Only populated on subscribe cards
issued_at: "2026-03-14T12:00:00Z"
expires_at: null                  # Optional expiry
issuer: "SysWatch"
fingerprint: "sha256:abc..."     # SHA-256(card_key + agent_name + issued_at)
```

**Compact format:** `odigos-card:<base64-encoded-yaml>` -- a single string for paste-into-chat.

**Fingerprint:** SHA-256 of `card_key + agent_name + issued_at`. Tamper detection, not cryptographic trust. If card fields are edited, import is rejected.

## Database Schema

### `contact_cards` (cards this agent has issued)

```sql
CREATE TABLE contact_cards (
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
```

### `accepted_cards` (cards this agent has imported)

```sql
CREATE TABLE accepted_cards (
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
```

### `feed_entries` (published feed content)

```sql
CREATE TABLE feed_entries (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

## Auth Integration

### Current flow
```
Request -> extract Bearer token -> compare to settings.api_key -> allow/deny
```

### New flow
```
Request -> extract Bearer token ->
  1. Compare to settings.api_key -> full dashboard/user access
  2. Else: look up in contact_cards -> if active + not expired: scoped peer access
  3. Else: 401/403
```

### Endpoint mapping

- **Dashboard routes**: `require_api_key` (global key only, unchanged)
- **Agent routes** (`/ws/agent`, `/api/agent/peer/announce`): `require_card_or_api_key`
- **Feed endpoint** (`/feed.xml`): card key bearer token, or public if configured

### Permission scoping

| Card type | WS connect | Announce | Send messages | Read feed |
|-----------|-----------|----------|---------------|-----------|
| `connect` | Yes | Yes | Yes | Yes |
| `subscribe` | No | No | No | Yes |
| `invite` | Yes (once) | Yes (once) | After first announce | Yes |

Invite cards transition to connect behavior after the spawned agent's first successful announce.

## Card Lifecycle

### Generating (issuer side)
1. Agent or user triggers via `generate_card` tool or dashboard button
2. System generates `card-sk-` + 32 random hex chars
3. Row inserted into `contact_cards` with status `active`
4. YAML assembled with computed fingerprint
5. Returns YAML file + compact `odigos-card:base64...` string

### Importing (recipient side)
1. User drops `.card.yaml` via dashboard upload, pastes compact string into chat, or agent receives programmatically
2. System validates: fingerprint matches, not expired, type recognized
3. Row inserted into `accepted_cards`
4. Based on type:
   - `connect`: peer added to `_peers`, mesh established on next heartbeat
   - `subscribe`: feed URL registered, polling starts on heartbeat
   - `invite`: stored for spawned agent boot sequence

### Revoking (either side)
1. **Issuer revokes**: `contact_cards.status = 'revoked'`. Card key rejected on next auth attempt. Best-effort revocation notice sent to peer.
2. **Recipient revokes**: `accepted_cards.status = 'revoked'`. Peer removed from `_peers`. Feed polling stopped. Best-effort notice sent back.

### Muting
- `accepted_cards.status = 'muted'`
- `connect` cards: inbound messages silently dropped (recorded with status `muted` in `peer_messages`)
- `subscribe` cards: feed polling paused
- Agent can still send to muted peers if it chooses
- Unmute from dashboard or via conversation

### Expiry
- If `expires_at` is set and passed, card treated as revoked during auth checks
- No cleanup job needed -- checked on use

## Feed Publisher

### Endpoint
- `GET /feed.xml` -- RSS 2.0 XML, latest N entries (default 50)
- Auth: bearer token with valid subscribe or connect card key. If `feed.public: true`, no auth required.

### Tool
- `publish_to_feed`: parameters `title` (required), `content` (required), `category` (optional)
- Agent calls this whenever it wants to share something
- Returns entry ID and feed URL

### Config
```yaml
feed:
  enabled: false
  public: false
  max_entries: 200
```

## Agent Tools

| Tool | Purpose | Parameters |
|------|---------|-----------|
| `generate_card` | Create a card to share | `type` (connect/subscribe/invite), `expires_in_days` (optional) |
| `import_card` | Import a received card | `card_data` (YAML string or compact token) |
| `publish_to_feed` | Add entry to RSS feed | `title`, `content`, `category` (optional) |

## Dashboard

### Connections page (new)
- Two tabs: "Issued Cards" and "Accepted Cards"
- Issued: card type, issued_to, status, created_at, last_used_at, Revoke button
- Accepted: agent_name, card type, host, status, last_connected_at, Revoke/Mute buttons
- "Generate Card" button with type selector and optional expiry

### Feed page (new)
- List of published entries: title, category, date, Delete button
- Feed URL displayed for copying

### Settings additions
- Feed section: `enabled` toggle, `public` toggle, `max_entries` input

## Files

| Component | File |
|-----------|------|
| Card core logic | `odigos/core/cards.py` |
| Card tools | `odigos/tools/card_tools.py` |
| Feed publish tool | `odigos/tools/feed_publish.py` |
| Feed API endpoint | `odigos/api/feed.py` |
| Auth dependency | `odigos/api/deps.py` (modify `require_card_or_api_key`) |
| Config | `odigos/config.py` (add `FeedConfig`, `MeshConfig` already exists) |
| Migration | `migrations/022_contact_cards.sql` |
| Dashboard Connections | `dashboard/src/pages/Connections.tsx` |
| Dashboard Feed | `dashboard/src/pages/Feed.tsx` |
| Dashboard Settings | `dashboard/src/pages/settings/GeneralSettings.tsx` (add feed section) |

## Security Considerations

- Card keys are per-relationship. Revoking one doesn't affect others.
- Subscribe cards grant zero mesh access -- feed only.
- Invite cards are single-use for initial mesh join.
- All inbound peer messages continue to pass through prompt injection filter.
- Mesh defaults to disabled. Cards don't work without `mesh.enabled: true` (except subscribe, which only needs `feed.enabled: true`).
- Fingerprint prevents card tampering in transit.
- Global `api_key` remains for dashboard auth -- card keys cannot access the dashboard.
