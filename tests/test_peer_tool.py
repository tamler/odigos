from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from odigos.tools.peer import MessagePeerTool


@pytest.fixture
def mock_peer_client():
    client = MagicMock()
    client.send = AsyncMock(return_value={"status": "delivered", "message_id": "abc-123"})
    client.list_peer_names.return_value = ["sarah", "bob"]
    client.agent_name = "Odigos"
    return client


@pytest.fixture
def tool(mock_peer_client):
    return MessagePeerTool(peer_client=mock_peer_client)


def test_tool_metadata(tool):
    assert tool.name == "message_peer"
    props = tool.parameters_schema["properties"]
    assert "peer" in props
    assert "message" in props
    assert "priority" in props


@pytest.mark.asyncio
async def test_send_message(tool, mock_peer_client):
    result = await tool.execute({"peer": "sarah", "message": "hello"})
    assert result.success is True
    assert "delivered" in result.data
    mock_peer_client.send.assert_called_once_with(
        "sarah", payload={"content": "hello"}, message_type="message", priority="normal",
    )


@pytest.mark.asyncio
async def test_send_with_priority(tool, mock_peer_client):
    result = await tool.execute({"peer": "sarah", "message": "urgent", "priority": "high"})
    assert result.success is True
    mock_peer_client.send.assert_called_once_with(
        "sarah", payload={"content": "urgent"}, message_type="message", priority="high",
    )


@pytest.mark.asyncio
async def test_send_queued(tool, mock_peer_client):
    mock_peer_client.send = AsyncMock(return_value={"status": "queued", "message_id": "abc-123"})
    result = await tool.execute({"peer": "sarah", "message": "hello"})
    assert result.success is True
    assert "queued" in result.data


@pytest.mark.asyncio
async def test_missing_peer(tool):
    result = await tool.execute({"message": "hello"})
    assert result.success is False


@pytest.mark.asyncio
async def test_missing_message(tool):
    result = await tool.execute({"peer": "sarah"})
    assert result.success is False


@pytest.mark.asyncio
async def test_unknown_peer(tool, mock_peer_client):
    mock_peer_client.send.side_effect = ValueError("Unknown peer: unknown")
    result = await tool.execute({"peer": "unknown", "message": "hello"})
    assert result.success is False
