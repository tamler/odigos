"""Tests for conversation API endpoints."""

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.conversations import router
from odigos.db import Database


def _make_app(db: Database) -> FastAPI:
    """Create a minimal FastAPI app with the conversations router and fake state."""
    app = FastAPI()
    app.include_router(router)
    app.state.db = db
    app.state.settings = SimpleNamespace(api_key="test-key")
    return app


@pytest_asyncio.fixture
async def db(tmp_db_path: str) -> Database:
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def client(db: Database) -> AsyncClient:
    app = _make_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_list_conversations_empty(client: AsyncClient):
    resp = await client.get("/api/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"conversations": [], "total": 0}


@pytest.mark.asyncio
async def test_list_conversations_with_data(client: AsyncClient, db: Database):
    await db.execute(
        "INSERT INTO conversations (id, channel, started_at, last_message_at, message_count) "
        "VALUES (?, ?, ?, ?, ?)",
        ("telegram:1", "telegram", "2026-01-01 00:00:00", "2026-01-01 01:00:00", 3),
    )
    await db.execute(
        "INSERT INTO conversations (id, channel, started_at, last_message_at, message_count) "
        "VALUES (?, ?, ?, ?, ?)",
        ("telegram:2", "telegram", "2026-01-02 00:00:00", "2026-01-02 02:00:00", 5),
    )

    resp = await client.get("/api/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["conversations"]) == 2
    # Ordered by last_message_at DESC
    assert data["conversations"][0]["id"] == "telegram:2"
    assert data["conversations"][1]["id"] == "telegram:1"


@pytest.mark.asyncio
async def test_list_conversations_pagination(client: AsyncClient, db: Database):
    for i in range(5):
        await db.execute(
            "INSERT INTO conversations (id, channel, started_at, last_message_at, message_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"telegram:{i}", "telegram", "2026-01-01 00:00:00", f"2026-01-01 0{i}:00:00", i),
        )

    resp = await client.get("/api/conversations", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["conversations"]) == 2
    # Most recent first
    assert data["conversations"][0]["id"] == "telegram:4"
    assert data["conversations"][1]["id"] == "telegram:3"

    # Second page
    resp2 = await client.get("/api/conversations", params={"limit": 2, "offset": 2})
    data2 = resp2.json()
    assert data2["total"] == 5
    assert len(data2["conversations"]) == 2
    assert data2["conversations"][0]["id"] == "telegram:2"


@pytest.mark.asyncio
async def test_get_conversation_by_id(client: AsyncClient, db: Database):
    await db.execute(
        "INSERT INTO conversations (id, channel, started_at, last_message_at, message_count) "
        "VALUES (?, ?, ?, ?, ?)",
        ("telegram:42", "telegram", "2026-01-01 00:00:00", "2026-01-01 01:00:00", 3),
    )

    resp = await client.get("/api/conversations/telegram:42")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "telegram:42"
    assert data["channel"] == "telegram"
    assert data["message_count"] == 3


@pytest.mark.asyncio
async def test_get_conversation_not_found(client: AsyncClient):
    resp = await client.get("/api/conversations/nonexistent:99")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_messages(client: AsyncClient, db: Database):
    await db.execute(
        "INSERT INTO conversations (id, channel, started_at, last_message_at, message_count) "
        "VALUES (?, ?, ?, ?, ?)",
        ("telegram:42", "telegram", "2026-01-01 00:00:00", "2026-01-01 01:00:00", 2),
    )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        ("msg-2", "telegram:42", "assistant", "Hello!", "2026-01-01 00:01:00"),
    )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        ("msg-1", "telegram:42", "user", "Hi", "2026-01-01 00:00:00"),
    )

    resp = await client.get("/api/conversations/telegram:42/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["messages"]) == 2
    # Ordered by timestamp ASC
    assert data["messages"][0]["id"] == "msg-1"
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["id"] == "msg-2"
    assert data["messages"][1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_get_messages_conversation_not_found(client: AsyncClient):
    resp = await client.get("/api/conversations/nonexistent:99/messages")
    assert resp.status_code == 404
