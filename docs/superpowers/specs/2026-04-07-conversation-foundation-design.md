# Conversation Foundation Design

**Date:** 2026-04-07
**Status:** Approved
**Goal:** One consistent, reliable system for all conversation interactions — single message bus, consistent schema, channel-agnostic identity, reliable delivery.

## Context

The conversation system has deep structural issues: messages live in three places (WebSocket session, Zustand store, database) with no defined contract. Column names are inconsistent across tables. Conversation IDs carry channel prefixes that break when stripped. Background task results don't reliably appear in conversations. The system needs a clean foundation before activity indicators, focus areas, or proactive agent behavior can be built.

## Design

### 1. Schema Conventions

Fresh database from schema.sql. Every table uses:
- `id` TEXT PRIMARY KEY (UUID, no prefixes)
- `created_at` TEXT DEFAULT (datetime('now'))
- `updated_at` TEXT where rows mutate
- `{event}_at` for domain timing: `due_at`, `completed_at`, `expires_at`, `delivered_at`, `seen_at`
- Foreign keys: `{table_singular}_id` (conversation_id, message_id)
- All timestamps ISO 8601 TEXT

### 2. Core Tables

```sql
CREATE TABLE conversations (
    id              TEXT PRIMARY KEY,
    title           TEXT,
    channel         TEXT NOT NULL,
    status          TEXT DEFAULT 'active',
    message_count   INTEGER DEFAULT 0,
    last_message_at TEXT,
    category        TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role            TEXT NOT NULL,
    content         TEXT,
    channel         TEXT,
    message_type    TEXT DEFAULT 'chat',
    model_used      TEXT,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cost_usd        REAL,
    metadata_json   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_messages_created ON messages(created_at);

CREATE TABLE message_deliveries (
    id              TEXT PRIMARY KEY,
    message_id      TEXT NOT NULL REFERENCES messages(id),
    channel         TEXT NOT NULL,
    delivered_at    TEXT,
    seen_at         TEXT
);

CREATE INDEX idx_deliveries_message ON message_deliveries(message_id);

CREATE TABLE message_artifacts (
    message_id      TEXT NOT NULL REFERENCES messages(id),
    artifact_id     TEXT NOT NULL REFERENCES artifacts(id),
    PRIMARY KEY (message_id, artifact_id)
);

CREATE TABLE channel_mappings (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    channel         TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(channel, external_id)
);

CREATE INDEX idx_channel_mappings_external ON channel_mappings(channel, external_id);
```

**conversations.id:** Plain UUID. No `web:` prefix. Channel is a field, not part of the identity.

**messages.channel:** Which channel the message came from (web, telegram, api, heartbeat, callback). Independent of the conversation's originating channel.

**messages.message_type:** `chat` (normal), `tool_result`, `notification`, `artifact`, `status`. The UI renders each type differently. Channel adapters filter by type (Telegram skips tool_result and status).

**messages.metadata_json:** Flexible storage for tool_name, artifact_ids, error details, display hints. Non-queryable data.

**Queryable fields stay as columns:** model_used, tokens_in, tokens_out, cost_usd. These are needed for analytics and budget tracking.

**message_deliveries:** One row per message per channel. Tracks when pushed and when seen. Created by the bus on delivery. `seen_at` populated by channel adapters when the user views the message.

All other tables in schema.sql get the same naming audit: `timestamp` → `created_at`, consistent foreign key names, same conventions.

### 3. MessageBus

A single class on the Container. One interface for publishing messages, used by everything.

