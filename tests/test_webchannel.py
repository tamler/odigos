from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from odigos.channels.web import WebChannel


@pytest.fixture
def channel():
    return WebChannel()


@pytest.fixture
def make_ws():
    def _make():
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        return ws
    return _make


@pytest.mark.asyncio
async def test_register_and_send_message(channel, make_ws):
    ws = make_ws()
    channel.register_connection("conv1", ws)

    await channel.send_message("conv1", "hello")

    ws.send_json.assert_awaited_once()
    payload = ws.send_json.call_args[0][0]
    assert payload["type"] == "chat"
    assert payload["content"] == "hello"
    assert payload["conversation_id"] == "conv1"
    assert payload["role"] == "assistant"


@pytest.mark.asyncio
async def test_send_to_unknown_conversation_is_noop(channel, make_ws):
    ws = make_ws()
    # No connections registered — should not raise
    await channel.send_message("unknown", "hello")
    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_unregister_connection(channel, make_ws):
    ws = make_ws()
    channel.register_connection("conv1", ws)
    channel.unregister_connection("conv1", ws)

    await channel.send_message("conv1", "hello")
    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_multiple_connections_same_conversation(channel, make_ws):
    ws1 = make_ws()
    ws2 = make_ws()
    channel.register_connection("conv1", ws1)
    channel.register_connection("conv1", ws2)

    await channel.send_message("conv1", "hello")

    ws1.send_json.assert_awaited_once()
    ws2.send_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_broadcast_event(channel, make_ws):
    ws = make_ws()
    channel.register_connection("conv1", ws)
    channel.add_subscription("conv1", "events")

    event = {"type": "event", "data": "test"}
    await channel.broadcast_event("conv1", event)

    ws.send_json.assert_awaited_once_with(event)


@pytest.mark.asyncio
async def test_broadcast_skips_unsubscribed(channel, make_ws):
    ws = make_ws()
    channel.register_connection("conv1", ws)
    # No subscription added

    await channel.broadcast_event("conv1", {"type": "event"})
    ws.send_json.assert_not_awaited()

    await channel.broadcast_status("conv1", {"type": "status"})
    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_stop_are_noops(channel, make_ws):
    ws = make_ws()
    channel.register_connection("conv1", ws)
    channel.add_subscription("conv1", "events")

    await channel.start()  # should not raise

    await channel.stop()
    # After stop, internal state should be cleared
    assert len(channel._connections) == 0
    assert len(channel._subscriptions) == 0


@pytest.mark.asyncio
async def test_failed_send_removes_connection(channel, make_ws):
    ws = make_ws()
    ws.send_json.side_effect = ConnectionError("closed")
    channel.register_connection("conv1", ws)

    await channel.send_message("conv1", "hello")

    # Connection should have been removed after failure
    assert ws not in channel._connections.get("conv1", set())


class TestTracerForwarding:
    """Tests for setup_tracer_forwarding and _make_event_handler."""

    @pytest.mark.asyncio
    async def test_tracer_events_forwarded_to_subscribed(self, channel, make_ws):
        ws = make_ws()
        channel.register_connection("web:conv1", ws)
        channel.add_subscription("web:conv1", "events")

        captured_callbacks: dict[str, object] = {}
        tracer = type("MockTracer", (), {
            "subscribe": lambda self, et, cb: captured_callbacks.update({et: cb}),
        })()

        channel.setup_tracer_forwarding(tracer)

        assert "step_start" in captured_callbacks
        assert "response" in captured_callbacks
        assert "error" in captured_callbacks
        assert "timeout" in captured_callbacks
        assert "budget_exceeded" in captured_callbacks

        await captured_callbacks["step_start"]("step_start", "web:conv1", {"step": 1})

        ws.send_json.assert_awaited_once()
        payload = ws.send_json.call_args[0][0]
        assert payload["type"] == "event"
        assert payload["source"] == "step_start"
        assert payload["conversation_id"] == "web:conv1"
        assert payload["data"] == {"step": 1}

    @pytest.mark.asyncio
    async def test_tracer_events_not_forwarded_to_unsubscribed(self, channel, make_ws):
        ws = make_ws()
        channel.register_connection("web:conv1", ws)
        # No subscription to "events"

        captured_callbacks: dict[str, object] = {}
        tracer = type("MockTracer", (), {
            "subscribe": lambda self, et, cb: captured_callbacks.update({et: cb}),
        })()

        channel.setup_tracer_forwarding(tracer)

        await captured_callbacks["step_start"]("step_start", "web:conv1", {"step": 1})

        ws.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tracer_events_skip_non_web_conversations(self, channel, make_ws):
        ws = make_ws()
        channel.register_connection("web:conv1", ws)
        channel.add_subscription("web:conv1", "events")

        captured_callbacks: dict[str, object] = {}
        tracer = type("MockTracer", (), {
            "subscribe": lambda self, et, cb: captured_callbacks.update({et: cb}),
        })()

        channel.setup_tracer_forwarding(tracer)

        await captured_callbacks["step_start"]("step_start", "telegram:42", {"step": 1})

        ws.send_json.assert_not_awaited()
