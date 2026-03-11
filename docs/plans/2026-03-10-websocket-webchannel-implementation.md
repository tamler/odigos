# Unified WebSocket + Web Channel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a single WebSocket endpoint at `/api/ws` with typed JSON messages for real-time chat, status updates, and event streaming, plus a `WebChannel` class that integrates into the existing channel/agent pipeline.

**Architecture:** `WebChannel` implements the `Channel` ABC and manages active WebSocket connections keyed by conversation_id. A FastAPI WebSocket route handles connection lifecycle, auth via query param token, and message dispatch. The Tracer's subscribe mechanism forwards agent events to connected clients in real time. Chat messages flow through the same `agent.handle_message()` pipeline as Telegram.

**Tech Stack:** FastAPI WebSocket support (built-in via Starlette), existing Channel/Agent/Tracer infrastructure.

---

## Context for the Implementer

**Channel ABC** (`odigos/channels/base.py`):
- Must implement: `start()`, `stop()`, `send_message(conversation_id, text)`
- Optional: `send_approval_request(approval_id, tool_name, conversation_id, arguments)`
- `channel_name` class attribute identifies the channel

**Conversation ID format:** `"web:{session_id}"` — derived from `f"{msg.channel}:{msg.metadata.get('chat_id', msg.sender)}"` in `agent._get_or_create_conversation()`.

**ChannelRegistry:** `registry.for_conversation("web:abc123")` returns the WebChannel by matching the `"web"` prefix.

**Tracer events:** Subscribe with `tracer.subscribe(event_type, callback)`. Callback signature: `async def cb(event_type, conversation_id, data)`. Events: `step_start`, `response`, `error`, `timeout`, `budget_exceeded`.

**Auth:** WebSocket can't use Authorization header in browsers. Use query param: `/api/ws?token=<key>`. Same logic as REST: empty api_key = dev mode (allow all).

**State:** `app.state.agent`, `app.state.settings`, `app.state.tracer`, `app.state.channel_registry` — all available via request/websocket.app.state.

---

### Task 1: WebChannel Class — Connection Management

**Files:**
- Create: `odigos/channels/web.py`
- Test: `tests/test_webchannel.py`

**Step 1: Write the failing test**

```python
# tests/test_webchannel.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from odigos.channels.web import WebChannel


class TestWebChannelConnections:
    def _make_ws(self):
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    async def test_register_and_send_message(self):
        channel = WebChannel()
        ws = self._make_ws()
        channel.register_connection("web:sess1", ws)

        await channel.send_message("web:sess1", "Hello!")

        ws.send_json.assert_called_once()
        payload = ws.send_json.call_args[0][0]
        assert payload["type"] == "chat"
        assert payload["content"] == "Hello!"
        assert payload["conversation_id"] == "web:sess1"
        assert payload["role"] == "assistant"

    async def test_send_to_unknown_conversation_is_noop(self):
        channel = WebChannel()
        await channel.send_message("web:unknown", "Hello!")
        # No error raised

    async def test_unregister_connection(self):
        channel = WebChannel()
        ws = self._make_ws()
        channel.register_connection("web:sess1", ws)
        channel.unregister_connection("web:sess1", ws)

        await channel.send_message("web:sess1", "Hello!")
        ws.send_json.assert_not_called()

    async def test_multiple_connections_same_conversation(self):
        channel = WebChannel()
        ws1 = self._make_ws()
        ws2 = self._make_ws()
        channel.register_connection("web:sess1", ws1)
        channel.register_connection("web:sess1", ws2)

        await channel.send_message("web:sess1", "Broadcast")

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()

    async def test_broadcast_event(self):
        channel = WebChannel()
        ws = self._make_ws()
        channel.register_connection("web:sess1", ws)
        channel.add_subscription("web:sess1", "events")

        await channel.broadcast_event("web:sess1", {
            "type": "event",
            "source": "heartbeat",
            "data": {"tick": 1},
        })

        ws.send_json.assert_called_once()

    async def test_broadcast_skips_unsubscribed(self):
        channel = WebChannel()
        ws = self._make_ws()
        channel.register_connection("web:sess1", ws)
        # No subscription to "events"

        await channel.broadcast_event("web:sess1", {
            "type": "event",
            "source": "heartbeat",
            "data": {},
        })

        ws.send_json.assert_not_called()

    async def test_start_stop_are_noops(self):
        channel = WebChannel()
        await channel.start()
        await channel.stop()
        # No errors

    async def test_failed_send_removes_connection(self):
        channel = WebChannel()
        ws = self._make_ws()
        ws.send_json = AsyncMock(side_effect=Exception("disconnected"))
        channel.register_connection("web:sess1", ws)

        await channel.send_message("web:sess1", "Hello!")

        # Connection should be removed after failure
        assert len(channel._connections.get("web:sess1", set())) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_webchannel.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write minimal implementation**

```python
# odigos/channels/web.py
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from odigos.channels.base import Channel

