from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from odigos.tools.peer import MessagePeerTool


@pytest.fixture
def mock_peer_client():
    client = MagicMock()
    client.send = AsyncMock(return_value={"status": "ok", "reply": "acknowledged"})
    client.list_peer_names.return_value = ["sarah", "bob"]
    return client


@pytest.fixture
def tool(mock_peer_client):
    return MessagePeerTool(peer_client=mock_peer_client)


def test_tool_metadata(tool):
    assert tool.name == "message_peer"
    assert "peer" in tool.description.lower() or "message" in tool.description.lower()
    props = tool.parameters_schema["properties"]
    assert "peer" in props
    assert "message" in props
    assert "peer" in tool.parameters_schema["required"]
    assert "message" in tool.parameters_schema["required"]


@pytest.mark.asyncio
async def test_send_message(tool, mock_peer_client):
    result = await tool.execute({"peer": "sarah", "message": "hello"})
    assert result.success is True
    assert "ok" in result.data
    mock_peer_client.send.assert_called_once_with(
        "sarah", "hello", message_type="message", metadata=None,
    )


@pytest.mark.asyncio
async def test_missing_peer(tool):
    result = await tool.execute({"message": "hello"})
    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_missing_message(tool):
    result = await tool.execute({"peer": "sarah"})
    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_unknown_peer(tool, mock_peer_client):
    mock_peer_client.send.side_effect = ValueError("Unknown peer: unknown")
    result = await tool.execute({"peer": "unknown", "message": "hello"})
    assert result.success is False
    assert "unknown" in result.data.lower() or "unknown" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_message_type_param(tool, mock_peer_client):
    result = await tool.execute({
        "peer": "sarah",
        "message": "need help",
        "message_type": "help_request",
    })
    assert result.success is True
    mock_peer_client.send.assert_called_once_with(
        "sarah", "need help", message_type="help_request", metadata=None,
    )
