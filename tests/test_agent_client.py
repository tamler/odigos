"""Tests for the AgentClient WebSocket communication layer."""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from odigos.core.agent_client import AgentClient, PeerEnvelope
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def mock_peers():
    from odigos.config import PeerConfig
    return [
        PeerConfig(name="Archie", netbird_ip="100.64.0.2", ws_port=8001, api_key="secret"),
        PeerConfig(name="Legacy", url="http://old-peer:8000", api_key="old-key"),
    ]


def test_peer_envelope_serialization():
    env = PeerEnvelope(
        from_agent="Odigos",
        to_agent="Archie",
        type="task_request",
        payload={"task": "summarize", "doc_id": "123"},
        correlation_id="corr-abc",
        priority="high",
    )
    data = env.to_dict()
    assert data["type"] == "task_request"
    assert data["from_agent"] == "Odigos"
    assert data["to_agent"] == "Archie"
    assert data["payload"]["task"] == "summarize"
    assert data["correlation_id"] == "corr-abc"
    assert data["priority"] == "high"
    assert "id" in data
    assert "timestamp" in data

    restored = PeerEnvelope.from_dict(data)
    assert restored.type == env.type
    assert restored.from_agent == env.from_agent
    assert restored.to_agent == env.to_agent
    assert restored.correlation_id == env.correlation_id


def test_peer_envelope_defaults():
    env = PeerEnvelope(
        from_agent="Odigos",
        to_agent="Archie",
        type="message",
        payload={"text": "hello"},
    )
    assert env.correlation_id is None
    assert env.priority == "normal"
    assert env.id  # UUID auto-generated
    assert env.timestamp  # timestamp auto-generated


@pytest.mark.asyncio
async def test_send_falls_back_to_http(db, mock_peers):
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    with patch("httpx.AsyncClient") as mock_httpx_cls:
        mock_httpx = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        mock_httpx.post = AsyncMock(return_value=mock_resp)
        mock_httpx.__aenter__ = AsyncMock(return_value=mock_httpx)
        mock_httpx.__aexit__ = AsyncMock()
        mock_httpx_cls.return_value = mock_httpx

        result = await client.send("Legacy", "Hello", message_type="message")
        assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_send_records_message(db, mock_peers):
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    with patch("httpx.AsyncClient") as mock_httpx_cls:
        mock_httpx = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        mock_httpx.post = AsyncMock(return_value=mock_resp)
        mock_httpx.__aenter__ = AsyncMock(return_value=mock_httpx)
        mock_httpx.__aexit__ = AsyncMock()
        mock_httpx_cls.return_value = mock_httpx

        await client.send("Legacy", "Hello", message_type="message")

    row = await db.fetch_one("SELECT * FROM peer_messages WHERE peer_name = 'Legacy'")
    assert row is not None
    assert row["direction"] == "outbound"


@pytest.mark.asyncio
async def test_announce_self(db, mock_peers):
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)
    msg = client.build_announce(
        role="personal_assistant",
        description="Jacob's AI",
        capabilities=["search", "code"],
    )
    assert msg.type == "registry_announce"
    assert msg.from_agent == "Odigos"
    assert "personal_assistant" in msg.payload["role"]


@pytest.mark.asyncio
async def test_handle_incoming_announce(db, mock_peers):
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    msg = PeerEnvelope(
        type="registry_announce",
        from_agent="Archie",
        to_agent="Odigos",
        payload={
            "role": "backend_dev",
            "description": "Backend specialist",
            "specialty": "coding",
            "capabilities": ["code_execute"],
            "evolution_score": 7.5,
            "allow_external_evaluation": True,
        },
    )
    await client.handle_incoming(msg, peer_ip="100.64.0.2")

    row = await db.fetch_one("SELECT * FROM agent_registry WHERE agent_name = 'Archie'")
    assert row is not None
    assert row["role"] == "backend_dev"
    assert row["status"] == "online"
