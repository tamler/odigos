"""Tests for the AgentClient WebSocket communication layer."""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock

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
async def test_send_ws_delivers(db, mock_peers):
    """Send via WebSocket returns delivered status."""
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)
    mock_ws = AsyncMock()
    client._ws_connections["Archie"] = mock_ws

    result = await client.send("Archie", payload={"text": "hello"}, message_type="message")
    assert result["status"] == "delivered"
    mock_ws.send.assert_called_once()


@pytest.mark.asyncio
async def test_send_queues_when_ws_down(db, mock_peers):
    """When WebSocket is not connected, message is queued."""
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    result = await client.send("Archie", payload={"text": "hello"}, message_type="message")
    assert result["status"] == "queued"

    row = await db.fetch_one("SELECT * FROM peer_messages WHERE peer_name = 'Archie'")
    assert row["status"] == "queued"


@pytest.mark.asyncio
async def test_announce_builds_envelope(db, mock_peers):
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)
    env = client.build_announce(
        role="personal_assistant",
        description="Jacob's AI",
        capabilities=["search", "code"],
    )
    assert env.type == "registry_announce"
    assert env.from_agent == "Odigos"
    assert env.to_agent == "*"
    assert env.payload["role"] == "personal_assistant"
    assert env.payload["capabilities"] == ["search", "code"]


@pytest.mark.asyncio
async def test_send_response_correlates(db, mock_peers):
    """send_response() copies correlation_id from original envelope."""
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)
    mock_ws = AsyncMock()
    client._ws_connections["Archie"] = mock_ws

    original = PeerEnvelope(
        from_agent="Archie",
        to_agent="Odigos",
        type="task_request",
        payload={"task": "summarize"},
        correlation_id="corr-123",
    )

    result = await client.send_response(original, payload={"result": "done"})
    assert result["status"] == "delivered"

    sent_data = json.loads(mock_ws.send.call_args[0][0])
    assert sent_data["to_agent"] == "Archie"
    assert sent_data["correlation_id"] == "corr-123"
    assert sent_data["type"] == "task_response"
    assert sent_data["payload"]["result"] == "done"


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