logger = logging.getLogger(__name__)


class WebChannel(Channel):
    """WebSocket-backed channel for real-time web dashboard communication."""

    channel_name = "web"

    def __init__(self) -> None:
        # conversation_id -> set of WebSocket connections
        self._connections: dict[str, set] = defaultdict(set)
        # conversation_id -> set of subscribed event channels ("status", "events")
        self._subscriptions: dict[str, set[str]] = defaultdict(set)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        self._connections.clear()
        self._subscriptions.clear()

    def register_connection(self, conversation_id: str, ws: Any) -> None:
        self._connections[conversation_id].add(ws)

    def unregister_connection(self, conversation_id: str, ws: Any) -> None:
        self._connections[conversation_id].discard(ws)
        if not self._connections[conversation_id]:
            del self._connections[conversation_id]
            self._subscriptions.pop(conversation_id, None)

    def add_subscription(self, conversation_id: str, channel: str) -> None:
        self._subscriptions[conversation_id].add(channel)

    async def send_message(self, conversation_id: str, text: str) -> None:
        """Send a chat message to all connections for this conversation."""
        payload = {
            "type": "chat",
            "content": text,
            "conversation_id": conversation_id,
            "role": "assistant",
        }
        await self._send_to_connections(conversation_id, payload)

    async def broadcast_event(self, conversation_id: str, event: dict) -> None:
        """Send an event to connections that have subscribed to events."""
        if "events" not in self._subscriptions.get(conversation_id, set()):
            return
        await self._send_to_connections(conversation_id, event)

    async def broadcast_status(self, conversation_id: str, status: dict) -> None:
        """Send a status update to connections that have subscribed to status."""
        if "status" not in self._subscriptions.get(conversation_id, set()):
            return
        await self._send_to_connections(conversation_id, status)

    async def _send_to_connections(self, conversation_id: str, payload: dict) -> None:
        connections = list(self._connections.get(conversation_id, set()))
        failed = []
        for ws in connections:
            try:
                await ws.send_json(payload)
            except Exception:
                logger.warning("WebSocket send failed, removing connection")
                failed.append(ws)
        for ws in failed:
            self._connections[conversation_id].discard(ws)
        if not self._connections.get(conversation_id):
            self._connections.pop(conversation_id, None)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_webchannel.py -v`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add odigos/channels/web.py tests/test_webchannel.py
git commit -m "feat(ws): add WebChannel class with connection management"
```

---

### Task 2: WebSocket Route — Connection Lifecycle + Chat

**Files:**
- Create: `odigos/api/ws.py`
- Test: `tests/test_api_ws.py`

**Step 1: Write the failing test**

