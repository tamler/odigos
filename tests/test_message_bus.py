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
    assert len(conv_id) == 32
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
    msg_id = await bus.publish(conversation_id=conv_id, role="user", content="Hello world", channel="web")
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
    msg_id = await bus.publish(conv_id, role="assistant", content="response", channel="web",
                                model_used="claude-3", tokens_in=100, tokens_out=50, cost_usd=0.001)
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
    deliveries = await bus_db.fetch_all("SELECT * FROM message_deliveries WHERE message_id = ? ORDER BY channel", (msg_id,))
    assert len(deliveries) == 2
    tg_row = [d for d in deliveries if d["channel"] == "telegram"][0]
    assert tg_row["delivered_at"] is None
    web_row = [d for d in deliveries if d["channel"] == "web"][0]
    assert web_row["delivered_at"] is not None


@pytest.mark.asyncio
async def test_publish_with_pre_allocated_message_id(bus_db):
    from odigos.core.message_bus import MessageBus
    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry())
    conv_id = await bus.create_conversation(channel="web")
    pre_id = uuid.uuid4().hex
    msg_id = await bus.publish(conv_id, role="assistant", content="streamed", channel="web", message_id=pre_id)
    assert msg_id == pre_id
    row = await bus_db.fetch_one("SELECT * FROM messages WHERE id = ?", (pre_id,))
    assert row is not None


@pytest.mark.asyncio
async def test_publish_idempotency_key_prevents_duplicates(bus_db):
    from odigos.core.message_bus import MessageBus
    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry())
    conv_id = await bus.create_conversation(channel="web")
    msg_id1 = await bus.publish(conv_id, role="system", content="task done", channel="callback", idempotency_key="task-123")
    msg_id2 = await bus.publish(conv_id, role="system", content="task done duplicate", channel="callback", idempotency_key="task-123")
    assert msg_id1 == msg_id2
    count = await bus_db.fetch_one("SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ?", (conv_id,))
    assert count["cnt"] == 1


@pytest.mark.asyncio
async def test_publish_metadata_stored_as_json(bus_db):
    from odigos.core.message_bus import MessageBus
    bus = MessageBus(db=bus_db, channel_registry=FakeRegistry())
    conv_id = await bus.create_conversation(channel="web")
    msg_id = await bus.publish(conv_id, role="system", content="artifact ready", channel="callback",
                                message_type="artifact", metadata={"artifact_ids": ["a1", "a2"]})
    row = await bus_db.fetch_one("SELECT * FROM messages WHERE id = ?", (msg_id,))
    assert row["message_type"] == "artifact"
    meta = json.loads(row["metadata_json"])
    assert meta["artifact_ids"] == ["a1", "a2"]
