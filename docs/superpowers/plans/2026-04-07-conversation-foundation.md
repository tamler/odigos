# Conversation Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragmented conversation/messaging system with a single MessageBus, consistent schema, channel-agnostic identity (plain UUIDs), and reliable delivery contract.

**Architecture:** A `MessageBus` class on the Container is the only way to write messages. It writes to DB (source of truth) and pushes to all registered channel adapters. Conversation IDs are plain UUIDs — no `web:` prefix. The existing `Channel` ABC gains `deliver()` and `is_reachable()` methods. Streaming chunks stay direct WebSocket (not through bus) but carry a pre-allocated `message_id` for correlation with the final bus message.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, SQLite json_extract, React 19, TypeScript, Zustand

---

## File Structure

| File | Responsibility |
|------|---------------|
| `schema.sql` | Rewrite conversations/messages tables, add message_deliveries/message_artifacts/channel_mappings, rename `timestamp`→`created_at` and `started_at`→`created_at` everywhere |
| `odigos/core/message_bus.py` | **New** — MessageBus class: `create_conversation()`, `publish()` |
| `odigos/channels/base.py` | Add `deliver()` and `is_reachable()` to Channel ABC, keep existing methods |
| `odigos/channels/web.py` | Implement `deliver()` (broadcast to all connections) and `is_reachable()`, remove `web:` prefix filtering |
| `odigos/container.py` | Add `message_bus: MessageBus` field |
| `odigos/bootstrap.py` | Create MessageBus after channel_registry, before heartbeat |
| `odigos/core/agent.py` | Replace direct INSERT with `bus.publish()`, remove `_get_or_create_conversation` prefix logic |
| `odigos/core/reflector.py` | Replace direct INSERT with `bus.publish()` |
| `odigos/api/ws.py` | Use `bus.create_conversation()` for plain UUIDs, pre-allocate `message_id` for streaming, `chat_chunk` carries `message_id` |
| `odigos/api/callbacks.py` | Replace direct INSERT + notifier + broadcast with single `bus.publish()` |
| `odigos/core/heartbeat/background.py` | Replace direct INSERT + notifier + broadcast with single `bus.publish()` |
| `odigos/api/conversations.py` | Update column references: `timestamp`→`created_at`, `started_at`→`created_at`, add `?after=` param, add `?category=` filter |
| `odigos/core/context.py` | Update all `ORDER BY timestamp` → `ORDER BY created_at` |
| `odigos/core/budget.py` | Update `timestamp` references → `created_at` |
| `odigos/memory/summarizer.py` | Update `ORDER BY timestamp` → `ORDER BY created_at` |
| `odigos/core/evaluator.py` | Update all `timestamp` references → `created_at` |
| `odigos/core/trajectory.py` | Update `timestamp` references → `created_at` |
| `odigos/core/data_export.py` | Update `timestamp`→`created_at`, `started_at`→`created_at` |
| `odigos/core/heartbeat/profiling.py` | Update `ORDER BY timestamp` → `ORDER BY created_at` |
| `odigos/api/state.py` | Update `timestamp`→`created_at`, `started_at`→`created_at` |
| `dashboard/src/stores/chatStore.ts` | Add `streamingMessageId` state for chunk correlation |
| `dashboard/src/layouts/hooks/useWebSocketHandler.ts` | Handle `message` event from bus, `chat_chunk` with `message_id`, drop late chunks, catch-up on reconnect |
| `dashboard/src/layouts/hooks/useConversationActions.ts` | `started_at`→`created_at` in displayTitle |
| `dashboard/src/components/ChatPanel.tsx` | Update timestamp field references, add `?after=` support |
| `dashboard/src/stores/conversationStore.ts` | `started_at`→`created_at` in Conversation type |
| `dashboard/src/components/QuickSwitcher.tsx` | `started_at`→`created_at` |
| `dashboard/src/pages/EvolutionPage.tsx` | `started_at`→`created_at` in Trial type |
| `dashboard/src/pages/settings/EvolutionTab.tsx` | `started_at`→`created_at` |
| `tests/conftest.py` | Add conversations + messages tables to `fake_db`, update column names |
| `tests/test_message_bus.py` | **New** — Tests for MessageBus |
| `tests/test_api_conversations.py` | Update column names in test SQL |
| `tests/test_summarizer.py` | Update `started_at`→`created_at` in test SQL |
| `tests/test_api_metrics.py` | Update `started_at`→`created_at` in test SQL |
| `tests/test_state_api.py` | Update `started_at`→`created_at` in test SQL |

---

### Task 1: Schema Rewrite

Rewrite the conversations and messages sections of `schema.sql` to match the spec. Add new tables. Rename columns across all sections.

**Files:**
- Modify: `schema.sql:20-44`

- [ ] **Step 1: Rewrite conversations and messages tables in schema.sql**

Replace the conversations and messages section (lines 17-44) with:

```sql
-- ════════════════════════════════════════════════════════════════════
-- CONVERSATIONS & MESSAGES
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS conversations (
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

CREATE TABLE IF NOT EXISTS messages (
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

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);

CREATE TABLE IF NOT EXISTS message_deliveries (
    id              TEXT PRIMARY KEY,
    message_id      TEXT NOT NULL REFERENCES messages(id),
    channel         TEXT NOT NULL,
    delivered_at    TEXT,
    seen_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_deliveries_message ON message_deliveries(message_id);

CREATE TABLE IF NOT EXISTS message_artifacts (
    message_id      TEXT NOT NULL REFERENCES messages(id),
    artifact_id     TEXT NOT NULL REFERENCES artifacts(id),
    PRIMARY KEY (message_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS channel_mappings (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    channel         TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(channel, external_id)
);

CREATE INDEX IF NOT EXISTS idx_channel_mappings_external ON channel_mappings(channel, external_id);
CREATE INDEX IF NOT EXISTS idx_messages_idempotency ON messages(json_extract(metadata_json, '$.idempotency_key'));
```

Remove the old `idx_messages_timestamp` and `idx_conversations_archived` indexes.

- [ ] **Step 2: Audit remaining tables in schema.sql for timestamp→created_at**