```python
# tests/test_api_ws.py
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from fastapi import FastAPI

from odigos.api.ws import router, websocket_endpoint
from odigos.channels.web import WebChannel


def _make_app(api_key="", agent_response="Hello from agent"):
    a = FastAPI()
    a.state.settings = type("S", (), {"api_key": api_key})()
    a.state.agent = MagicMock()
    a.state.agent.handle_message = AsyncMock(return_value=agent_response)
    a.state.tracer = MagicMock()
    a.state.tracer.subscribe = MagicMock()
    web_channel = WebChannel()
    a.state.web_channel = web_channel
    a.include_router(router)
    return a, web_channel


class TestWebSocketAuth:
    def test_no_token_when_required_closes(self):
        app, _ = _make_app(api_key="secret")
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws"):
                pass

    def test_wrong_token_closes(self):
        app, _ = _make_app(api_key="secret")
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws?token=wrong"):
                pass

    def test_valid_token_connects(self):
        app, _ = _make_app(api_key="secret")
        client = TestClient(app)
        with client.websocket_connect("/api/ws?token=secret") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"

    def test_no_key_configured_allows_connection(self):
        app, _ = _make_app(api_key="")
        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"


class TestWebSocketChat:
    def test_chat_message_returns_response(self):
        app, _ = _make_app(agent_response="Agent says hi")
        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # connected message
            ws.send_json({
                "type": "chat",
                "content": "Hello",
                "conversation_id": "web:test-session",
            })
            resp = ws.receive_json()
            assert resp["type"] == "chat"
            assert resp["content"] == "Agent says hi"
            assert resp["conversation_id"] == "web:test-session"
            assert resp["role"] == "assistant"

    def test_chat_auto_generates_conversation_id(self):
        app, _ = _make_app()
        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            connected = ws.receive_json()
            session_id = connected["session_id"]
            ws.send_json({"type": "chat", "content": "Hi"})
            resp = ws.receive_json()
            assert resp["conversation_id"].startswith("web:")


class TestWebSocketSubscribe:
    def test_subscribe_to_events(self):
        app, web_channel = _make_app()
        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            connected = ws.receive_json()
            session_id = connected["session_id"]
            ws.send_json({"type": "subscribe", "channels": ["status", "events"]})
            resp = ws.receive_json()
            assert resp["type"] == "subscribed"
            conv_id = f"web:{session_id}"
            assert "events" in web_channel._subscriptions.get(conv_id, set())
            assert "status" in web_channel._subscriptions.get(conv_id, set())
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_ws.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write minimal implementation**

```python
# odigos/api/ws.py
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from odigos.channels.base import UniversalMessage

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Auth check
    settings = websocket.app.state.settings
    if settings.api_key:
        token = websocket.query_params.get("token", "")
        if token != settings.api_key:
            await websocket.close(code=4003, reason="Invalid or missing token")
            return

    await websocket.accept()

    session_id = uuid.uuid4().hex[:12]
    conversation_id = f"web:{session_id}"
    web_channel = websocket.app.state.web_channel
    agent = websocket.app.state.agent

    web_channel.register_connection(conversation_id, websocket)

    try:
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "conversation_id": conversation_id,
        })

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "chat":
                content = data.get("content", "")
                conv_id = data.get("conversation_id", conversation_id)

                if not content:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Empty content",
                    })
                    continue

                msg = UniversalMessage(
                    id=str(uuid.uuid4()),
                    channel="web",
                    sender=session_id,
                    content=content,
                    timestamp=datetime.now(timezone.utc),
                    metadata={"chat_id": conv_id.split(":", 1)[1] if ":" in conv_id else session_id},
                )

                response = await agent.handle_message(msg)

                await websocket.send_json({
                    "type": "chat",
                    "content": response,
                    "conversation_id": conv_id,
                    "role": "assistant",
                })

            elif msg_type == "subscribe":
                channels = data.get("channels", [])
                for ch in channels:
                    if ch in ("status", "events"):
                        web_channel.add_subscription(conversation_id, ch)
                await websocket.send_json({
                    "type": "subscribed",
                    "channels": channels,
                })

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", conversation_id)
    except Exception:
        logger.exception("WebSocket error: %s", conversation_id)
    finally:
        web_channel.unregister_connection(conversation_id, websocket)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_ws.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add odigos/api/ws.py tests/test_api_ws.py