```python
class MessageBus:
    def __init__(self, db: Database, channel_registry: ChannelRegistry):
        self.db = db
        self.channel_registry = channel_registry

    async def create_conversation(self, channel: str, title: str = None) -> str:
        """Create a new conversation. Returns the conversation ID (plain UUID)."""
        conv_id = uuid.uuid4().hex
        await self.db.execute(
            "INSERT INTO conversations (id, channel, title) VALUES (?, ?, ?)",
            (conv_id, channel, title),
        )
        return conv_id

    async def publish(
        self,
        conversation_id: str,
        role: str,
        content: str,
        channel: str = "system",
        message_type: str = "chat",
        model_used: str = None,
        tokens_in: int = None,
        tokens_out: int = None,
        cost_usd: float = None,
        metadata: dict = None,
        idempotency_key: str = None,
    ) -> str:
        """Publish a message. Writes to DB + pushes to all reachable channels.
        Returns the message ID. If idempotency_key is provided and a message
        with that key already exists, returns the existing message ID (no duplicate)."""

        # 0. Idempotency check (callbacks may fire twice)
        if idempotency_key:
            existing = await self.db.fetch_one(
                "SELECT id FROM messages WHERE json_extract(metadata_json, '$.idempotency_key') = ?",
                (idempotency_key,),
            )
            if existing:
                return existing["id"]
            metadata = {**(metadata or {}), "idempotency_key": idempotency_key}

        # 1. Write to DB (source of truth)
        msg_id = uuid.uuid4().hex
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, channel, "
            "message_type, model_used, tokens_in, tokens_out, cost_usd, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (msg_id, conversation_id, role, content, channel, message_type,
             model_used, tokens_in, tokens_out, cost_usd,
             json.dumps(metadata) if metadata else None),
        )

        # 2. Update conversation metadata
        await self.db.execute(
            "UPDATE conversations SET message_count = message_count + 1, "
            "last_message_at = datetime('now'), updated_at = datetime('now') "
            "WHERE id = ?",
            (conversation_id,),
        )

        # 3. Push to all reachable channels for this user
        msg_data = {
            "type": "message",
            "id": msg_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "channel": channel,
            "message_type": message_type,
            "metadata": metadata,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        for ch in self.channel_registry.all():
            try:
                if ch.is_reachable():
                    await ch.deliver(msg_data)
                    await self.db.execute(
                        "INSERT INTO message_deliveries (id, message_id, channel, delivered_at) "
                        "VALUES (?, ?, ?, datetime('now'))",
                        (uuid.uuid4().hex, msg_id, ch.channel_name),
                    )
            except Exception:
                pass  # Channel not connected, delivery skipped

        return msg_id
```

**Streaming exception:** Streaming chunks are ephemeral — pushed directly over WebSocket for real-time display, not through the bus. The bus handles the FINAL message after streaming completes. This matches Vercel AI SDK's approach.

### 4. Who Calls the Bus

| Caller | What | Bus Call |
|--------|------|---------|
| agent.py | User message | `bus.publish(role='user', channel='web')` |
| reflector.py | Assistant response | `bus.publish(role='assistant', model_used=..., tokens_in=...)` |
| callbacks.py | Task completion | `bus.publish(role='system', message_type='artifact', metadata={'artifact_ids': [...]})` |
| background.py | Heartbeat result | `bus.publish(role='system', message_type='notification')` |
| ws.py | New conversation | `bus.create_conversation(channel='web')` |
| telegram.py | New conversation | `bus.create_conversation(channel='telegram')` |

Everything goes through `bus.publish()`. No more direct `INSERT INTO messages` anywhere except the bus itself.

### 5. Channel Adapters

```python
class ChannelAdapter:
    channel_name: str

    async def deliver(self, msg_data: dict) -> None:
        """Push a message to connected clients on this channel."""
        raise NotImplementedError

    def is_reachable(self) -> bool:
        """Is at least one client connected on this channel?"""
        raise NotImplementedError
```

**WebChannel:**
- Maintains WebSocket connections
- `deliver()` sends full JSON — frontend renders by message_type
- Handles streaming directly (not through bus)

**TelegramChannel:**
- Maintains bot connection
- `deliver()` sends text rendering via Telegram API
- Strips metadata, ignores tool_result and status types
- Simplifies artifacts to text + download link

**Delivery is per-user, not per-conversation.** The bus pushes to all channels where the user is reachable. A song completing in a web conversation sends a Telegram notification if the user has Telegram connected.

### 6. Conversation Identity

- `id` is a plain UUID — no channel prefix
- `channel` field records where the conversation started
- Each message has its own `channel` field for where it came from
- Same conversation accessible from any channel (future: cross-channel continuation)
- URLs: `/?c=abc123def456` (no colon, no encoding issues)
- Frontend stores and sends the full UUID, no stripping

### 7. Reliable Delivery Contract

