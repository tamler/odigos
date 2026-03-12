# Peer Communication Protocol Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade peer communication to WebSocket-only with PeerEnvelope, persistent outbox, correlation support, and inert-when-solo behavior.

**Architecture:** Replace `AgentMessage` with `PeerEnvelope` (adds `to_agent`, `correlation_id`, `priority`, `payload` dict). Remove HTTP fallback from `AgentClient.send()` — WS-only with outbox for failures. Add heartbeat phase to flush outbox. Slim HTTP to discovery-only announce endpoint. Entire peer system is inert when no peers exist.

**Tech Stack:** Python/asyncio, FastAPI WebSocket, SQLite (peer_messages table), dataclasses

**Design doc:** `docs/plans/2026-03-12-peer-protocol-design.md`

---

### Task 1: Replace AgentMessage with PeerEnvelope

**Files:**
- Modify: `odigos/core/agent_client.py`
- Modify: `tests/test_agent_client.py`

**Step 1: Write the failing test**

In `tests/test_agent_client.py`, replace the import and `test_agent_message_serialization` test. At the top, change:

```python
from odigos.core.agent_client import AgentClient, AgentMessage
```
to:
```python
from odigos.core.agent_client import AgentClient, PeerEnvelope
```

Replace `test_agent_message_serialization`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_client.py::test_peer_envelope_serialization -v`
Expected: FAIL — `PeerEnvelope` not found

**Step 3: Implement PeerEnvelope**

In `odigos/core/agent_client.py`, replace the `AgentMessage` dataclass (lines 34-62) with:

```python
@dataclass
class PeerEnvelope:
    from_agent: str
    to_agent: str
    type: str
    payload: dict
    correlation_id: str | None = None
    priority: str = "normal"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "type": self.type,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "priority": self.priority,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PeerEnvelope:
        return cls(
            from_agent=data["from_agent"],
            to_agent=data.get("to_agent", ""),
            type=data["type"],
            payload=data.get("payload", {}),
            correlation_id=data.get("correlation_id"),
            priority=data.get("priority", "normal"),
            id=data.get("id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )
```

Keep `AgentMessage = PeerEnvelope` as a temporary alias so other files don't break yet. Add after the class:

```python
# Backward compatibility alias — remove once all references are updated
AgentMessage = PeerEnvelope
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_agent_client.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -x -q`
Expected: Some tests may need `content` → `payload` adjustments. Fix any that break by updating their AgentMessage construction to use `payload` and `to_agent` fields. The alias keeps backward compat for code using `AgentMessage`.

**Step 6: Commit**

```bash
git add odigos/core/agent_client.py tests/test_agent_client.py
git commit -m "feat: replace AgentMessage with PeerEnvelope dataclass"
```

---

### Task 2: Update AgentClient.send() — WS-only with outbox

**Files:**
- Modify: `odigos/core/agent_client.py`
- Modify: `tests/test_agent_client.py`

**Step 1: Write the failing tests**

Add to `tests/test_agent_client.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_client.py::test_send_ws_delivers tests/test_agent_client.py::test_send_queues_when_ws_down -v`
Expected: FAIL — send() signature doesn't match

**Step 3: Rewrite send() method**

Replace the `send()` method in `AgentClient` with:

```python
    async def send(
        self,
        peer_name: str,
        payload: dict | None = None,
        message_type: str = "message",
        content: str = "",
        metadata: dict | None = None,
        correlation_id: str | None = None,
        priority: str = "normal",
    ) -> dict:
        """Send a message to a peer via WebSocket. Queues to outbox if WS is down."""
        peer = self._peers.get(peer_name)
        if not peer:
            raise ValueError(f"Unknown peer: {peer_name}")

        # Support both new payload style and legacy content+metadata style
        if payload is None:
            payload = {"content": content, **(metadata or {})}

        envelope = PeerEnvelope(
            from_agent=self.agent_name,
            to_agent=peer_name,
            type=message_type,
            payload=payload,
            correlation_id=correlation_id,
            priority=priority,
        )

        # Record outbound message
        if self._db:
            await self._db.execute(
                "INSERT INTO peer_messages "
                "(message_id, direction, peer_name, message_type, content, metadata_json, status) "
                "VALUES (?, 'outbound', ?, ?, ?, ?, 'queued')",
                (envelope.id, peer_name, message_type, json.dumps(payload),
                 json.dumps(envelope.to_dict())),
            )

        # Try WebSocket
        ws = self._ws_connections.get(peer_name)
        if ws:
            try:
                await ws.send(json.dumps(envelope.to_dict()))
                if self._db:
                    await self._db.execute(
                        "UPDATE peer_messages SET status = 'delivered', delivered_at = datetime('now') "
                        "WHERE message_id = ?",
                        (envelope.id,),
                    )
                return {"status": "delivered", "message_id": envelope.id}
            except Exception:
                logger.warning("WebSocket send to %s failed, message queued", peer_name)
                del self._ws_connections[peer_name]

        # No WS connection — message stays queued in outbox
        return {"status": "queued", "message_id": envelope.id}
```

Remove the `import httpx` at the top of the file since HTTP is no longer used.

**Step 4: Run tests**

Run: `uv run pytest tests/test_agent_client.py -v`
Expected: PASS. The old `test_send_falls_back_to_http` and `test_send_records_message` will fail — remove them since HTTP fallback is gone.

**Step 5: Run full suite**

Run: `uv run pytest tests/ -x -q`
Fix any callers that use the old `send(peer, content_string, ...)` signature by updating to use `payload=` or the `content=` backward-compat parameter.

**Step 6: Commit**

```bash
git add odigos/core/agent_client.py tests/test_agent_client.py
git commit -m "feat: WS-only send with outbox queuing, remove HTTP fallback"
```

---

### Task 3: Add send_response() helper and update build_announce()

**Files:**
- Modify: `odigos/core/agent_client.py`
- Modify: `tests/test_agent_client.py`

**Step 1: Write the failing tests**

Add to `tests/test_agent_client.py`:

```python
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

    # Check the envelope sent over WS
    sent_data = json.loads(mock_ws.send.call_args[0][0])
    assert sent_data["to_agent"] == "Archie"
    assert sent_data["correlation_id"] == "corr-123"
    assert sent_data["type"] == "task_response"
    assert sent_data["payload"]["result"] == "done"
```

Also update `test_announce_self` to use PeerEnvelope:

```python
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
    assert env.payload["role"] == "personal_assistant"
    assert env.payload["capabilities"] == ["search", "code"]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_client.py::test_send_response_correlates -v`
Expected: FAIL — `send_response` doesn't exist

**Step 3: Add send_response() and update build_announce()**

Add to `AgentClient`:

```python
    async def send_response(
        self,
        original: PeerEnvelope,
        payload: dict,
        message_type: str = "task_response",
    ) -> dict:
        """Send a response that automatically correlates to the original request."""
        return await self.send(
            peer_name=original.from_agent,
            payload=payload,
            message_type=message_type,
            correlation_id=original.correlation_id,
        )
```

Update `build_announce()` to return a `PeerEnvelope` with `payload` dict instead of JSON-encoded `content`:

```python
    def build_announce(
        self,
        role: str = "",
        description: str = "",
        specialty: str | None = None,
        capabilities: list[str] | None = None,
        evolution_score: float | None = None,
        allow_external_evaluation: bool = False,
    ) -> PeerEnvelope:
        """Build a registry_announce envelope for broadcasting identity to peers."""
        return PeerEnvelope(
            from_agent=self.agent_name,
            to_agent="*",  # broadcast
            type=MSG_REGISTRY_ANNOUNCE,
            payload={
                "role": role,
                "description": description,
                "specialty": specialty,
                "capabilities": capabilities or [],
                "evolution_score": evolution_score,
                "allow_external_evaluation": allow_external_evaluation,
            },
        )
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_agent_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/core/agent_client.py tests/test_agent_client.py
git commit -m "feat: add send_response() helper, update build_announce() for PeerEnvelope"
```

---

### Task 4: Update handle_incoming() for PeerEnvelope

**Files:**
- Modify: `odigos/core/agent_client.py`
- Modify: `tests/test_agent_client.py`

**Step 1: Write the failing tests**

Add to `tests/test_agent_client.py`:

```python
@pytest.mark.asyncio
async def test_handle_incoming_validates_to_agent(db, mock_peers):
    """Messages not addressed to this agent are ignored."""
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    handler = AsyncMock()
    client.on_message("task_request", handler)

    msg = PeerEnvelope(
        from_agent="Archie",
        to_agent="SomeOtherAgent",
        type="task_request",
        payload={"task": "summarize"},
    )
    await client.handle_incoming(msg, peer_ip="100.64.0.2")

    handler.assert_not_called()


@pytest.mark.asyncio
async def test_handle_incoming_accepts_broadcast(db, mock_peers):
    """Messages addressed to '*' (broadcast) are accepted."""
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    handler = AsyncMock()
    client.on_message("registry_announce", handler)

    msg = PeerEnvelope(
        from_agent="Archie",
        to_agent="*",
        type="registry_announce",
        payload={"role": "backend_dev"},
    )
    await client.handle_incoming(msg, peer_ip="100.64.0.2")

    handler.assert_called_once()


@pytest.mark.asyncio
async def test_handle_incoming_deduplicates(db, mock_peers):
    """Duplicate message IDs are ignored."""
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    handler = AsyncMock()
    client.on_message("task_request", handler)

    msg = PeerEnvelope(
        from_agent="Archie",
        to_agent="Odigos",
        type="task_request",
        payload={"task": "summarize"},
    )
    await client.handle_incoming(msg, peer_ip="100.64.0.2")
    await client.handle_incoming(msg, peer_ip="100.64.0.2")  # same id

    handler.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_client.py::test_handle_incoming_validates_to_agent -v`
Expected: FAIL — current handle_incoming doesn't check to_agent

**Step 3: Rewrite handle_incoming()**

Replace `handle_incoming()` in `AgentClient`:

```python
    async def handle_incoming(self, msg: PeerEnvelope, peer_ip: str = "") -> None:
        """Process an incoming message from a peer agent."""
        # Validate recipient
        if msg.to_agent not in (self.agent_name, "*", ""):
            logger.debug("Ignoring message for %s (we are %s)", msg.to_agent, self.agent_name)
            return

        # Deduplicate
        if self._db:
            existing = await self._db.fetch_one(
                "SELECT 1 FROM peer_messages WHERE message_id = ? AND direction = 'inbound'",
                (msg.id,),
            )
            if existing:
                logger.debug("Duplicate message %s, ignoring", msg.id)
                return

            # Record inbound
            await self._db.execute(
                "INSERT INTO peer_messages "
                "(message_id, direction, peer_name, message_type, content, metadata_json, status, response_to) "
                "VALUES (?, 'inbound', ?, ?, ?, ?, 'received', ?)",
                (msg.id, msg.from_agent, msg.type, json.dumps(msg.payload),
                 json.dumps(msg.to_dict()), msg.correlation_id),
            )

        # Built-in handlers
        if msg.type == MSG_REGISTRY_ANNOUNCE:
            await self._handle_announce(msg, peer_ip)
        elif msg.type == MSG_STATUS_PING:
            await self._handle_ping(msg)

        # Custom handlers
        for handler in self._handlers.get(msg.type, []):
            try:
                await handler(msg)
            except Exception:
                logger.warning("Handler for %s failed", msg.type, exc_info=True)
```

Update `_handle_announce()` to read from `msg.payload` instead of `json.loads(msg.content)`:

```python
    async def _handle_announce(self, msg: PeerEnvelope, peer_ip: str) -> None:
        """Upsert agent_registry from a registry_announce message."""
        data = msg.payload
        if not data or not self._db:
            return

        # ... rest stays the same, just uses `data` directly instead of json.loads(msg.content)
```

Update `_handle_ping()` to accept `PeerEnvelope`:

```python
    async def _handle_ping(self, msg: PeerEnvelope) -> None:
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_agent_client.py -v`
Expected: PASS

**Step 5: Fix test_handle_incoming_announce**

Update the existing `test_handle_incoming_announce` test to use PeerEnvelope with `payload=` dict instead of `content=json.dumps(...)`:

```python
@pytest.mark.asyncio
async def test_handle_incoming_announce(db, mock_peers):
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    msg = PeerEnvelope(
        from_agent="Archie",
        to_agent="*",
        type="registry_announce",
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
```

**Step 6: Run full suite**

Run: `uv run pytest tests/ -x -q`

**Step 7: Commit**

```bash
git add odigos/core/agent_client.py tests/test_agent_client.py
git commit -m "feat: handle_incoming with to_agent validation and deduplication"
```

---

### Task 5: Update broadcast_announce() and add outbox flush

**Files:**
- Modify: `odigos/core/agent_client.py`
- Modify: `tests/test_agent_client.py`

**Step 1: Write the failing tests**

Add to `tests/test_agent_client.py`:

```python
@pytest.mark.asyncio
async def test_flush_outbox_delivers_queued(db, mock_peers):
    """flush_outbox() sends queued messages when WS becomes available."""
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    # Queue a message (no WS connection)
    await client.send("Archie", payload={"text": "hello"}, message_type="message")

    row = await db.fetch_one("SELECT * FROM peer_messages WHERE peer_name = 'Archie'")
    assert row["status"] == "queued"

    # Now connect WS
    mock_ws = AsyncMock()
    client._ws_connections["Archie"] = mock_ws

    flushed = await client.flush_outbox()
    assert flushed == 1

    row = await db.fetch_one("SELECT * FROM peer_messages WHERE peer_name = 'Archie'")
    assert row["status"] == "delivered"
    mock_ws.send.assert_called_once()


@pytest.mark.asyncio
async def test_flush_outbox_skips_disconnected(db, mock_peers):
    """flush_outbox() leaves messages queued if WS is still down."""
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    await client.send("Archie", payload={"text": "hello"}, message_type="message")

    flushed = await client.flush_outbox()
    assert flushed == 0

    row = await db.fetch_one("SELECT * FROM peer_messages WHERE peer_name = 'Archie'")
    assert row["status"] == "queued"


@pytest.mark.asyncio
async def test_flush_outbox_expires_old_messages(db, mock_peers):
    """flush_outbox() marks old queued messages as expired."""
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    # Insert an old queued message directly
    await db.execute(
        "INSERT INTO peer_messages "
        "(message_id, direction, peer_name, message_type, content, metadata_json, status, created_at) "
        "VALUES (?, 'outbound', 'Archie', 'message', '{}', '{}', 'queued', datetime('now', '-25 hours'))",
        ("old-msg",),
    )

    expired = await client.flush_outbox(expire_hours=24)

    row = await db.fetch_one("SELECT * FROM peer_messages WHERE message_id = 'old-msg'")
    assert row["status"] == "expired"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_client.py::test_flush_outbox_delivers_queued -v`
Expected: FAIL — `flush_outbox` doesn't exist

**Step 3: Update broadcast_announce() and add flush_outbox()**

Update `broadcast_announce()` to use the new `send()` signature:

```python
    async def broadcast_announce(self, **kwargs) -> None:
        """Send a registry_announce message to all configured peers."""
        env = self.build_announce(**kwargs)
        for peer_name in self._peers:
            try:
                await self.send(peer_name, payload=env.payload, message_type=MSG_REGISTRY_ANNOUNCE)
            except Exception:
                logger.debug("Failed to announce to %s", peer_name, exc_info=True)
```

Add `flush_outbox()`:

```python
    async def flush_outbox(self, expire_hours: int = 24) -> int:
        """Flush queued outbox messages. Returns count of messages delivered."""
        if not self._db:
            return 0

        # Expire old messages
        await self._db.execute(
            "UPDATE peer_messages SET status = 'expired' "
            "WHERE status = 'queued' AND direction = 'outbound' "
            "AND created_at < datetime('now', ?)",
            (f"-{expire_hours} hours",),
        )

        # Fetch queued messages
        queued = await self._db.fetch_all(
            "SELECT message_id, peer_name, metadata_json FROM peer_messages "
            "WHERE status = 'queued' AND direction = 'outbound' "
            "ORDER BY created_at ASC",
        )
        if not queued:
            return 0

        delivered = 0
        for row in queued:
            peer_name = row["peer_name"]
            ws = self._ws_connections.get(peer_name)
            if not ws:
                continue

            try:
                # metadata_json stores the full serialized envelope
                await ws.send(row["metadata_json"])
                await self._db.execute(
                    "UPDATE peer_messages SET status = 'delivered', delivered_at = datetime('now') "
                    "WHERE message_id = ?",
                    (row["message_id"],),
                )
                delivered += 1
            except Exception:
                logger.warning("Outbox flush to %s failed", peer_name)
                del self._ws_connections[peer_name]

        return delivered
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_agent_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/core/agent_client.py tests/test_agent_client.py
git commit -m "feat: add outbox flush and update broadcast_announce"
```

---

### Task 6: Add outbox flush heartbeat phase + inert-when-solo guard

**Files:**
- Modify: `odigos/core/heartbeat.py`
- Modify: `tests/test_heartbeat_announce.py`

**Step 1: Write the failing tests**

Replace `tests/test_heartbeat_announce.py`:

```python
"""Test heartbeat peer maintenance phase."""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from odigos.core.heartbeat import Heartbeat


def _build_heartbeat(**overrides):
    """Build a Heartbeat with all fields set, overridable for testing."""
    hb = Heartbeat.__new__(Heartbeat)
    hb.db = AsyncMock()
    hb.agent = AsyncMock()
    hb.channel_registry = MagicMock()
    hb.goal_store = AsyncMock()
    hb.provider = AsyncMock()
    hb._interval = 30
    hb._max_todos_per_tick = 3
    hb._idle_think_interval = 900
    hb._task = None
    hb.tracer = None
    hb.subagent_manager = None
    hb._last_idle = 0
    hb.paused = False
    hb.evolution_engine = None
    hb.strategist = None
    hb.agent_client = overrides.get("agent_client", None)
    hb._announce_interval = 60
    hb._last_announce = time.monotonic() - 120
    hb._agent_role = "personal_assistant"
    hb._agent_description = "Test agent"

    hb._fire_reminders = AsyncMock(return_value=False)
    hb._work_todos = AsyncMock(return_value=False)
    hb._deliver_subagent_results = AsyncMock(return_value=False)
    hb._idle_think = AsyncMock()
    return hb


@pytest.mark.asyncio
async def test_tick_announces_and_flushes():
    agent_client = AsyncMock()
    agent_client.broadcast_announce = AsyncMock()
    agent_client.mark_stale_peers = AsyncMock(return_value=0)
    agent_client.flush_outbox = AsyncMock(return_value=0)
    agent_client.list_peer_names = MagicMock(return_value=["Archie"])

    hb = _build_heartbeat(agent_client=agent_client)
    await hb._tick()

    agent_client.broadcast_announce.assert_called_once()
    agent_client.mark_stale_peers.assert_called_once()
    agent_client.flush_outbox.assert_called_once()


@pytest.mark.asyncio
async def test_tick_inert_when_no_peers():
    """Peer maintenance is skipped entirely when no peers exist."""
    agent_client = AsyncMock()
    agent_client.list_peer_names = MagicMock(return_value=[])
    agent_client.broadcast_announce = AsyncMock()
    agent_client.flush_outbox = AsyncMock()

    hb = _build_heartbeat(agent_client=agent_client)

    # Also mock db to return no online peers in registry
    hb.db.fetch_one = AsyncMock(return_value=None)

    await hb._tick()

    agent_client.broadcast_announce.assert_not_called()
    agent_client.flush_outbox.assert_not_called()


@pytest.mark.asyncio
async def test_tick_skips_peer_when_no_agent_client():
    """No crash when agent_client is None."""
    hb = _build_heartbeat(agent_client=None)
    await hb._tick()
    # Should complete without error
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_heartbeat_announce.py -v`
Expected: FAIL — flush_outbox not called, inert guard not implemented

**Step 3: Update _peer_maintenance() in heartbeat.py**

Replace `_peer_maintenance()`:

```python
    async def _peer_maintenance(self) -> None:
        """Phase 6: Announce self to peers, flush outbox, mark stale peers offline.

        Inert when solo: skips entirely if no peers configured and no online peers in registry.
        """
        # Inert-when-solo guard
        if not self.agent_client.list_peer_names():
            # No configured peers — check if any discovered peers are online
            online = await self.db.fetch_one(
                "SELECT 1 FROM agent_registry WHERE status = 'online' LIMIT 1"
            )
            if not online:
                return

        now = time.monotonic()
        try:
            # Announce on schedule
            if now - self._last_announce >= self._announce_interval:
                self._last_announce = now
                await self.agent_client.broadcast_announce(
                    role=self._agent_role,
                    description=self._agent_description,
                )
                await self.agent_client.mark_stale_peers()

            # Always try to flush outbox
            await self.agent_client.flush_outbox()
        except Exception:
            logger.debug("Peer maintenance failed", exc_info=True)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_heartbeat_announce.py -v`
Expected: PASS

**Step 5: Run full suite**

Run: `uv run pytest tests/ -x -q`

**Step 6: Commit**

```bash
git add odigos/core/heartbeat.py tests/test_heartbeat_announce.py
git commit -m "feat: heartbeat outbox flush phase + inert-when-solo guard"
```

---

### Task 7: Replace HTTP message endpoint with discovery announce

**Files:**
- Modify: `odigos/api/agent_message.py`
- Modify: `odigos/main.py`
- Create: `tests/test_peer_announce_api.py`

**Step 1: Write the failing tests**

Create `tests/test_peer_announce_api.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app():
    from odigos.api.agent_message import router

    app = FastAPI()

    settings = MagicMock()
    settings.api_key = "test-key"

    db = AsyncMock()
    db.fetch_one = AsyncMock(return_value=None)
    db.execute = AsyncMock()

    agent_client = AsyncMock()

    app.state.settings = settings
    app.state.db = db
    app.state.agent_client = agent_client

    app.include_router(router)
    return app, agent_client


class TestPeerAnnounce:
    def test_announce_registers_peer(self):
        app, agent_client = _make_app()
        client = TestClient(app)

        resp = client.post(
            "/api/agent/peer/announce",
            json={
                "agent_name": "Archie",
                "ws_host": "100.64.0.2",
                "ws_port": 8001,
                "role": "backend_dev",
                "description": "Backend specialist",
            },
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_announce_requires_auth(self):
        app, _ = _make_app()
        client = TestClient(app)

        resp = client.post(
            "/api/agent/peer/announce",
            json={"agent_name": "Archie", "ws_host": "100.64.0.2"},
        )
        assert resp.status_code in (401, 403)

    def test_old_message_endpoint_removed(self):
        app, _ = _make_app()
        client = TestClient(app)

        resp = client.post(
            "/api/agent/message",
            json={"from_agent": "Archie", "content": "hello"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code in (404, 405)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_peer_announce_api.py -v`
Expected: FAIL — `/api/agent/peer/announce` doesn't exist

**Step 3: Rewrite agent_message.py**

Replace the entire contents of `odigos/api/agent_message.py`:

```python
"""Peer agent discovery endpoint.

Provides POST /api/agent/peer/announce for peers to register their
WebSocket coordinates. Not used for messaging — all messaging is WS-only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from odigos.api.deps import require_api_key

router = APIRouter(
    prefix="/api/agent",
    dependencies=[Depends(require_api_key)],
)


class PeerAnnounceRequest(BaseModel):
    agent_name: str
    ws_host: str = ""
    ws_port: int = 8001
    role: str = ""
    description: str = ""
    specialty: str | None = None
    capabilities: list[str] = []


@router.post("/peer/announce")
async def peer_announce(
    body: PeerAnnounceRequest,
    request: Request,
):
    """Register a peer agent's WebSocket coordinates for future communication."""
    db = request.app.state.db
    now = datetime.now(timezone.utc).isoformat()

    existing = await db.fetch_one(
        "SELECT agent_name FROM agent_registry WHERE agent_name = ?",
        (body.agent_name,),
    )

    if existing:
        await db.execute(
            "UPDATE agent_registry SET role = ?, description = ?, specialty = ?, "
            "netbird_ip = ?, ws_port = ?, capabilities = ?, "
            "status = 'online', last_seen = ?, updated_at = ? "
            "WHERE agent_name = ?",
            (body.role, body.description, body.specialty,
             body.ws_host, body.ws_port, str(body.capabilities),
             now, now, body.agent_name),
        )
    else:
        await db.execute(
            "INSERT INTO agent_registry "
            "(agent_name, role, description, specialty, netbird_ip, ws_port, "
            "capabilities, status, last_seen, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'online', ?, ?)",
            (body.agent_name, body.role, body.description, body.specialty,
             body.ws_host, body.ws_port, str(body.capabilities),
             now, now),
        )

    return {"status": "ok", "message": f"Peer {body.agent_name} registered"}
```

**Step 4: Update main.py imports**

In `odigos/main.py`, the import `from odigos.api.agent_message import router as agent_message_router` stays the same (same module, just different endpoints now). No change needed.

**Step 5: Run tests**

Run: `uv run pytest tests/test_peer_announce_api.py -v`
Expected: PASS

**Step 6: Run full suite**

Run: `uv run pytest tests/ -x -q`
Fix any tests that reference the old `POST /api/agent/message` endpoint.

**Step 7: Commit**

```bash
git add odigos/api/agent_message.py tests/test_peer_announce_api.py
git commit -m "feat: replace HTTP message endpoint with peer announce discovery"
```

---

### Task 8: Update WebSocket endpoint for PeerEnvelope

**Files:**
- Modify: `odigos/api/agent_ws.py`
- Modify: `tests/test_ws_peer.py` (if it tests the WS endpoint)

**Step 1: Update agent_ws.py**

Read `odigos/api/agent_ws.py` and update to use `PeerEnvelope`:

```python
"""WebSocket endpoint for agent-to-agent communication.

Peer agents connect to /ws/agent to exchange PeerEnvelope messages in real-time.
Authenticated via API key in query parameter.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from odigos.core.agent_client import AgentClient, PeerEnvelope

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    token = websocket.query_params.get("token", "")
    expected = getattr(websocket.app.state, "settings", None)
    api_key = getattr(expected, "api_key", "") if expected else ""

    if not api_key or token != api_key:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    agent_client: AgentClient = websocket.app.state.agent_client
    peer_name = None
    peer_ip = websocket.client.host if websocket.client else ""

    try:
        while True:
            data = await websocket.receive_json()

            if not isinstance(data, dict) or "type" not in data:
                await websocket.send_json({"type": "error", "payload": {"message": "Invalid message format"}})
                continue

            from odigos.core.agent_client import PeerEnvelope
            msg = PeerEnvelope.from_dict(data)

            if peer_name is None:
                peer_name = msg.from_agent
                logger.info("Agent connection from %s (%s)", peer_name, peer_ip)
                # Register this WS connection for outbox flushing
                agent_client._ws_connections[peer_name] = websocket

            if msg.type == "status_ping":
                pong = PeerEnvelope(
                    from_agent=agent_client.agent_name,
                    to_agent=msg.from_agent,
                    type="status_pong",
                    payload={},
                )
                await websocket.send_json(pong.to_dict())

            await agent_client.handle_incoming(msg, peer_ip=peer_ip)

    except WebSocketDisconnect:
        logger.info("Agent %s disconnected", peer_name or "unknown")
        if peer_name and peer_name in agent_client._ws_connections:
            del agent_client._ws_connections[peer_name]
    except Exception:
        logger.warning("Agent WebSocket error", exc_info=True)
        if peer_name and peer_name in agent_client._ws_connections:
            del agent_client._ws_connections[peer_name]
```

**Step 2: Run full suite**

Run: `uv run pytest tests/ -x -q`

**Step 3: Commit**

```bash
git add odigos/api/agent_ws.py
git commit -m "feat: update WS endpoint for PeerEnvelope, register connections"
```

---

### Task 9: Update MessagePeerTool

**Files:**
- Modify: `odigos/tools/peer.py`
- Modify: `tests/test_peer_tool.py`

**Step 1: Write failing tests**

Replace `tests/test_peer_tool.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_peer_tool.py -v`
Expected: FAIL — send() call signature doesn't match, no priority param

**Step 3: Update MessagePeerTool**

Replace `odigos/tools/peer.py`:

```python
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.core.agent_client import AgentClient


class MessagePeerTool(BaseTool):
    name = "message_peer"
    description = (
        "Send a message to a peer agent. Use this to communicate, "
        "request help, share knowledge, or delegate tasks to other agents."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "peer": {
                "type": "string",
                "description": "Name of the peer agent to message",
            },
            "message": {
                "type": "string",
                "description": "The message content to send",
            },
            "message_type": {
                "type": "string",
                "description": "Type of message: message, help_request, knowledge_share, task_delegation, status",
                "default": "message",
            },
            "priority": {
                "type": "string",
                "description": "Message priority: low, normal, high",
                "default": "normal",
            },
        },
        "required": ["peer", "message"],
    }

    def __init__(self, peer_client: AgentClient) -> None:
        self.peer_client = peer_client

    async def execute(self, params: dict) -> ToolResult:
        peer = params.get("peer")
        message = params.get("message")

        if not peer:
            return ToolResult(success=False, data="", error="Missing required parameter: peer")
        if not message:
            return ToolResult(success=False, data="", error="Missing required parameter: message")

        message_type = params.get("message_type", "message")
        priority = params.get("priority", "normal")

        try:
            result = await self.peer_client.send(
                peer, payload={"content": message}, message_type=message_type, priority=priority,
            )
        except ValueError as exc:
            return ToolResult(success=False, data=str(exc), error=str(exc))

        return ToolResult(success=True, data=json.dumps(result))
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_peer_tool.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/tools/peer.py tests/test_peer_tool.py
git commit -m "feat: update MessagePeerTool for PeerEnvelope with priority"
```

---

### Task 10: Remove AgentMessage alias, update remaining references, final verification

**Files:**
- Modify: `odigos/core/agent_client.py` (remove alias)
- Modify: any files still importing `AgentMessage`
- Modify: `tests/test_peer_integration.py`, `tests/test_peer_config.py` (if they reference old types)

**Step 1: Remove the AgentMessage alias**

In `odigos/core/agent_client.py`, remove:
```python
AgentMessage = PeerEnvelope
```

**Step 2: Search for remaining AgentMessage references**

Run: `grep -r "AgentMessage" odigos/ tests/ --include="*.py"`

Update each file to import `PeerEnvelope` instead of `AgentMessage`.

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 4: Verify no dead imports**

Run: `grep -r "agent_message\|AgentMessage\|_send_http\|httpx" odigos/core/agent_client.py`
Expected: No matches for `_send_http` or `httpx`. No matches for `AgentMessage`.

**Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove AgentMessage alias, clean up all references to PeerEnvelope"
```

---

## Summary of Changes

| File | Action |
|------|--------|
| `odigos/core/agent_client.py` | Replace AgentMessage with PeerEnvelope, WS-only send, add send_response, flush_outbox, remove HTTP |
| `odigos/tools/peer.py` | Update for PeerEnvelope, add priority parameter |
| `odigos/api/agent_message.py` | Replace message endpoint with peer announce discovery |
| `odigos/api/agent_ws.py` | Update for PeerEnvelope, register WS connections |
| `odigos/core/heartbeat.py` | Add outbox flush to peer maintenance, inert-when-solo guard |
| `tests/test_agent_client.py` | Rewrite for PeerEnvelope, WS-only send, outbox tests |
| `tests/test_peer_tool.py` | Rewrite for new send signature with priority |
| `tests/test_heartbeat_announce.py` | Rewrite for outbox flush and inert guard |
| `tests/test_peer_announce_api.py` | New: announce endpoint tests |