git commit -m "feat(ws): add WebSocket endpoint with auth, chat, and subscribe"
```

---

### Task 3: Tracer Event Forwarding

**Files:**
- Modify: `odigos/channels/web.py` — add `setup_tracer_forwarding(tracer)` method
- Test: `tests/test_webchannel.py` — add event forwarding tests

**Step 1: Write the failing test**

Add to `tests/test_webchannel.py`:

```python
class TestTracerForwarding:
    async def test_tracer_events_forwarded_to_subscribed(self):
        from unittest.mock import call
        channel = WebChannel()
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        channel.register_connection("web:sess1", ws)
        channel.add_subscription("web:sess1", "events")

        tracer = MagicMock()
        captured_callbacks = {}
        def fake_subscribe(event_type, cb):
            captured_callbacks[event_type] = cb
        tracer.subscribe = fake_subscribe

        channel.setup_tracer_forwarding(tracer)

        # Simulate a tracer event
        assert "response" in captured_callbacks
        await captured_callbacks["response"]("response", "web:sess1", {"model": "test"})

        ws.send_json.assert_called_once()
        payload = ws.send_json.call_args[0][0]
        assert payload["type"] == "event"
        assert payload["source"] == "response"

    async def test_tracer_events_not_forwarded_to_unsubscribed(self):
        channel = WebChannel()
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        channel.register_connection("web:sess1", ws)
        # No subscription

        tracer = MagicMock()
        captured_callbacks = {}
        tracer.subscribe = lambda et, cb: captured_callbacks.update({et: cb})

        channel.setup_tracer_forwarding(tracer)

        await captured_callbacks["response"]("response", "web:sess1", {"model": "test"})
        ws.send_json.assert_not_called()

    async def test_tracer_events_skip_non_web_conversations(self):
        channel = WebChannel()
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        channel.register_connection("web:sess1", ws)
        channel.add_subscription("web:sess1", "events")

        tracer = MagicMock()
        captured_callbacks = {}
        tracer.subscribe = lambda et, cb: captured_callbacks.update({et: cb})

        channel.setup_tracer_forwarding(tracer)

        # Event for a telegram conversation — should be ignored
        await captured_callbacks["response"]("response", "telegram:42", {"model": "test"})
        ws.send_json.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_webchannel.py::TestTracerForwarding -v`
Expected: FAIL (AttributeError: WebChannel has no setup_tracer_forwarding)

**Step 3: Add to `odigos/channels/web.py`**

```python
    _FORWARDED_EVENTS = ("step_start", "response", "error", "timeout", "budget_exceeded")

    def setup_tracer_forwarding(self, tracer) -> None:
        """Subscribe to tracer events and forward to connected WebSocket clients."""
        for event_type in self._FORWARDED_EVENTS:
            tracer.subscribe(event_type, self._make_event_handler(event_type))

    def _make_event_handler(self, event_type: str):
        async def handler(et: str, conversation_id: str | None, data: dict) -> None:
            if not conversation_id or not conversation_id.startswith("web:"):
                return
            await self.broadcast_event(conversation_id, {
                "type": "event",
                "source": event_type,
                "conversation_id": conversation_id,
                "data": data,
            })
        return handler
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_webchannel.py -v`
Expected: PASS (11 tests)

**Step 5: Commit**

```bash
git add odigos/channels/web.py tests/test_webchannel.py
git commit -m "feat(ws): add tracer event forwarding to WebSocket clients"
```

---

### Task 4: Wire WebChannel into main.py

**Files:**
- Modify: `odigos/main.py` — create WebChannel, register it, mount WS router
- Test: `tests/test_api_ws_integration.py`

**Step 1: Write the failing test**

```python
# tests/test_api_ws_integration.py
import pytest
from starlette.testclient import TestClient


class TestWebSocketMounted:
    def test_ws_endpoint_exists(self):
        from odigos.main import app
        from unittest.mock import AsyncMock, MagicMock
        from odigos.channels.web import WebChannel

        # Stub state
        app.state.settings = type("S", (), {"api_key": ""})()
        app.state.agent = MagicMock()
        app.state.agent.handle_message = AsyncMock(return_value="ok")
        app.state.tracer = MagicMock()
        app.state.tracer.subscribe = MagicMock()
        app.state.web_channel = WebChannel()

        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert "session_id" in data
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_ws_integration.py -v`
Expected: FAIL (WebSocket route not found -> connection refused or 404)

**Step 3: Wire into main.py**

Add to the imports section of `odigos/main.py`:
```python
from odigos.api.ws import router as ws_router
from odigos.channels.web import WebChannel
```

Add `app.include_router(ws_router)` with the other router includes.

In the lifespan function, after the channel_registry is created and before channels are started:
```python
web_channel = WebChannel()
channel_registry.register("web", web_channel)
web_channel.setup_tracer_forwarding(tracer)
app.state.web_channel = web_channel
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_ws_integration.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add odigos/main.py tests/test_api_ws_integration.py
git commit -m "feat(ws): wire WebChannel and WebSocket route into main app"
```
