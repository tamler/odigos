from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from odigos.config import PeerConfig
from odigos.core.peers import PeerClient, PeerMessage


@pytest.fixture
def peers():
    return [
        PeerConfig(name="sarah", url="http://sarah.local:8000", api_key="sarah-key"),
        PeerConfig(name="bob", url="http://bob.local:8000", api_key="bob-key"),
    ]


@pytest.fixture
def client(peers):
    return PeerClient(peers=peers, agent_name="odigos")


def test_peer_message_fields():
    msg = PeerMessage(from_agent="odigos", message_type="message", content="hello")
    assert msg.from_agent == "odigos"
    assert msg.message_type == "message"
    assert msg.content == "hello"
    assert msg.metadata == {}


def test_peer_message_with_metadata():
    msg = PeerMessage(
        from_agent="odigos",
        message_type="help_request",
        content="need help",
        metadata={"urgency": "high"},
    )
    assert msg.metadata == {"urgency": "high"}


def test_get_peer(client):
    peer = client.get_peer("sarah")
    assert peer is not None
    assert peer.name == "sarah"
    assert peer.url == "http://sarah.local:8000"


def test_get_unknown_peer(client):
    assert client.get_peer("unknown") is None


def test_list_peers(client):
    names = client.list_peer_names()
    assert sorted(names) == ["bob", "sarah"]


@pytest.mark.asyncio
async def test_send_message(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok", "reply": "got it"}

    mock_client_instance = AsyncMock()
    mock_client_instance.post.return_value = mock_response
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch("odigos.core.peers.httpx.AsyncClient", return_value=mock_client_instance):
        result = await client.send("sarah", "hello there")

    assert result == {"status": "ok", "reply": "got it"}
    mock_client_instance.post.assert_called_once_with(
        "http://sarah.local:8000/api/agent/message",
        json={
            "from_agent": "odigos",
            "message_type": "message",
            "content": "hello there",
            "metadata": {},
        },
        headers={"Authorization": "Bearer sarah-key"},
    )


@pytest.mark.asyncio
async def test_send_to_unknown_raises(client):
    with pytest.raises(ValueError, match="Unknown peer: unknown"):
        await client.send("unknown", "hello")
