"""Tests for the NotifyTool."""
from __future__ import annotations

import pytest

from odigos.channels.base import ChannelRegistry
from odigos.channels.web import WebChannel
from odigos.core.notifier import Notifier
from odigos.tools.notify import NotifyTool
from unittest.mock import AsyncMock


@pytest.fixture
def web_channel():
    return WebChannel()


@pytest.fixture
def make_ws():
    def _make():
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        return ws
    return _make


@pytest.fixture
def registry(web_channel):
    reg = ChannelRegistry()
    reg.register("web", web_channel)
    return reg


@pytest.fixture
def notifier(registry):
    return Notifier(channel_registry=registry)


@pytest.fixture
def tool(notifier):
    return NotifyTool(notifier=notifier)


def test_tool_metadata(tool):
    assert tool.name == "send_notification"
    props = tool.parameters_schema["properties"]
    assert "message" in props
    assert "priority" in props


@pytest.mark.asyncio
async def test_send_info_notification(tool, web_channel, make_ws):
    ws = make_ws()
    web_channel.register_connection("web:conv1", ws)

    result = await tool.execute({"message": "Task complete"})

    assert result.success is True
    assert "Task complete" in result.data
    ws.send_json.assert_awaited_once()
    payload = ws.send_json.call_args[0][0]
    assert payload["type"] == "notification"
    assert payload["title"] == "Update"
    assert payload["body"] == "Task complete"


@pytest.mark.asyncio
async def test_send_warning_notification(tool, web_channel, make_ws):
    ws = make_ws()
    web_channel.register_connection("web:conv1", ws)

    result = await tool.execute({"message": "Disk space low", "priority": "warning"})

    assert result.success is True
    payload = ws.send_json.call_args[0][0]
    assert payload["title"] == "Warning"
    assert payload["body"] == "Disk space low"


@pytest.mark.asyncio
async def test_send_urgent_notification(tool, web_channel, make_ws):
    ws = make_ws()
    web_channel.register_connection("web:conv1", ws)

    result = await tool.execute({"message": "Action needed", "priority": "urgent"})

    assert result.success is True
    payload = ws.send_json.call_args[0][0]
    assert payload["title"] == "Action Required"


@pytest.mark.asyncio
async def test_missing_message(tool):
    result = await tool.execute({})
    assert result.success is False
    assert result.error == "No message provided"


@pytest.mark.asyncio
async def test_empty_message(tool):
    result = await tool.execute({"message": ""})
    assert result.success is False
    assert result.error == "No message provided"


@pytest.mark.asyncio
async def test_default_priority_is_info(tool, web_channel, make_ws):
    ws = make_ws()
    web_channel.register_connection("web:conv1", ws)

    await tool.execute({"message": "hello"})

    payload = ws.send_json.call_args[0][0]
    assert payload["title"] == "Update"


@pytest.mark.asyncio
async def test_broadcasts_to_all_connections(tool, web_channel, make_ws):
    ws1 = make_ws()
    ws2 = make_ws()
    web_channel.register_connection("web:a", ws1)
    web_channel.register_connection("web:b", ws2)

    result = await tool.execute({"message": "broadcast"})

    assert result.success is True
    assert ws1.send_json.await_count == 1
    assert ws2.send_json.await_count == 1