Search schema.sql for any remaining `timestamp` columns (not in function calls like `datetime('now')`) and rename to `created_at`. The `heartbeat_sessions` table has `started_at` which should stay (it's domain timing for session start, not creation). The `traces` table has `started_at` and `ended_at` which should stay (domain timing).

Specifically, no other tables in schema.sql use a bare `timestamp` column — the conversations/messages tables were the only ones. Confirm by searching the file.

- [ ] **Step 3: Verify schema.sql is valid SQL**

Run: `sqlite3 :memory: < schema.sql`
Expected: No errors (or only warnings about vec0 extension not being available)

- [ ] **Step 4: Commit**

```bash
git add schema.sql
git commit -m "schema: rewrite conversations/messages tables, add deliveries/artifacts/channel_mappings"
```

---

### Task 2: MessageBus Core

Create the MessageBus class with `create_conversation()` and `publish()`.

**Files:**
- Create: `odigos/core/message_bus.py`
- Create: `tests/test_message_bus.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_message_bus.py`:

```python
"""Tests for MessageBus — the single interface for all message publishing."""
from __future__ import annotations

import json
import uuid

import aiosqlite
import pytest
import pytest_asyncio

from tests.conftest import FakeDB


class FakeChannel:
    """Minimal channel adapter for testing."""

    def __init__(self, name: str, reachable: bool = True):
        self.channel_name = name
        self._reachable = reachable
        self.delivered: list[dict] = []

    def is_reachable(self) -> bool:
        return self._reachable

    async def deliver(self, msg_data: dict) -> None:
        self.delivered.append(msg_data)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class FakeRegistry:
    """Minimal channel registry for testing."""

    def __init__(self, channels: list[FakeChannel] | None = None):
        self._channels = channels or []

    def all(self) -> list[FakeChannel]:
        return self._channels


@pytest_asyncio.fixture
async def bus_db():
    """Create an in-memory DB with the conversations and messages tables."""
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        db = FakeDB(conn)
        await conn.execute("""
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT,
                channel TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                message_count INTEGER DEFAULT 0,
                last_message_at TEXT,
                category TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("""
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                role TEXT NOT NULL,
                content TEXT,
                channel TEXT,
                message_type TEXT DEFAULT 'chat',
                model_used TEXT,
                tokens_in INTEGER,
                tokens_out INTEGER,
                cost_usd REAL,
                metadata_json TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("""
            CREATE TABLE message_deliveries (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL REFERENCES messages(id),
                channel TEXT NOT NULL,
                delivered_at TEXT,
                seen_at TEXT
            )
        """)
        await conn.commit()
        yield db


@pytest.mark.asyncio
async def test_create_conversation(bus_db):
    from odigos.core.message_bus import MessageBus

    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry())
    conv_id = await bus.create_conversation(channel="web")

    assert len(conv_id) == 32  # uuid4().hex
    row = await bus_db.fetch_one("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    assert row is not None
    assert row["channel"] == "web"
    assert row["status"] == "active"


@pytest.mark.asyncio
async def test_create_conversation_with_title(bus_db):
    from odigos.core.message_bus import MessageBus

    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry())
    conv_id = await bus.create_conversation(channel="telegram", title="Test Chat")

    row = await bus_db.fetch_one("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    assert row["title"] == "Test Chat"
    assert row["channel"] == "telegram"


@pytest.mark.asyncio
async def test_publish_stores_message(bus_db):
    from odigos.core.message_bus import MessageBus

    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry())
    conv_id = await bus.create_conversation(channel="web")

    msg_id = await bus.publish(
        conversation_id=conv_id,
        role="user",
        content="Hello world",
        channel="web",
    )

    assert len(msg_id) == 32
    row = await bus_db.fetch_one("SELECT * FROM messages WHERE id = ?", (msg_id,))
    assert row["conversation_id"] == conv_id
    assert row["role"] == "user"
    assert row["content"] == "Hello world"
    assert row["channel"] == "web"
    assert row["message_type"] == "chat"


@pytest.mark.asyncio
async def test_publish_updates_conversation_metadata(bus_db):
    from odigos.core.message_bus import MessageBus

    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry())
    conv_id = await bus.create_conversation(channel="web")

    await bus.publish(conv_id, role="user", content="msg1", channel="web")
    await bus.publish(conv_id, role="assistant", content="msg2", channel="web")

    row = await bus_db.fetch_one("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    assert row["message_count"] == 2
    assert row["last_message_at"] is not None


@pytest.mark.asyncio
async def test_publish_with_model_metadata(bus_db):
    from odigos.core.message_bus import MessageBus

    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry())
    conv_id = await bus.create_conversation(channel="web")

    msg_id = await bus.publish(
        conv_id, role="assistant", content="response",
        channel="web", model_used="claude-3", tokens_in=100,
        tokens_out=50, cost_usd=0.001,
    )

    row = await bus_db.fetch_one("SELECT * FROM messages WHERE id = ?", (msg_id,))
    assert row["model_used"] == "claude-3"
    assert row["tokens_in"] == 100
    assert row["tokens_out"] == 50
    assert row["cost_usd"] == 0.001


@pytest.mark.asyncio
async def test_publish_delivers_to_reachable_channels(bus_db):
    from odigos.core.message_bus import MessageBus

    web = FakeChannel("web", reachable=True)
    telegram = FakeChannel("telegram", reachable=False)
    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry([web, telegram]))
    conv_id = await bus.create_conversation(channel="web")

    await bus.publish(conv_id, role="user", content="test", channel="web")

    assert len(web.delivered) == 1
    assert web.delivered[0]["content"] == "test"
    assert len(telegram.delivered) == 0


@pytest.mark.asyncio
async def test_publish_creates_delivery_rows_for_all_channels(bus_db):
    from odigos.core.message_bus import MessageBus

    web = FakeChannel("web", reachable=True)
    telegram = FakeChannel("telegram", reachable=False)
    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry([web, telegram]))
    conv_id = await bus.create_conversation(channel="web")

    msg_id = await bus.publish(conv_id, role="user", content="test", channel="web")

    deliveries = await bus_db.fetch_all(
        "SELECT * FROM message_deliveries WHERE message_id = ? ORDER BY channel",
        (msg_id,),
    )
    assert len(deliveries) == 2
    # Telegram: delivery row exists but delivered_at is NULL
    tg_row = [d for d in deliveries if d["channel"] == "telegram"][0]
    assert tg_row["delivered_at"] is None
    # Web: delivery row with delivered_at set
    web_row = [d for d in deliveries if d["channel"] == "web"][0]
    assert web_row["delivered_at"] is not None


@pytest.mark.asyncio
async def test_publish_with_pre_allocated_message_id(bus_db):
    from odigos.core.message_bus import MessageBus

    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry())
    conv_id = await bus.create_conversation(channel="web")

    pre_id = uuid.uuid4().hex
    msg_id = await bus.publish(
        conv_id, role="assistant", content="streamed",
        channel="web", message_id=pre_id,
    )

    assert msg_id == pre_id
    row = await bus_db.fetch_one("SELECT * FROM messages WHERE id = ?", (pre_id,))
    assert row is not None


@pytest.mark.asyncio
async def test_publish_idempotency_key_prevents_duplicates(bus_db):
    from odigos.core.message_bus import MessageBus

    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry())
    conv_id = await bus.create_conversation(channel="web")

    msg_id1 = await bus.publish(
        conv_id, role="system", content="task done",
        channel="callback", idempotency_key="task-123",
    )
    msg_id2 = await bus.publish(
        conv_id, role="system", content="task done duplicate",
        channel="callback", idempotency_key="task-123",
    )

    assert msg_id1 == msg_id2
    count = await bus_db.fetch_one("SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ?", (conv_id,))
    assert count["cnt"] == 1


@pytest.mark.asyncio
async def test_publish_metadata_stored_as_json(bus_db):
    from odigos.core.message_bus import MessageBus

    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry())
    conv_id = await bus.create_conversation(channel="web")

    msg_id = await bus.publish(
        conv_id, role="system", content="artifact ready",
        channel="callback", message_type="artifact",
        metadata={"artifact_ids": ["a1", "a2"]},
    )

    row = await bus_db.fetch_one("SELECT * FROM messages WHERE id = ?", (msg_id,))
    assert row["message_type"] == "artifact"
    meta = json.loads(row["metadata_json"])
    assert meta["artifact_ids"] == ["a1", "a2"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_message_bus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odigos.core.message_bus'`

- [ ] **Step 3: Implement MessageBus**

Create `odigos/core/message_bus.py`:

```python
"""MessageBus — single interface for all conversation message publishing.

Every message in the system flows through bus.publish(). No other code
writes directly to the messages table. The bus writes to DB (source of
truth) and pushes to all registered channel adapters.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.channels.base import ChannelRegistry
    from odigos.db import Database


class MessageBus:
    def __init__(self, db: Database, channel_registry: ChannelRegistry):
        self.db = db
        self.channel_registry = channel_registry

    async def create_conversation(self, channel: str, title: str | None = None) -> str:
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
        model_used: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cost_usd: float | None = None,
        metadata: dict | None = None,
        idempotency_key: str | None = None,
        message_id: str | None = None,
    ) -> str:
        """Publish a message. Writes to DB + pushes to all registered channels.

        Returns the message ID. Pass message_id for pre-allocated IDs (streaming
        correlation). If idempotency_key is provided and already exists, returns
        the existing message ID without creating a duplicate.
        """
        # Idempotency check (callbacks may fire twice)
        if idempotency_key:
            existing = await self.db.fetch_one(
                "SELECT id FROM messages WHERE json_extract(metadata_json, '$.idempotency_key') = ?",
                (idempotency_key,),
            )
            if existing:
                return existing["id"]
            metadata = {**(metadata or {}), "idempotency_key": idempotency_key}

        # 1. Write to DB (source of truth)
        msg_id = message_id or uuid.uuid4().hex
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

        # 3. Create delivery rows for ALL registered channels, push to reachable ones
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
            delivery_id = uuid.uuid4().hex
            delivered_at = None
            try:
                if ch.is_reachable():
                    await ch.deliver(msg_data)
                    delivered_at = datetime.now(timezone.utc).isoformat()
            except Exception:
                pass  # Channel error, delivery stays pending
            await self.db.execute(
                "INSERT INTO message_deliveries (id, message_id, channel, delivered_at) "
                "VALUES (?, ?, ?, ?)",
                (delivery_id, msg_id, ch.channel_name, delivered_at),
            )

        return msg_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_message_bus.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/core/message_bus.py tests/test_message_bus.py
git commit -m "feat: add MessageBus — single interface for all message publishing"
```

---

### Task 3: Channel Adapter Interface

Add `deliver()` and `is_reachable()` to the Channel ABC. Update WebChannel to implement them. Remove `web:` prefix filtering from WebChannel.

**Files:**
- Modify: `odigos/channels/base.py`
- Modify: `odigos/channels/web.py`

- [ ] **Step 1: Add deliver() and is_reachable() to Channel ABC**

In `odigos/channels/base.py`, add two abstract methods to the `Channel` class after the existing `stop()` method:

```python
    @abstractmethod
    async def deliver(self, msg_data: dict) -> None:
        """Push a message to connected clients on this channel.
        Called by MessageBus for every published message."""
        ...

    @abstractmethod
    def is_reachable(self) -> bool:
        """Is at least one client connected on this channel?"""
        ...
```

- [ ] **Step 2: Update ChannelRegistry.for_conversation to handle plain UUIDs**

In `odigos/channels/base.py`, update the `for_conversation` method. Since conversation IDs are now plain UUIDs without prefixes, this method needs to look up the conversation's channel from the DB. But the registry doesn't have DB access, and this method is used in places that already know the channel. Change it to a simpler lookup that just returns by channel name (the `get()` method already does this). Keep `for_conversation()` for backward compatibility during the transition but it should no longer split on `:`:

```python
    def for_conversation(self, conversation_id: str) -> Channel | None:
        """Look up channel for a conversation.
        With plain UUID conversation IDs, callers should use get(channel_name) directly.
        This method is kept for backward compatibility during migration."""
        prefix = conversation_id.split(":", 1)[0] if ":" in conversation_id else ""
        return self._channels.get(prefix)
```

No change needed here — this method will be gradually replaced by callers using `get()` directly.

- [ ] **Step 3: Add deliver() and is_reachable() to WebChannel**

In `odigos/channels/web.py`, add these two methods:

```python
    async def deliver(self, msg_data: dict) -> None:
        """Push a message to ALL connected WebSocket clients.
        The bus calls this for every published message — delivery is per-user, not per-conversation."""
        for cid in list(self._connections.keys()):
            await self._send_to_connections(cid, msg_data)

    def is_reachable(self) -> bool:
        """Is at least one WebSocket client connected?"""
        return bool(self._connections)
```

- [ ] **Step 4: Remove web: prefix filter from _make_event_handler**

In `odigos/channels/web.py`, update `_make_event_handler` at line 103. Remove the `web:` prefix check since conversation IDs are now plain UUIDs:

```python
    def _make_event_handler(self, event_type: str):
        async def handler(et: str, conversation_id: str | None, data: dict) -> None:
            if not conversation_id:
                return
            await self.broadcast_event(conversation_id, {
                "type": "event",
                "source": event_type,
                "conversation_id": conversation_id,
                "data": data,
            })
        return handler
```

- [ ] **Step 5: Run existing tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_channels.py tests/test_webchannel.py -v`
Expected: PASS (or skip if these tests don't exist — check first)

- [ ] **Step 6: Commit**

```bash
git add odigos/channels/base.py odigos/channels/web.py
git commit -m "feat: add deliver()/is_reachable() to Channel ABC, implement in WebChannel"
```

---

### Task 4: Wire MessageBus into Container and Bootstrap

Add the `message_bus` field to Container and create it during bootstrap.

**Files:**
- Modify: `odigos/container.py`
- Modify: `odigos/bootstrap.py`

- [ ] **Step 1: Add message_bus to Container**

In `odigos/container.py`, add `MessageBus` to the TYPE_CHECKING imports:

```python
    from odigos.core.message_bus import MessageBus
```

Add the field after the `web_channel` field (around line 71):

```python
    message_bus: MessageBus | None = None
```

- [ ] **Step 2: Create MessageBus in bootstrap**

In `odigos/bootstrap.py`, after the WebChannel is created and registered (around line 765, after `self.container.web_channel = web_channel`), add:

```python
        # MessageBus — single interface for all message publishing
        from odigos.core.message_bus import MessageBus
        self.container.message_bus = MessageBus(
            db=db,
            channel_registry=self.container.channel_registry,
        )
        logger.info("MessageBus initialized")
```

- [ ] **Step 3: Run the test suite to check nothing breaks**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q --timeout=30`
Expected: PASS (existing tests should still work)

- [ ] **Step 4: Commit**

```bash
git add odigos/container.py odigos/bootstrap.py
git commit -m "feat: wire MessageBus into Container and Bootstrap"
```

---

### Task 5: Migrate Agent to MessageBus

Replace the direct INSERT in `agent.py` and remove the `web:` prefix conversation ID construction.

**Files:**
- Modify: `odigos/core/agent.py`

- [ ] **Step 1: Add message_bus parameter to Agent**

The Agent class needs access to the bus. Find the `__init__` method and add `message_bus` as a parameter. Store it as `self.message_bus`. Check how Agent is constructed in bootstrap.py and pass the bus there too.

In `agent.py`, the `__init__` likely accepts `db`, `provider`, etc. Add:

```python
    self.message_bus = message_bus
```

In `bootstrap.py`, wherever `Agent(...)` is constructed, add `message_bus=self.container.message_bus`. Find this by searching for `Agent(` in bootstrap.py.

- [ ] **Step 2: Replace direct INSERT in _run()**

In `odigos/core/agent.py` around line 150, replace:

```python
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (message.id, conversation_id, "user", message.content),
        )
```

With:

```python
        await self.message_bus.publish(
            conversation_id=conversation_id,
            role="user",
            content=message.content,
            channel=message.channel,
            message_id=message.id,
        )
```

- [ ] **Step 3: Replace _get_or_create_conversation prefix logic**

In `odigos/core/agent.py`, the `_get_or_create_conversation` method (lines 314-329) constructs `f"{message.channel}:{chat_id}"`. Replace it to use `message_bus.create_conversation()`:

```python
    async def _get_or_create_conversation(self, message: UniversalMessage) -> str:
        """Get existing conversation or create a new one via the message bus."""
        # The conversation_id comes directly from the caller (ws.py, telegram, etc.)
        # It's already a plain UUID created by bus.create_conversation()
        conv_id = message.metadata.get("conversation_id", "")
        if conv_id:
            existing = await self.db.fetch_one(
                "SELECT id FROM conversations WHERE id = ?", (conv_id,)
            )
            if existing:
                return existing["id"]

        # No valid conversation_id — create one
        return await self.message_bus.create_conversation(channel=message.channel)
```

- [ ] **Step 4: Update conversation count increment**

Around line 256, the agent does `message_count = message_count + 2`. Since the bus now increments message_count on each publish, remove this manual increment:

```python
        # Remove this block — the bus handles message_count increments per publish()
        # await self.db.execute(
        #     "UPDATE conversations SET last_message_at = datetime('now'), "
        #     "message_count = message_count + 2 WHERE id = ?",
        #     (conversation_id,),
        # )
```

Delete the block entirely.

- [ ] **Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q --timeout=30`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add odigos/core/agent.py odigos/bootstrap.py
git commit -m "refactor: agent uses MessageBus instead of direct INSERT"
```

---

### Task 6: Migrate Reflector to MessageBus

Replace the direct INSERT in `reflector.py` with `bus.publish()`.

**Files:**
- Modify: `odigos/core/reflector.py`

- [ ] **Step 1: Add message_bus to Reflector**

Find the Reflector's `__init__` and add `self.message_bus = message_bus`. Update the construction site in bootstrap.py to pass the bus.

- [ ] **Step 2: Replace direct INSERT in reflect()**

In `odigos/core/reflector.py` around lines 93-107, replace:

```python
        msg_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, model_used, "
            "tokens_in, tokens_out, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg_id,
                conversation_id,
                "assistant",
                content,
                response.model,
                response.tokens_in,
                response.tokens_out,
                response.cost_usd,
            ),
        )
```

With:

```python
        msg_id = message_id or uuid.uuid4().hex
        await self.message_bus.publish(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            channel=channel or "web",
            model_used=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
            message_id=msg_id,
        )
```

The `message_id` parameter is passed down from ws.py (the pre-allocated streaming ID). The `channel` parameter comes from the caller. Add both as parameters to the `reflect()` method signature.

- [ ] **Step 3: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_reflector_cost.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add odigos/core/reflector.py odigos/bootstrap.py
git commit -m "refactor: reflector uses MessageBus instead of direct INSERT"
```

---

### Task 7: Migrate WebSocket Handler

Update `ws.py` to use `bus.create_conversation()` for plain UUIDs, pre-allocate `message_id` for streaming, and include `message_id` in `chat_chunk` events.

**Files:**
- Modify: `odigos/api/ws.py`

- [ ] **Step 1: Replace conversation ID creation**

In `odigos/api/ws.py`, line 138 creates `f"web:{session_id}"` and line 162 creates `f"web:{uuid.uuid4().hex[:16]}"`. Replace both patterns.

Line 138 — initial ephemeral ID on connect:
```python
# Old:
conversation_id = f"web:{session_id}"
# New:
conversation_id = None  # No conversation until first message
```

Line 159-162 — conversation ID in chat queue:
```python
# Old:
client_conv_id = data.get("conversation_id")
if client_conv_id and client_conv_id != "new":
    conversation_id = client_conv_id
elif client_conv_id == "new" or not client_conv_id:
    conversation_id = f"web:{uuid.uuid4().hex[:16]}"
# New:
client_conv_id = data.get("conversation_id")
if client_conv_id and client_conv_id != "new":
    conversation_id = client_conv_id
elif client_conv_id == "new" or not client_conv_id:
    bus = websocket.app.state.container.message_bus
    conversation_id = await bus.create_conversation(channel="web")
```

- [ ] **Step 2: Remove chat_id prefix stripping**

Lines 164-165 strip the prefix:
```python
# Old:
chat_id = conversation_id.split(":", 1)[1] if ":" in conversation_id else conversation_id
msg_metadata = {"chat_id": chat_id}
# New:
msg_metadata = {"conversation_id": conversation_id}
```

The `UniversalMessage.metadata` now carries `conversation_id` directly instead of `chat_id`.

- [ ] **Step 3: Pre-allocate message_id for streaming**

Before calling `agent_service.handle_message()`, allocate a message_id:

```python
                streaming_msg_id = uuid.uuid4().hex
```

Update `send_chunk` to include the message_id:

```python
                async def send_chunk(text: str) -> None:
                    nonlocal streamed
                    streamed = True
                    try:
                        await websocket.send_json({
                            "type": "chat_chunk",
                            "content": text,
                            "conversation_id": conversation_id,
                            "message_id": streaming_msg_id,
                        })
                    except Exception:
                        pass
```

Pass `streaming_msg_id` to the agent service so it flows through to the reflector's `bus.publish(message_id=streaming_msg_id)`. This requires adding a `message_id` parameter to `agent_service.handle_message()` and threading it through to `reflector.reflect()`.

- [ ] **Step 4: Update conversation_started event**

Around line 217-220, the `conversation_started` event sends the conversation_id. This is now a plain UUID — no changes needed to the event format, just ensure it's sending the plain UUID:

```python
                        await websocket.send_json({
                            "type": "conversation_started",
                            "conversation_id": conversation_id,
                        })
```

This already works with plain UUIDs.

- [ ] **Step 5: Update WebChannel connection registration**

Line 141 registers with the `web:` prefixed ID. Since conversation_id is now None at connect time, register with a session-level key instead:

```python
# Old:
web_channel.register_connection(conversation_id, websocket)
# New:
web_channel.register_connection(session_id, websocket)
```

Then when conversation_id is known (after first message), re-register:

```python
web_channel.register_connection(conversation_id, websocket)
```

And on disconnect, unregister both:

```python
web_channel.unregister_connection(session_id, websocket)
if conversation_id:
    web_channel.unregister_connection(conversation_id, websocket)
```

- [ ] **Step 6: Send connected event with session_id (no conversation_id yet)**

The `connected` event currently sends `conversation_id`. Since we don't have one yet at connect time:

```python
await websocket.send_json({
    "type": "connected",
    "session_id": session_id,
})
```

- [ ] **Step 7: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_api_ws.py tests/test_api_ws_integration.py -v`
Expected: Some tests may need updating for the new conversation_id format. Fix as needed.

- [ ] **Step 8: Commit**

```bash
git add odigos/api/ws.py
git commit -m "refactor: ws.py uses MessageBus, plain UUID conversation IDs, streaming message_id"
```

---

### Task 8: Migrate Callbacks and Background Polling

Replace direct INSERTs + notifier + broadcast calls in `callbacks.py` and `background.py` with single `bus.publish()` calls.

**Files:**
- Modify: `odigos/api/callbacks.py`
- Modify: `odigos/core/heartbeat/background.py`

- [ ] **Step 1: Rewrite callbacks.py completion handler**

In `odigos/api/callbacks.py`, lines 89-119 (the successful completion block) do three things: INSERT message, notifier.notify(), web_channel.broadcast(). Replace all with one bus.publish():

```python
                # Inject system message via bus
                conversation_id = task["conversation_id"] or ""
                if conversation_id:
                    container = request.app.state.container
                    await container.message_bus.publish(
                        conversation_id=conversation_id,
                        role="system",
                        content=f"[Background task completed] {result.data}",
                        channel="callback",
                        message_type="artifact" if result.side_effect else "notification",
                        metadata={
                            "tool_name": task["tool_name"],
                            "task_id": task_id,
                            "artifact": result.side_effect.get("artifact") if result.side_effect else None,
                        },
                        idempotency_key=f"callback-{task_id}",
                    )
```

Remove the separate `notifier.notify()` and `web_channel.broadcast()` calls. The bus handles delivery to all channels.

- [ ] **Step 2: Rewrite background.py completion handler**

In `odigos/core/heartbeat/background.py`, lines 57-84 (the successful completion block) have the same pattern. Replace with bus.publish():

```python
                if conversation_id:
                    await hb.message_bus.publish(
                        conversation_id=conversation_id,
                        role="system",
                        content=f"[Background task completed] {result.data}",
                        channel="heartbeat",
                        message_type="artifact" if result.side_effect else "notification",
                        metadata={
                            "tool_name": tool_name,
                            "task_id": task["id"],
                            "artifact": result.side_effect.get("artifact") if result.side_effect else None,
                        },
                        idempotency_key=f"bg-{task['id']}",
                    )
```

Remove the separate `notifier.notify()` and `web_channel.broadcast()` calls.

The heartbeat needs access to `message_bus`. Check how the heartbeat gets its dependencies — it receives them in `__init__`. Add `message_bus` to the Heartbeat init and pass it from bootstrap. The heartbeat loop calls `poll_pending_tasks(hb)` passing `self` — so `hb.message_bus` will be available.

- [ ] **Step 3: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q --timeout=30`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add odigos/api/callbacks.py odigos/core/heartbeat/background.py odigos/core/heartbeat/__init__.py odigos/bootstrap.py
git commit -m "refactor: callbacks and background polling use MessageBus"
```

---

### Task 9: Backend Column Rename Audit

Update all Python files that reference `messages.timestamp` → `created_at` and `conversations.started_at` → `created_at`.

**Files:**
- Modify: `odigos/api/conversations.py`
- Modify: `odigos/api/state.py`
- Modify: `odigos/core/context.py`
- Modify: `odigos/core/budget.py`
- Modify: `odigos/core/evaluator.py`
- Modify: `odigos/core/trajectory.py`
- Modify: `odigos/core/data_export.py`
- Modify: `odigos/memory/summarizer.py`
- Modify: `odigos/core/heartbeat/profiling.py`
- Modify: `odigos/core/checkpoint.py`

- [ ] **Step 1: Update odigos/api/conversations.py**

Four changes:
1. Line 54: `ORDER BY timestamp ASC` → `ORDER BY created_at ASC`
2. Line 155: `SELECT role, content, timestamp` → `SELECT role, content, created_at`
3. Line 161: `msg.get("timestamp", "")` → `msg.get("created_at", "")`
4. Line 177: `SELECT id, role, content, timestamp` → `SELECT id, role, content, created_at`

Also add `?after=` parameter support to `get_conversation_messages`:

```python
@router.get("/conversations/{conversation_id:path}/messages")
async def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    after: str = Query(default=None),
    db: Database = Depends(get_db),
):
```

If `after` is provided, filter messages:
```python
    if after:
        messages = await db.fetch_all(
            "SELECT * FROM messages WHERE conversation_id = ? AND created_at > ? "
            "ORDER BY created_at ASC LIMIT ?",
            (conversation_id, after, limit),
        )
        return {"messages": messages, "total": len(messages)}
```

Also add `?category=` filter to `list_conversations`:

```python
@router.get("/conversations")
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    category: str = Query(default=None),
    db: Database = Depends(get_db),
):
```

Add category filter to the WHERE clause:
```python
    base_where = "WHERE (status = 'active' OR status IS NULL)"
    params = []
    if category:
        base_where += " AND category = ?"
        params.append(category)
```

Also update the archived check to use `status` field instead of `archived` column (the new schema uses `status TEXT DEFAULT 'active'` instead of `archived INTEGER DEFAULT 0`).

- [ ] **Step 2: Update remaining Python files**

For each file, do a find-and-replace of `ORDER BY timestamp` → `ORDER BY created_at` and `messages.timestamp` → `messages.created_at` and `WHERE timestamp` → `WHERE created_at` and `date(timestamp)` → `date(created_at)` and `strftime('%Y-%m', timestamp)` → `strftime('%Y-%m', created_at)`.

Files and specific changes:
- `odigos/api/state.py:100`: `timestamp >` → `created_at >`
- `odigos/api/state.py:144`: `started_at` → `created_at`
- `odigos/core/context.py:434,436`: `ORDER BY timestamp DESC` → `ORDER BY created_at DESC`
- `odigos/core/context.py:681`: `ORDER BY timestamp ASC` → `ORDER BY created_at ASC`
- `odigos/core/context.py:910,933`: `ORDER BY timestamp DESC` → `ORDER BY created_at DESC`
- `odigos/core/budget.py:39`: `date(timestamp)` → `date(created_at)`
- `odigos/core/budget.py:46`: `strftime('%Y-%m', timestamp)` → `strftime('%Y-%m', created_at)`
- `odigos/core/evaluator.py:108,178,232,236,257`: `timestamp` → `created_at`
- `odigos/core/trajectory.py:29,33,34`: `m.timestamp` → `m.created_at`
- `odigos/core/data_export.py:31`: `ORDER BY timestamp` → `ORDER BY created_at`
- `odigos/core/data_export.py:23`: `started_at` → `created_at`
- `odigos/memory/summarizer.py:66`: `ORDER BY timestamp` → `ORDER BY created_at`
- `odigos/core/heartbeat/profiling.py:77,349`: `ORDER BY timestamp` → `ORDER BY created_at`
- `odigos/core/checkpoint.py:133`: `ORDER BY started_at` → `ORDER BY created_at`

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q --timeout=30`
Expected: PASS (or failures only in tests that also need column name updates — those are fixed in Task 10)

- [ ] **Step 4: Commit**

```bash
git add odigos/
git commit -m "refactor: rename timestamp→created_at and started_at→created_at across backend"
```

---

### Task 10: Update Tests for New Schema

Update test fixtures and test SQL to use the new column names.

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_api_conversations.py`
- Modify: `tests/test_summarizer.py`
- Modify: `tests/test_api_metrics.py`
- Modify: `tests/test_state_api.py`

- [ ] **Step 1: Update conftest.py fake_db fixture**

Add `conversations` and `messages` tables matching the new schema to the `fake_db` fixture:

```python
        await conn.execute("""
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT,
                channel TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                message_count INTEGER DEFAULT 0,
                last_message_at TEXT,
                category TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("""
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                role TEXT NOT NULL,
                content TEXT,
                channel TEXT,
                message_type TEXT DEFAULT 'chat',
                model_used TEXT,
                tokens_in INTEGER,
                tokens_out INTEGER,
                cost_usd REAL,
                metadata_json TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("""
            CREATE TABLE message_deliveries (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL REFERENCES messages(id),
                channel TEXT NOT NULL,
                delivered_at TEXT,
                seen_at TEXT
            )
        """)
```

- [ ] **Step 2: Update test_api_conversations.py**

Replace all `started_at` references with `created_at` in INSERT statements. Replace `timestamp` references with `created_at` in assertions and queries. Update conversation IDs from `telegram:1` format to plain UUIDs. Replace `archived` column checks with `status` column.

Example: Line 59:
```python
# Old:
"INSERT INTO conversations (id, channel, started_at, last_message_at, message_count) "
# New:
"INSERT INTO conversations (id, channel, created_at, last_message_at, message_count) "
```

And conversation IDs:
```python
# Old:
("telegram:1", "telegram", ...)
# New:
("conv001", "telegram", ...)
```

- [ ] **Step 3: Update test_summarizer.py, test_api_metrics.py, test_state_api.py**

Same pattern: `started_at` → `created_at` in INSERT statements, `timestamp` → `created_at` in message queries.

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q --timeout=30`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: update fixtures and SQL for new schema column names"
```

---

### Task 11: Frontend — chatStore Streaming Correlation

Add `streamingMessageId` to chatStore for chunk-to-message correlation. Update streaming methods.

**Files:**
- Modify: `dashboard/src/stores/chatStore.ts`

- [ ] **Step 1: Add streamingMessageId to state**

In `dashboard/src/stores/chatStore.ts`, add to the interface:

```typescript
  streamingMessageId: string | null
  setStreamingMessageId: (id: string | null) => void
```

Add to the store:

```typescript
  streamingMessageId: null,
  setStreamingMessageId: (id) => set({ streamingMessageId: id }),
```

- [ ] **Step 2: Update addMessage to track streaming ID**

Modify `addMessage` to accept an optional `messageId`:

```typescript
  addMessage: (message, messageId?: string) => set((state) => ({
    messages: [...state.messages, message],
    ...(message.role === 'assistant' ? { isStreaming: true, streamingMessageId: messageId || null } : {}),
  })),
```

- [ ] **Step 3: Update finalizeLastMessage to clear streaming ID**

```typescript
  finalizeLastMessage: () =>
    set({ isStreaming: false, streamingMessageId: null }),
```

Also update `finalizeStreaming`:

```typescript
  finalizeStreaming: (fullContent: string) =>
    set((state) => {
      const msgs = [...state.messages]
      if (msgs.length > 0 && msgs[msgs.length - 1].role === 'assistant') {
        msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], content: fullContent }
      }
      return { messages: msgs, isStreaming: false, streamingMessageId: null }
    }),
```

- [ ] **Step 4: Update setActiveConversationId to clear streaming ID on switch**

```typescript
  setActiveConversationId: (id) => set((state) => {
    const switching = state.activeConversationId !== null && state.activeConversationId !== id
    return {
      activeConversationId: id,
      ...(switching ? {
        messages: [],
        isStreaming: false,
        streamingMessageId: null,
        thinking: false,
        status: null,
        suggestedActions: [],
      } : {}),
    }
  }),
```

- [ ] **Step 5: Verify syntax**

Run: `cd /Users/jacob/Projects/odigos/dashboard && node --check src/stores/chatStore.ts 2>&1 || npx tsc --noEmit src/stores/chatStore.ts 2>&1 | head -20`

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/stores/chatStore.ts
git commit -m "feat: add streamingMessageId to chatStore for chunk-to-message correlation"
```

---

### Task 12: Frontend — WebSocket Handler Updates

Update `useWebSocketHandler.ts` to handle `message` events from the bus, use `message_id` on chunks, drop late chunks, and catch-up on reconnect.

**Files:**
- Modify: `dashboard/src/layouts/hooks/useWebSocketHandler.ts`

- [ ] **Step 1: Update chat_chunk handler to use message_id**

In the `chat_chunk` handler (around line 55), use `msg.message_id` for correlation:

```typescript
        if (msg.type === 'chat_chunk') {
          if (msg.conversation_id && activeIdRef.current && msg.conversation_id !== activeIdRef.current) return
          const msgId = msg.message_id as string | undefined
          // Drop late chunks for already-finalized messages
          if (msgId && chat.streamingMessageId !== null && msgId !== chat.streamingMessageId) return
          chat.setThinking(false)
          chat.setStatus(null)
          const chunk = msg.content as string

          if (!useChatStore.getState().isStreaming) {
            chat.addMessage({ role: 'assistant', content: chunk, timestamp: new Date().toISOString() }, msgId)
          } else {
            chat.appendToLastMessage(chunk)
          }
        }
```

- [ ] **Step 2: Add message event handler**

Add a new handler for the bus `message` event type. This is distinct from `chat_response` — it comes from the bus for non-streaming messages (system messages, background task results, notifications):

```typescript
        if (msg.type === 'message') {
          if (msg.conversation_id && activeIdRef.current && msg.conversation_id !== activeIdRef.current) return
          const msgId = msg.id as string
          // If this matches the streaming message, finalize it
          if (msgId && useChatStore.getState().streamingMessageId === msgId) {
            chat.finalizeStreaming(msg.content as string)
          } else {
            // Non-streaming message from bus (system, notification, background result)
            chat.addMessage({
              role: msg.role as 'user' | 'assistant' | 'system',
              content: msg.content as string,
              timestamp: msg.created_at as string || new Date().toISOString(),
            })
          }
        }
```

- [ ] **Step 3: Add catch-up on reconnect**

In the connection status callback (around line 161), when reconnecting, fetch missed messages:

```typescript
      (isConnected) => {
        const wasConnected = useUIStore.getState().connected
        useUIStore.getState().setConnected(isConnected)
        if (isConnected && !wasConnected) {
          toast.dismiss()
          // Catch-up: fetch messages since last seen
          const activeId = activeIdRef.current
          const messages = useChatStore.getState().messages
          if (activeId && messages.length > 0) {
            const lastTimestamp = messages[messages.length - 1].timestamp
            if (lastTimestamp) {
              import('@/lib/api').then(({ get }) => {
                get(`/api/conversations/${activeId}/messages?after=${encodeURIComponent(lastTimestamp)}`).then((data: any) => {
                  if (data?.messages?.length > 0) {
                    const chat = useChatStore.getState()
                    for (const m of data.messages) {
                      chat.addMessage({
                        role: m.role,
                        content: m.content,
                        timestamp: m.created_at,
                      })
                    }
                  }
                }).catch(() => {})
              })
            }
          }
        }
        if (!isConnected && wasConnected) toast('Reconnecting...', { duration: 3000 })
      },
```

- [ ] **Step 4: Remove task_completed system message injection**

Around line 150, the `task_completed` handler manually injects a system message:

```typescript
          if (msg.conversation_id === activeIdRef.current) {
            chat.setMessages((prev) => [...prev, {
              role: 'system',
              content: `[Background task completed] ${resultText}`,
              timestamp: new Date().toISOString(),
            }])
          }
```

Remove this block. The bus `message` event now handles injecting the system message from the server side.

- [ ] **Step 5: Verify syntax**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit 2>&1 | head -30`

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/layouts/hooks/useWebSocketHandler.ts
git commit -m "feat: WS handler uses message_id correlation, bus message events, catch-up on reconnect"
```

---

### Task 13: Frontend — Column Name Updates

Update all frontend files that reference `started_at` to use `created_at`, and `timestamp` field in message responses.

**Files:**
- Modify: `dashboard/src/stores/conversationStore.ts`
- Modify: `dashboard/src/layouts/hooks/useConversationActions.ts`
- Modify: `dashboard/src/layouts/hooks/useWebSocketHandler.ts`
- Modify: `dashboard/src/components/ChatPanel.tsx`
- Modify: `dashboard/src/components/QuickSwitcher.tsx`
- Modify: `dashboard/src/pages/EvolutionPage.tsx`
- Modify: `dashboard/src/pages/settings/EvolutionTab.tsx`

- [ ] **Step 1: Update conversationStore.ts**

Change the Conversation type interface:

```typescript
// Old:
  started_at: string
// New:
  created_at: string
```

- [ ] **Step 2: Update useConversationActions.ts**

Line 91:
```typescript
// Old:
    const raw = c.last_message_at || c.started_at
// New:
    const raw = c.last_message_at || c.created_at
```

- [ ] **Step 3: Update useWebSocketHandler.ts conversation_started**

Line 115:
```typescript
// Old:
              started_at: new Date().toISOString(),
// New:
              created_at: new Date().toISOString(),
```

- [ ] **Step 4: Update ChatPanel.tsx message mapping**

In the message loading callback (around line 147), update the timestamp field:

```typescript
// Old:
            timestamp: m.timestamp,
// New:
            timestamp: m.created_at,
```

- [ ] **Step 5: Update QuickSwitcher.tsx**

Line 53 and 55:
```typescript
// Old:
          title: c.title || `Chat ${new Date(c.started_at).toLocaleDateString()}`,
          updated_at: c.last_message_at || c.started_at
// New:
          title: c.title || `Chat ${new Date(c.created_at).toLocaleDateString()}`,
          updated_at: c.last_message_at || c.created_at
```

- [ ] **Step 6: Update EvolutionPage.tsx and EvolutionTab.tsx**

Both files have a Trial type with `started_at` — these reference the `trials` table which uses `started_at` as domain timing (trial start, not creation). Leave these as-is — they reference a different table.

- [ ] **Step 7: Build check**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit 2>&1 | head -30`

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/
git commit -m "refactor: frontend uses created_at instead of started_at/timestamp"
```

---

### Task 14: Database Drop and Recreate

Drop the existing database and recreate from the updated schema.sql. This is a dev environment — clean slate.

**Files:**
- No file changes — runtime operation

- [ ] **Step 1: Stop the running server (if any)**

Run: `cd /Users/jacob/Projects/odigos && make down 2>/dev/null; true`

- [ ] **Step 2: Delete the database file**

Run: `rm -f /Users/jacob/Projects/odigos/data/odigos.db`

(The exact path may differ — check `config.yaml` for the database path. Default is `data/odigos.db`.)

- [ ] **Step 3: Verify schema.sql creates cleanly**

Run: `cd /Users/jacob/Projects/odigos && sqlite3 /tmp/test-schema.db < schema.sql && echo "OK" && rm /tmp/test-schema.db`
Expected: `OK`

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q --timeout=30`
Expected: All PASS

- [ ] **Step 5: Build frontend**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 6: Commit (no file changes, just verification)**

No commit needed — this is a runtime operation.

---

### Task 15: Integration Smoke Test

Start the server and verify the full flow works end-to-end.

- [ ] **Step 1: Start server**

Run: `cd /Users/jacob/Projects/odigos && make up`

- [ ] **Step 2: Verify database created with new schema**

Run: `sqlite3 data/odigos.db ".schema conversations" && sqlite3 data/odigos.db ".schema messages" && sqlite3 data/odigos.db ".schema message_deliveries"`
Expected: New schema with `created_at`, `channel`, `message_type`, `metadata_json` columns

- [ ] **Step 3: Open dashboard and send a message**

Open browser to the dashboard URL. Send a message. Verify:
- Conversation ID in URL is a plain UUID (no `web:` prefix)
- Messages appear in real-time via streaming
- Conversation shows in sidebar
- Switching conversations loads messages from API

- [ ] **Step 4: Check database for correct data**

Run: `sqlite3 data/odigos.db "SELECT id, channel, status, message_count FROM conversations LIMIT 5"`
Expected: Plain UUID id, channel='web', status='active'

Run: `sqlite3 data/odigos.db "SELECT id, role, channel, message_type, created_at FROM messages LIMIT 10"`
Expected: Proper columns with data

Run: `sqlite3 data/odigos.db "SELECT * FROM message_deliveries LIMIT 5"`
Expected: Delivery rows for each published message

- [ ] **Step 5: Commit any remaining fixes**

```bash
git add -A
git commit -m "fix: integration fixes for conversation foundation"
```