1. **DB is source of truth.** In DB = happened. Not in DB = didn't happen.
2. **WebSocket push is best-effort.** Connected = real-time. Not connected = get it on next DB load.
3. **Frontend loads from DB on conversation open.** API reads DB. Not memory, not cache.
4. **Frontend subscribes to WebSocket for live updates.** New messages added to UI via WebSocket.
5. **Streaming is ephemeral.** Chunks flow over WebSocket. Final message through the bus.
6. **Background results go through the bus.** Callbacks, heartbeat, proactive messages — all use publish().
7. **On reconnect, re-fetch from DB.** Frontend sends `last_seen_at` timestamp on reconnect. API returns only messages newer than that timestamp. No full re-fetch, no sequence gaps.

### 8. Frontend Changes

**chatStore.ts:**
- Messages loaded from API on conversation open
- WebSocket `message` events append to messages array
- No separate streaming state for storage (streaming is display-only)
- `activeConversationId` is a plain UUID

**useWebSocketHandler.ts:**
- Handle unified `message` event type from bus
- Remove old type-specific message storage (chat_response adding messages)
- Keep `chat_chunk` for streaming display
- On reconnect: send `last_seen_at` timestamp, fetch only missed messages via `GET /api/conversations/{id}/messages?after={timestamp}`
- Track `last_seen_at` from the most recent message's `created_at`

**ChatPanel.tsx:**
- Load messages via `GET /api/conversations/{id}/messages` on conversation open
- Supports `?after={timestamp}` for catch-up on reconnect
- Subscribe to WebSocket for live updates
- Plain UUID in all conversation references

**AppSidebar.tsx:**
- Read conversations from store (already does)
- conversation_started event from bus uses plain UUID
- `GET /api/conversations` supports `?category=` filter (prep for Spec C focus areas)
- `conversations.category` field exists but unused until Spec C

### 9. What This Replaces

| Old Pattern | New Pattern |
|-------------|-------------|
| Direct `INSERT INTO messages` in 4+ files | `bus.publish()` everywhere |
| `web:xxx` conversation IDs | Plain UUIDs |
| `messages.timestamp` | `messages.created_at` |
| Messages in 3 places (WS session, store, DB) | DB is truth, store is display, WS is notification |
| Manual `websocket.send_json()` per message type | Bus pushes to channel adapters |
| Callbacks writing to DB but not pushing to UI | Bus writes AND pushes atomically |
| `_resolve_conversation_id` prefix fallback | Simple UUID lookup |
| `notifier.notify()` separate from message storage | Bus handles both |

## File Changes

| File | Change |
|------|--------|
| `schema.sql` | Rewrite with consistent naming, new tables |
| `odigos/core/message_bus.py` | **New** — MessageBus class |
| `odigos/channels/base.py` | Add ChannelAdapter base class |
| `odigos/channels/web.py` | Implement ChannelAdapter.deliver() |
| `odigos/channels/telegram.py` | Implement ChannelAdapter.deliver() |
| `odigos/container.py` | Add message_bus field |
| `odigos/bootstrap.py` | Create MessageBus on startup |
| `odigos/core/agent.py` | Use bus.publish() for user messages |
| `odigos/core/reflector.py` | Use bus.publish() for assistant messages |
| `odigos/api/ws.py` | Use bus.create_conversation(), streaming stays direct |
| `odigos/api/callbacks.py` | Use bus.publish() for completions |
| `odigos/core/heartbeat/background.py` | Use bus.publish() for results |
| `dashboard/src/stores/chatStore.ts` | Plain UUID, no prefix handling |
| `dashboard/src/layouts/hooks/useWebSocketHandler.ts` | Handle unified message event |
| `dashboard/src/layouts/hooks/useConversationActions.ts` | Plain UUID in URLs |
| `dashboard/src/components/ChatPanel.tsx` | Load from API, subscribe to WS |

## What Doesn't Change

- Tool registry, find_tools, skill system
- Query planner and prompt assembly
- XSkill experience store
- Executor tool loop
- Frontend component decomposition
- Streaming chunk delivery (stays direct WebSocket)

## Database

Drop and recreate from schema.sql. No migration. Dev environment, clean slate.

## Future (Spec B & C, not built now)

- **Spec B: Activity & notifications** — sidebar badges, cross-conversation alerts, built on message_deliveries
- **Spec C: Focus areas** — conversation categories, general inbox, proactive agent publishing
- **Cross-channel continuation** — "continue conversation" loads context from any prior channel
- **Delivery tracking** — seen_at populated by channel adapters
