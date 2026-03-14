"""Tests for the Notifier — proactive notification system."""
from __future__ import annotations

import pytest

from odigos.channels.base import ChannelRegistry
from odigos.channels.web import WebChannel
from odigos.core.notifier import Notifier
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


class TestNotifier:
    @pytest.mark.asyncio
    async def test_notify_sends_to_web_channel(self, notifier, web_channel, make_ws):
        ws = make_ws()
        web_channel.register_connection("web:conv1", ws)

        await notifier.notify(
            title="Test Title",
            body="Test body content",
            conversation_id="web:conv1",
        )

        ws.send_json.assert_awaited_once()
        payload = ws.send_json.call_args[0][0]
        assert payload["type"] == "notification"
        assert payload["title"] == "Test Title"
        assert payload["body"] == "Test body content"

    @pytest.mark.asyncio
    async def test_notify_with_conversation_id(self, notifier, web_channel, make_ws):
        ws1 = make_ws()
        ws2 = make_ws()
        web_channel.register_connection("web:conv1", ws1)
        web_channel.register_connection("web:conv2", ws2)

        await notifier.notify(
            title="Targeted",
            body="Only conv1",
            conversation_id="web:conv1",
        )

        ws1.send_json.assert_awaited_once()
        ws2.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_notify_broadcast_no_conversation_id(self, notifier, web_channel, make_ws):
        ws1 = make_ws()
        ws2 = make_ws()
        web_channel.register_connection("web:conv1", ws1)
        web_channel.register_connection("web:conv2", ws2)

        await notifier.notify(
            title="Broadcast",
            body="To everyone",
        )

        ws1.send_json.assert_awaited_once()
        ws2.send_json.assert_awaited_once()
        payload1 = ws1.send_json.call_args[0][0]
        assert payload1["type"] == "notification"
        assert payload1["title"] == "Broadcast"

    @pytest.mark.asyncio
    async def test_notify_specific_channels(self, notifier, web_channel, make_ws):
        ws = make_ws()
        web_channel.register_connection("web:conv1", ws)

        await notifier.notify(
            title="Web Only",
            body="Content",
            conversation_id="web:conv1",
            channels=["web"],
        )

        ws.send_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notify_unknown_channel_ignored(self, notifier, web_channel, make_ws):
        ws = make_ws()
        web_channel.register_connection("web:conv1", ws)

        # Should not raise when requesting non-existent channel
        await notifier.notify(
            title="Test",
            body="Content",
            channels=["nonexistent"],
        )
        ws.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_notify_no_connections_is_noop(self, notifier):
        # No connections registered — should not raise
        await notifier.notify(
            title="Nobody Home",
            body="Content",
            conversation_id="web:nobody",
        )

    @pytest.mark.asyncio
    async def test_notify_empty_title(self, notifier, web_channel, make_ws):
        ws = make_ws()
        web_channel.register_connection("web:conv1", ws)

        await notifier.notify(title="", body="Just body", conversation_id="web:conv1")

        payload = ws.send_json.call_args[0][0]
        assert payload["title"] == ""
        assert payload["body"] == "Just body"


class TestWebChannelNotify:
    """Direct tests on WebChannel.notify method."""

    @pytest.mark.asyncio
    async def test_notify_payload_structure(self, web_channel, make_ws):
        ws = make_ws()
        web_channel.register_connection("web:c1", ws)

        await web_channel.notify(title="T", body="B", conversation_id="web:c1")

        payload = ws.send_json.call_args[0][0]
        assert payload == {
            "type": "notification",
            "title": "T",
            "body": "B",
            "conversation_id": "web:c1",
        }

    @pytest.mark.asyncio
    async def test_notify_broadcast(self, web_channel, make_ws):
        ws1 = make_ws()
        ws2 = make_ws()
        web_channel.register_connection("web:a", ws1)
        web_channel.register_connection("web:b", ws2)

        await web_channel.notify(title="All", body="Content")

        assert ws1.send_json.await_count == 1
        assert ws2.send_json.await_count == 1
