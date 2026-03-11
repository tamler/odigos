# Phase 2b: Agent Networking, Cross-Agent Evaluation, Specialist Spawning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build WebSocket-based agent-to-agent communication over NetBird WireGuard mesh, cross-agent evaluation routing, and specialist agent spawning with deployment automation.

**Architecture:** Upgrade the existing HTTP-only `PeerClient` to an `AgentClient` with persistent WebSocket connections for real-time delegation and streaming. Add heartbeat-based peer status tracking. Build cross-agent evaluation that routes to qualified specialist peers. Create a spawning pipeline that generates config + seed identity for new specialist agents and deploys them via SSH/Docker.

**Tech Stack:** Python 3.12, websockets, aiosqlite, FastAPI, existing PeerClient/tool infrastructure

**Reference:** Read `docs/plans/2026-03-11-phase2-evolution-agents-dashboard-design.md` for full design rationale.

---

### Task 1: Database Migration — WebSocket Message Types + Deploy Targets

**Files:**
- Create: `migrations/017_phase2b.sql`

**Step 1: Write the migration**

```sql
-- Add new message types for WebSocket protocol
-- Existing peer_messages table already handles message storage
-- Add response tracking for task delegation
ALTER TABLE peer_messages ADD COLUMN response_to TEXT;
ALTER TABLE peer_messages ADD COLUMN task_status TEXT DEFAULT NULL;

-- Deploy targets for specialist spawning
CREATE TABLE IF NOT EXISTS deploy_targets (
    name TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT 'docker',
    ssh_user TEXT DEFAULT 'root',
    ssh_key_path TEXT,
    status TEXT DEFAULT 'available',
    last_used_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Track spawned specialists
CREATE TABLE IF NOT EXISTS spawned_agents (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    description TEXT,
    deploy_target TEXT NOT NULL,
    proposal_id TEXT,
    config_snapshot TEXT,
    status TEXT DEFAULT 'deploying',
    deployed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (deploy_target) REFERENCES deploy_targets(name)
);
CREATE INDEX IF NOT EXISTS idx_spawned_status ON spawned_agents(status);
```

**Step 2: Verify migration applies**

Run: `cd /Users/jacob/Projects/odigos && python3 -c "import asyncio; from odigos.db import Database; asyncio.run(Database(':memory:', migrations_dir='migrations').initialize()); print('Migration OK')"`
Expected: `Migration OK`

**Step 3: Commit**

```bash
git add migrations/017_phase2b.sql
git commit -m "feat: add deploy targets and spawned agents tables, extend peer messages

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Deploy Targets Config

**Files:**
- Modify: `odigos/config.py`
- Create: `tests/test_config_deploy_targets.py`

**Step 1: Write the failing test**

Create `tests/test_config_deploy_targets.py`:

```python
"""Test deploy target config fields."""
from odigos.config import DeployTargetConfig, Settings


def test_deploy_target_config():
    target = DeployTargetConfig(
        name="vps-1", host="100.64.0.1", method="docker",
        ssh_user="deployer", ssh_key_path="/home/deployer/.ssh/id_ed25519"
    )
    assert target.name == "vps-1"
    assert target.host == "100.64.0.1"
    assert target.method == "docker"
    assert target.ssh_user == "deployer"


def test_deploy_target_defaults():
    target = DeployTargetConfig(name="test", host="10.0.0.1")
    assert target.method == "docker"
    assert target.ssh_user == "root"
    assert target.ssh_key_path is None


def test_settings_has_deploy_targets():
    """Settings should accept deploy_targets list."""
    # Just verify the field exists and defaults to empty
    s = Settings(llm_api_key="test")
    assert s.deploy_targets == []
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_config_deploy_targets.py -v`
Expected: FAIL (DeployTargetConfig doesn't exist)

**Step 3: Update config.py**

Read `odigos/config.py` first. Add the new config class before `Settings`:

```python
class DeployTargetConfig(BaseModel):
    """Configuration for a VPS deployment target."""
    name: str
    host: str
    method: str = "docker"
    ssh_user: str = "root"
    ssh_key_path: Optional[str] = None
```

Add to `Settings`:
```python
deploy_targets: list[DeployTargetConfig] = []
```

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_config_deploy_targets.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add odigos/config.py tests/test_config_deploy_targets.py
git commit -m "feat: add DeployTargetConfig for specialist spawning targets

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: AgentClient — WebSocket Upgrade of PeerClient

**Files:**
- Create: `odigos/core/agent_client.py`
- Create: `tests/test_agent_client.py`

**Context:** The existing `PeerClient` in `odigos/core/peers.py` uses HTTP-only communication via httpx. The `AgentClient` wraps or replaces it with WebSocket support for real-time communication. WebSocket is primary, HTTP is fallback. Each peer connection is a persistent WebSocket to `ws://{netbird_ip}:{ws_port}/ws/agent`.

The message protocol uses JSON with a `type` field:
- `task_request` — Delegate a task to a peer
- `task_response` — Final response from peer
- `task_stream` — Streaming progress/partial results
- `evaluation_request` — Ask a peer to evaluate an action
- `evaluation_response` — Evaluation result from peer
- `registry_announce` — Peer announcing/updating its profile
- `status_ping` — Heartbeat keepalive

**Step 1: Write the failing test**

Create `tests/test_agent_client.py`:

```python
"""Tests for the AgentClient WebSocket communication layer."""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from odigos.core.agent_client import AgentClient, AgentMessage
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


def test_agent_message_serialization():
    msg = AgentMessage(
        type="task_request",
        from_agent="Odigos",
        content="Summarize this document",
        metadata={"task_id": "123"},
    )
    data = msg.to_dict()
    assert data["type"] == "task_request"
    assert data["from_agent"] == "Odigos"
    assert data["content"] == "Summarize this document"
    assert "message_id" in data

    # Round-trip
    restored = AgentMessage.from_dict(data)
    assert restored.type == msg.type
    assert restored.from_agent == msg.from_agent


@pytest.mark.asyncio
async def test_send_falls_back_to_http(db, mock_peers):
    """When no WebSocket connection exists and peer has url, fall back to HTTP."""
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
    """Messages should be recorded in peer_messages table."""
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
    """announce_self should prepare registry_announce messages."""
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)
    msg = client.build_announce(
        role="personal_assistant",
        description="Jacob's AI",
        capabilities=["search", "code"],
    )
    assert msg.type == "registry_announce"
    assert msg.from_agent == "Odigos"
    assert "personal_assistant" in msg.content


@pytest.mark.asyncio
async def test_handle_incoming_announce(db, mock_peers):
    """Incoming registry_announce should upsert agent_registry."""
    client = AgentClient(peers=mock_peers, agent_name="Odigos", db=db)

    msg = AgentMessage(
        type="registry_announce",
        from_agent="Archie",
        content=json.dumps({
            "role": "backend_dev",
            "description": "Backend specialist",
            "specialty": "coding",
            "capabilities": ["code_execute"],
            "evolution_score": 7.5,
            "allow_external_evaluation": True,
        }),
    )
    await client.handle_incoming(msg, peer_ip="100.64.0.2")

    row = await db.fetch_one("SELECT * FROM agent_registry WHERE agent_name = 'Archie'")
    assert row is not None
    assert row["role"] == "backend_dev"
    assert row["status"] == "online"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_agent_client.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

Create `odigos/core/agent_client.py`:

```python
"""AgentClient: WebSocket-primary agent-to-agent communication.

Upgrades the HTTP-only PeerClient with persistent WebSocket connections
for real-time delegation and streaming over a NetBird WireGuard mesh.
Falls back to HTTP when WebSocket is unavailable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from odigos.config import PeerConfig
    from odigos.db import Database

logger = logging.getLogger(__name__)

# WebSocket message types
MSG_TASK_REQUEST = "task_request"
MSG_TASK_RESPONSE = "task_response"
MSG_TASK_STREAM = "task_stream"
MSG_EVAL_REQUEST = "evaluation_request"
MSG_EVAL_RESPONSE = "evaluation_response"
MSG_REGISTRY_ANNOUNCE = "registry_announce"
MSG_STATUS_PING = "status_ping"


@dataclass
class AgentMessage:
    """A message in the agent-to-agent protocol."""
    type: str
    from_agent: str
    content: str
    metadata: dict = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "from_agent": self.from_agent,
            "content": self.content,
            "metadata": self.metadata,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AgentMessage:
        return cls(
            type=data["type"],
            from_agent=data["from_agent"],
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            message_id=data.get("message_id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )


class AgentClient:
    """Manages communication with peer agents.

    WebSocket is primary for peers with netbird_ip.
    HTTP is fallback for peers with only url configured.
    """

    def __init__(
        self,
        peers: list[PeerConfig],
        agent_name: str = "Odigos",
        db: Database | None = None,
    ) -> None:
        self._peers = {p.name: p for p in peers}
        self.agent_name = agent_name
        self._db = db
        self._ws_connections: dict[str, object] = {}  # peer_name -> websocket
        self._handlers: dict[str, list] = {}  # message_type -> [callbacks]

    def get_peer(self, name: str) -> PeerConfig | None:
        return self._peers.get(name)

    def list_peer_names(self) -> list[str]:
        return list(self._peers.keys())

    def has_ws_peer(self, name: str) -> bool:
        """Check if a peer has WebSocket (NetBird) config."""
        peer = self._peers.get(name)
        return bool(peer and peer.netbird_ip)

    async def send(
        self,
        peer_name: str,
        content: str,
        message_type: str = "message",
        metadata: dict | None = None,
    ) -> dict:
        """Send a message to a peer. Uses WebSocket if available, HTTP fallback."""
        peer = self._peers.get(peer_name)
        if not peer:
            raise ValueError(f"Unknown peer: {peer_name}")

        msg = AgentMessage(
            type=message_type,
            from_agent=self.agent_name,
            content=content,
            metadata=metadata or {},
        )

        # Record outbound message
        if self._db:
            await self._db.execute(
                "INSERT INTO peer_messages "
                "(message_id, direction, peer_name, message_type, content, metadata_json, status) "
                "VALUES (?, 'outbound', ?, ?, ?, ?, 'queued')",
                (msg.message_id, peer_name, message_type, content, json.dumps(metadata or {})),
            )

        # Try WebSocket first if peer has netbird_ip
        ws = self._ws_connections.get(peer_name)
        if ws:
            try:
                await ws.send(json.dumps(msg.to_dict()))
                if self._db:
                    await self._db.execute(
                        "UPDATE peer_messages SET status = 'delivered', delivered_at = datetime('now') "
                        "WHERE message_id = ?",
                        (msg.message_id,),
                    )
                return {"status": "sent", "via": "websocket"}
            except Exception:
                logger.warning("WebSocket send to %s failed, trying HTTP", peer_name)
                del self._ws_connections[peer_name]

        # HTTP fallback
        if not peer.url:
            if self._db:
                await self._db.execute(
                    "UPDATE peer_messages SET status = 'failed' WHERE message_id = ?",
                    (msg.message_id,),
                )
            return {"status": "error", "response": f"No HTTP URL for {peer_name} and WebSocket unavailable"}

        url = f"{peer.url.rstrip('/')}/api/agent/message"
        payload = {
            "from_agent": self.agent_name,
            "message_type": message_type,
            "content": content,
            "metadata": {**(metadata or {}), "message_id": msg.message_id},
        }
        headers = {}
        if peer.api_key:
            headers["Authorization"] = f"Bearer {peer.api_key}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            if self._db:
                await self._db.execute(
                    "UPDATE peer_messages SET status = 'failed' WHERE message_id = ?",
                    (msg.message_id,),
                )
            return {"status": "error", "response": f"Peer returned {resp.status_code}"}

        if self._db:
            await self._db.execute(
                "UPDATE peer_messages SET status = 'delivered', delivered_at = datetime('now') "
                "WHERE message_id = ?",
                (msg.message_id,),
            )
        return resp.json()

    def build_announce(
        self,
        role: str = "",
        description: str = "",
        specialty: str | None = None,
        capabilities: list[str] | None = None,
        evolution_score: float | None = None,
        allow_external_evaluation: bool = False,
    ) -> AgentMessage:
        """Build a registry_announce message for broadcasting to peers."""
        return AgentMessage(
            type=MSG_REGISTRY_ANNOUNCE,
            from_agent=self.agent_name,
            content=json.dumps({
                "role": role,
                "description": description,
                "specialty": specialty,
                "capabilities": capabilities or [],
                "evolution_score": evolution_score,
                "allow_external_evaluation": allow_external_evaluation,
            }),
        )

    async def handle_incoming(self, msg: AgentMessage, peer_ip: str = "") -> None:
        """Process an incoming agent message."""
        if self._db:
            await self._db.execute(
                "INSERT INTO peer_messages "
                "(message_id, direction, peer_name, message_type, content, metadata_json, status) "
                "VALUES (?, 'inbound', ?, ?, ?, ?, 'received')",
                (msg.message_id, msg.from_agent, msg.type, msg.content, json.dumps(msg.metadata)),
            )

        if msg.type == MSG_REGISTRY_ANNOUNCE:
            await self._handle_announce(msg, peer_ip)
        elif msg.type == MSG_STATUS_PING:
            await self._handle_ping(msg)

        # Dispatch to registered handlers
        for handler in self._handlers.get(msg.type, []):
            try:
                await handler(msg)
            except Exception:
                logger.warning("Handler for %s failed", msg.type, exc_info=True)

    def on_message(self, message_type: str, handler) -> None:
        """Register a handler for a specific message type."""
        self._handlers.setdefault(message_type, []).append(handler)

    async def _handle_announce(self, msg: AgentMessage, peer_ip: str) -> None:
        """Update agent registry from a peer announcement."""
        try:
            data = json.loads(msg.content)
        except (json.JSONDecodeError, TypeError):
            return

        if not self._db:
            return

        existing = await self._db.fetch_one(
            "SELECT agent_name FROM agent_registry WHERE agent_name = ?",
            (msg.from_agent,),
        )

        now = datetime.now(timezone.utc).isoformat()
        if existing:
            await self._db.execute(
                "UPDATE agent_registry SET role = ?, description = ?, specialty = ?, "
                "netbird_ip = ?, capabilities = ?, evolution_score = ?, "
                "allow_external_evaluation = ?, status = 'online', last_seen = ?, updated_at = ? "
                "WHERE agent_name = ?",
                (
                    data.get("role", ""),
                    data.get("description", ""),
                    data.get("specialty"),
                    peer_ip,
                    json.dumps(data.get("capabilities", [])),
                    data.get("evolution_score"),
                    1 if data.get("allow_external_evaluation") else 0,
                    now,
                    now,
                    msg.from_agent,
                ),
            )
        else:
            await self._db.execute(
                "INSERT INTO agent_registry "
                "(agent_name, role, description, specialty, netbird_ip, capabilities, "
                "evolution_score, allow_external_evaluation, status, last_seen, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'online', ?, ?)",
                (
                    msg.from_agent,
                    data.get("role", ""),
                    data.get("description", ""),
                    data.get("specialty"),
                    peer_ip,
                    json.dumps(data.get("capabilities", [])),
                    data.get("evolution_score"),
                    1 if data.get("allow_external_evaluation") else 0,
                    now,
                    now,
                ),
            )

    async def _handle_ping(self, msg: AgentMessage) -> None:
        """Update last_seen for a peer."""
        if self._db:
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "UPDATE agent_registry SET last_seen = ?, status = 'online' WHERE agent_name = ?",
                (now, msg.from_agent),
            )

    async def broadcast_announce(self, **kwargs) -> None:
        """Send registry_announce to all peers."""
        msg = self.build_announce(**kwargs)
        for peer_name in self._peers:
            try:
                await self.send(peer_name, msg.content, message_type=MSG_REGISTRY_ANNOUNCE)
            except Exception:
                logger.debug("Failed to announce to %s", peer_name, exc_info=True)

    async def mark_stale_peers(self, stale_minutes: int = 5) -> int:
        """Mark peers as offline if not seen recently."""
        if not self._db:
            return 0
        result = await self._db.execute(
            "UPDATE agent_registry SET status = 'offline' "
            "WHERE status = 'online' AND last_seen < datetime('now', ?)",
            (f"-{stale_minutes} minutes",),
        )
        return result if isinstance(result, int) else 0
```

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_agent_client.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add odigos/core/agent_client.py tests/test_agent_client.py
git commit -m "feat: add AgentClient with WebSocket-primary, HTTP-fallback peer communication

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: WebSocket Server Endpoint for Agent-to-Agent Communication

**Files:**
- Create: `odigos/api/agent_ws.py`
- Create: `tests/test_agent_ws.py`

**Context:** Each Odigos instance needs a WebSocket endpoint that peer agents connect to. This is separate from the dashboard WebSocket in `ws.py` — this is for agent-to-agent traffic on the mesh.

**Step 1: Write the failing test**

Create `tests/test_agent_ws.py`:

```python
"""Tests for agent-to-agent WebSocket endpoint."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from odigos.api.agent_ws import router as agent_ws_router


@pytest_asyncio.fixture
async def app():
    from odigos.db import Database
    from odigos.core.agent_client import AgentClient

    db = Database(":memory:", migrations_dir="migrations")
    await db.initialize()

    app = FastAPI()
    app.state.db = db
    app.state.agent_client = AgentClient(peers=[], agent_name="TestAgent", db=db)
    app.state.settings = MagicMock()
    app.state.settings.api_key = "test-key"
    app.include_router(agent_ws_router)
    return app


def test_agent_ws_rejects_without_auth(app):
    """WebSocket connections without valid API key should be rejected."""
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/agent"):
            pass


def test_agent_ws_accepts_with_auth(app):
    """WebSocket connections with valid API key should be accepted."""
    client = TestClient(app)
    with client.websocket_connect("/ws/agent?token=test-key") as ws:
        # Send a ping
        ws.send_json({
            "type": "status_ping",
            "from_agent": "Archie",
            "content": "",
        })
        # Should get a pong back
        response = ws.receive_json()
        assert response["type"] == "status_pong"
```

**Step 2: Run to verify failure**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_agent_ws.py -v`

**Step 3: Write the implementation**

Create `odigos/api/agent_ws.py`:

```python
"""WebSocket endpoint for agent-to-agent communication.

Peer agents connect to /ws/agent to exchange messages in real-time.
Authenticated via API key in query parameter.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

if TYPE_CHECKING:
    from odigos.core.agent_client import AgentClient, AgentMessage

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    """Handle incoming agent-to-agent WebSocket connections."""
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
                await websocket.send_json({"type": "error", "content": "Invalid message format"})
                continue

            from odigos.core.agent_client import AgentMessage
            msg = AgentMessage.from_dict(data)

            # Track which peer this connection belongs to
            if peer_name is None:
                peer_name = msg.from_agent
                logger.info("Agent connection from %s (%s)", peer_name, peer_ip)

            # Respond to pings immediately
            if msg.type == "status_ping":
                await websocket.send_json({
                    "type": "status_pong",
                    "from_agent": agent_client.agent_name,
                    "content": "",
                })

            # Process through agent client
            await agent_client.handle_incoming(msg, peer_ip=peer_ip)

    except WebSocketDisconnect:
        logger.info("Agent %s disconnected", peer_name or "unknown")
    except Exception:
        logger.warning("Agent WebSocket error", exc_info=True)
    finally:
        if peer_name and websocket.application_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass
```

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_agent_ws.py -v`
Expected: All tests PASS

**Step 5: Mount in main.py**

Read `odigos/main.py` and add:
```python
from odigos.api.agent_ws import router as agent_ws_router
app.include_router(agent_ws_router)
app.state.agent_client = agent_client  # Use the AgentClient instead of PeerClient
```

**Step 6: Commit**

```bash
git add odigos/api/agent_ws.py tests/test_agent_ws.py odigos/main.py
git commit -m "feat: add agent-to-agent WebSocket endpoint for mesh communication

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Cross-Agent Evaluation Routing

**Files:**
- Modify: `odigos/core/evaluator.py`
- Create: `tests/test_cross_agent_eval.py`

**Context:** When the evaluator scores an action, it checks the agent registry for a qualified peer whose specialty matches the action's task_type. If found and the peer is online with `allow_external_evaluation`, it sends an `evaluation_request` via the AgentClient instead of running local LLM evaluation. Falls back to local if no qualified peer or peer unavailable.

**Step 1: Write the failing test**

Create `tests/test_cross_agent_eval.py`:

```python
"""Tests for cross-agent evaluation routing."""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from odigos.core.evaluator import Evaluator
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.fallback_model = "test-fallback"
    return provider


@pytest.mark.asyncio
async def test_find_qualified_evaluator(db, mock_provider):
    """Should find a qualified peer evaluator for a task type."""
    evaluator = Evaluator(db=db, provider=mock_provider)

    # Register a qualified peer
    await db.execute(
        "INSERT INTO agent_registry (agent_name, role, specialty, status, "
        "evolution_score, allow_external_evaluation) VALUES (?, ?, ?, ?, ?, ?)",
        ("CodeBot", "backend_dev", "coding", "online", 8.0, 1),
    )

    result = await evaluator.find_qualified_evaluator("coding")
    assert result is not None
    assert result["agent_name"] == "CodeBot"


@pytest.mark.asyncio
async def test_no_qualified_evaluator_offline(db, mock_provider):
    """Should not return offline peers."""
    evaluator = Evaluator(db=db, provider=mock_provider)

    await db.execute(
        "INSERT INTO agent_registry (agent_name, role, specialty, status, "
        "evolution_score, allow_external_evaluation) VALUES (?, ?, ?, ?, ?, ?)",
        ("CodeBot", "backend_dev", "coding", "offline", 8.0, 1),
    )

    result = await evaluator.find_qualified_evaluator("coding")
    assert result is None


@pytest.mark.asyncio
async def test_no_qualified_evaluator_low_score(db, mock_provider):
    """Should not return peers with low evolution score."""
    evaluator = Evaluator(db=db, provider=mock_provider)

    await db.execute(
        "INSERT INTO agent_registry (agent_name, role, specialty, status, "
        "evolution_score, allow_external_evaluation) VALUES (?, ?, ?, ?, ?, ?)",
        ("CodeBot", "backend_dev", "coding", "online", 5.0, 1),
    )

    result = await evaluator.find_qualified_evaluator("coding")
    assert result is None


@pytest.mark.asyncio
async def test_no_qualified_evaluator_not_opted_in(db, mock_provider):
    """Should not return peers that haven't opted in."""
    evaluator = Evaluator(db=db, provider=mock_provider)

    await db.execute(
        "INSERT INTO agent_registry (agent_name, role, specialty, status, "
        "evolution_score, allow_external_evaluation) VALUES (?, ?, ?, ?, ?, ?)",
        ("CodeBot", "backend_dev", "coding", "online", 8.0, 0),
    )

    result = await evaluator.find_qualified_evaluator("coding")
    assert result is None
```

**Step 2: Run to verify failure**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_cross_agent_eval.py -v`
Expected: FAIL (`find_qualified_evaluator` doesn't exist)

**Step 3: Add find_qualified_evaluator to Evaluator**

Read `odigos/core/evaluator.py` first. Add this method to the `Evaluator` class:

```python
    async def find_qualified_evaluator(self, task_type: str) -> dict | None:
        """Find a qualified peer to evaluate actions of this task type.

        Requirements:
        - Peer specialty matches task_type
        - Peer is online
        - Peer has allow_external_evaluation = 1
        - Peer has evolution_score > 7.0
        """
        row = await self.db.fetch_one(
            "SELECT * FROM agent_registry "
            "WHERE specialty = ? AND status = 'online' "
            "AND allow_external_evaluation = 1 AND evolution_score > 7.0 "
            "ORDER BY evolution_score DESC LIMIT 1",
            (task_type,),
        )
        return dict(row) if row else None
```

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_cross_agent_eval.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add odigos/core/evaluator.py tests/test_cross_agent_eval.py
git commit -m "feat: add cross-agent evaluation routing to find qualified peer evaluators

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Specialist Spawning — Config Generator

**Files:**
- Create: `odigos/core/spawner.py`
- Create: `tests/test_spawner.py`

**Context:** When a specialization proposal is approved (or user requests), the spawner generates a complete config + seed identity for a new specialist agent. It does NOT handle deployment (Task 7) — just generates the files.

**Step 1: Write the failing test**

Create `tests/test_spawner.py`:

```python
"""Tests for specialist agent spawning."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.spawner import Spawner
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.fallback_model = "test-fallback"
    provider.complete = AsyncMock(return_value=AsyncMock(
        content="You are a Python backend specialist focused on writing clean, efficient server-side code."
    ))
    return provider


@pytest.mark.asyncio
async def test_generate_config(db, mock_provider):
    spawner = Spawner(db=db, provider=mock_provider, parent_name="Odigos")

    config = await spawner.generate_config(
        agent_name="CodeBot",
        role="backend_dev",
        description="Python backend specialist",
        specialty="coding",
        deploy_target="vps-1",
    )

    assert config["agent"]["name"] == "CodeBot"
    assert config["agent"]["role"] == "backend_dev"
    assert config["agent"]["parent"] == "Odigos"
    assert config["agent"]["description"] == "Python backend specialist"


@pytest.mark.asyncio
async def test_generate_seed_identity(db, mock_provider):
    spawner = Spawner(db=db, provider=mock_provider, parent_name="Odigos")

    identity = await spawner.generate_seed_identity(
        role="backend_dev",
        description="Python backend specialist",
        specialty="coding",
    )

    assert len(identity) > 0
    mock_provider.complete.assert_called_once()


@pytest.mark.asyncio
async def test_gather_seed_knowledge(db, mock_provider):
    """Should gather relevant memories filtered by task type."""
    spawner = Spawner(db=db, provider=mock_provider, parent_name="Odigos")

    # Insert some evaluations to simulate knowledge
    for i in range(5):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, improvement_signal, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "coding", 7.0 + i * 0.5, f"Insight {i}"),
        )
    for i in range(3):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, created_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "scheduling", 8.0),
        )

    knowledge = await spawner.gather_seed_knowledge("coding")
    assert len(knowledge) > 0
    # Should only include coding evaluations
    assert all("coding" in k.get("task_type", "") for k in knowledge)


@pytest.mark.asyncio
async def test_record_spawn(db, mock_provider):
    spawner = Spawner(db=db, provider=mock_provider, parent_name="Odigos")

    # Insert a deploy target
    await db.execute(
        "INSERT INTO deploy_targets (name, host, method) VALUES (?, ?, ?)",
        ("vps-1", "100.64.0.1", "docker"),
    )

    spawn_id = await spawner.record_spawn(
        agent_name="CodeBot",
        role="backend_dev",
        description="Python backend specialist",
        deploy_target="vps-1",
        config_snapshot={"agent": {"name": "CodeBot"}},
    )

    row = await db.fetch_one("SELECT * FROM spawned_agents WHERE id = ?", (spawn_id,))
    assert row is not None
    assert row["agent_name"] == "CodeBot"
    assert row["status"] == "deploying"
```

**Step 2: Run to verify failure**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_spawner.py -v`

**Step 3: Write the implementation**

Create `odigos/core/spawner.py`:

```python
"""Spawner: generates config and seed identity for specialist agents.

Handles the planning phase of specialist creation. Actual deployment
is handled separately by the deploy tool.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class Spawner:
    """Generates specialist agent configurations and seed content."""

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        parent_name: str = "Odigos",
    ) -> None:
        self.db = db
        self.provider = provider
        self.parent_name = parent_name

    async def generate_config(
        self,
        agent_name: str,
        role: str,
        description: str,
        specialty: str | None = None,
        deploy_target: str = "",
    ) -> dict:
        """Generate a config.yaml structure for a new specialist agent."""
        return {
            "agent": {
                "name": agent_name,
                "role": role,
                "description": description,
                "parent": self.parent_name,
                "allow_external_evaluation": False,
            },
            "llm": {
                "base_url": "https://openrouter.ai/api/v1",
                "default_model": "anthropic/claude-sonnet-4",
                "fallback_model": "google/gemini-2.0-flash-001",
            },
            "peers": [
                {
                    "name": self.parent_name,
                    "netbird_ip": "",  # Filled at deploy time
                    "ws_port": 8001,
                }
            ],
            "_deploy_target": deploy_target,
            "_specialty": specialty,
        }

    async def generate_seed_identity(
        self,
        role: str,
        description: str,
        specialty: str | None = None,
    ) -> str:
        """Generate a seed identity.md prompt section for the specialist."""
        prompt = (
            f"Write a brief identity statement (2-3 sentences) for an AI agent with:\n"
            f"- Role: {role}\n"
            f"- Description: {description}\n"
            f"- Specialty: {specialty or 'general'}\n\n"
            f"The identity should define the agent's core purpose and approach. "
            f"Write in second person ('You are...'). Be specific, not generic."
        )
        response = await self.provider.complete(
            [{"role": "user", "content": prompt}],
            model=getattr(self.provider, "fallback_model", None),
            max_tokens=150,
            temperature=0.4,
        )
        return response.content.strip()

    async def gather_seed_knowledge(
        self,
        specialty: str,
        limit: int = 20,
    ) -> list[dict]:
        """Gather relevant improvement signals from evaluations matching the specialty."""
        rows = await self.db.fetch_all(
            "SELECT task_type, overall_score, improvement_signal, created_at "
            "FROM evaluations "
            "WHERE task_type = ? AND improvement_signal IS NOT NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (specialty, limit),
        )
        return [dict(r) for r in rows]

    async def record_spawn(
        self,
        agent_name: str,
        role: str,
        description: str,
        deploy_target: str,
        config_snapshot: dict,
        proposal_id: str | None = None,
    ) -> str:
        """Record a spawn attempt in the database."""
        spawn_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO spawned_agents "
            "(id, agent_name, role, description, deploy_target, proposal_id, config_snapshot, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'deploying')",
            (spawn_id, agent_name, role, description, deploy_target, proposal_id, json.dumps(config_snapshot)),
        )
        return spawn_id

    async def spawn(
        self,
        agent_name: str,
        role: str,
        description: str,
        specialty: str | None = None,
        deploy_target: str = "",
        proposal_id: str | None = None,
    ) -> dict:
        """Full spawn pipeline: config + identity + knowledge + record.

        Returns the spawn record with all generated artifacts.
        Does NOT deploy — that's handled by the deploy tool.
        """
        config = await self.generate_config(
            agent_name=agent_name,
            role=role,
            description=description,
            specialty=specialty,
            deploy_target=deploy_target,
        )

        identity = await self.generate_seed_identity(
            role=role, description=description, specialty=specialty,
        )

        knowledge = await self.gather_seed_knowledge(specialty or role)

        spawn_id = await self.record_spawn(
            agent_name=agent_name,
            role=role,
            description=description,
            deploy_target=deploy_target,
            config_snapshot=config,
            proposal_id=proposal_id,
        )

        return {
            "spawn_id": spawn_id,
            "config": config,
            "identity": identity,
            "seed_knowledge": knowledge,
        }
```

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_spawner.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add odigos/core/spawner.py tests/test_spawner.py
git commit -m "feat: add Spawner for generating specialist agent configs and seed content

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Spawn API Endpoint + Agents API Enhancement

**Files:**
- Modify: `odigos/api/agents.py`
- Create: `tests/test_api_agents_spawn.py`

**Context:** Add POST /api/agents/spawn endpoint that triggers the spawner. Also add GET /api/agents/spawned to list spawned agents.

**Step 1: Write the failing test**

Create `tests/test_api_agents_spawn.py`:

```python
"""Tests for agent spawn API endpoints."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.agents import router as agents_router
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def app(db):
    app = FastAPI()
    app.state.db = db
    app.state.settings = SimpleNamespace(api_key="test-key")

    mock_spawner = AsyncMock()
    mock_spawner.spawn = AsyncMock(return_value={
        "spawn_id": "spawn-123",
        "config": {"agent": {"name": "CodeBot"}},
        "identity": "You are a coding specialist.",
        "seed_knowledge": [],
    })
    app.state.spawner = mock_spawner
    app.include_router(agents_router)
    return app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers["Authorization"] = "Bearer test-key"
        yield c


@pytest.mark.asyncio
async def test_spawn_agent(client):
    resp = await client.post("/api/agents/spawn", json={
        "agent_name": "CodeBot",
        "role": "backend_dev",
        "description": "Python backend specialist",
        "specialty": "coding",
        "deploy_target": "vps-1",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["spawn_id"] == "spawn-123"


@pytest.mark.asyncio
async def test_list_spawned_agents(client, db):
    # Insert a deploy target and spawned agent
    await db.execute(
        "INSERT INTO deploy_targets (name, host, method) VALUES (?, ?, ?)",
        ("vps-1", "100.64.0.1", "docker"),
    )
    await db.execute(
        "INSERT INTO spawned_agents (id, agent_name, role, deploy_target, status) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "CodeBot", "backend_dev", "vps-1", "running"),
    )
    resp = await client.get("/api/agents/spawned")
    assert resp.status_code == 200
    assert len(resp.json()["agents"]) == 1


@pytest.mark.asyncio
async def test_list_deploy_targets(client, db):
    await db.execute(
        "INSERT INTO deploy_targets (name, host, method) VALUES (?, ?, ?)",
        ("vps-1", "100.64.0.1", "docker"),
    )
    resp = await client.get("/api/agents/deploy-targets")
    assert resp.status_code == 200
    assert len(resp.json()["targets"]) == 1
```

**Step 2: Run to verify failure**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_api_agents_spawn.py -v`

**Step 3: Update agents.py**

Read `odigos/api/agents.py` first. Add these endpoints:

```python
from pydantic import BaseModel


class SpawnRequest(BaseModel):
    agent_name: str
    role: str
    description: str
    specialty: str = ""
    deploy_target: str = ""
    proposal_id: str = ""


@router.post("/agents/spawn")
async def spawn_agent(req: SpawnRequest, request: Request):
    """Spawn a new specialist agent."""
    spawner = request.app.state.spawner
    result = await spawner.spawn(
        agent_name=req.agent_name,
        role=req.role,
        description=req.description,
        specialty=req.specialty or None,
        deploy_target=req.deploy_target,
        proposal_id=req.proposal_id or None,
    )
    return result


@router.get("/agents/spawned")
async def list_spawned(db: Database = Depends(get_db)):
    """List all spawned specialist agents."""
    rows = await db.fetch_all(
        "SELECT * FROM spawned_agents ORDER BY created_at DESC"
    )
    return {"agents": [dict(r) for r in rows]}


@router.get("/agents/deploy-targets")
async def list_deploy_targets(db: Database = Depends(get_db)):
    """List available deployment targets."""
    rows = await db.fetch_all(
        "SELECT * FROM deploy_targets ORDER BY name"
    )
    return {"targets": [dict(r) for r in rows]}
```

You'll need to add `from fastapi import Request` to the imports (and `from pydantic import BaseModel`).

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_api_agents_spawn.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add odigos/api/agents.py tests/test_api_agents_spawn.py
git commit -m "feat: add spawn, spawned agents, and deploy targets API endpoints

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Wire AgentClient + Spawner into Main + Heartbeat Announce

**Files:**
- Modify: `odigos/main.py`
- Modify: `odigos/core/heartbeat.py`
- Create: `tests/test_heartbeat_announce.py`

**Context:** Replace the existing PeerClient usage with AgentClient. Initialize the Spawner. Add heartbeat announce broadcasting so peers stay aware of each other.

**Step 1: Write the failing test**

Create `tests/test_heartbeat_announce.py`:

```python
"""Test heartbeat announces agent to peers."""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_tick_announces_periodically():
    from odigos.core.heartbeat import Heartbeat

    heartbeat = Heartbeat.__new__(Heartbeat)
    heartbeat.db = AsyncMock()
    heartbeat.agent = AsyncMock()
    heartbeat.channel_registry = MagicMock()
    heartbeat.goal_store = AsyncMock()
    heartbeat.provider = AsyncMock()
    heartbeat._interval = 30
    heartbeat._max_todos_per_tick = 3
    heartbeat._idle_think_interval = 900
    heartbeat._task = None
    heartbeat.tracer = None
    heartbeat.subagent_manager = None
    heartbeat._last_idle = 0
    heartbeat.paused = False
    heartbeat.evolution_engine = None
    heartbeat.strategist = None
    heartbeat.agent_client = AsyncMock()
    heartbeat.agent_client.broadcast_announce = AsyncMock()
    heartbeat.agent_client.mark_stale_peers = AsyncMock(return_value=0)
    heartbeat._announce_interval = 60
    heartbeat._last_announce = 0
    heartbeat._agent_role = "personal_assistant"
    heartbeat._agent_description = "Test agent"

    heartbeat._fire_reminders = AsyncMock(return_value=False)
    heartbeat._work_todos = AsyncMock(return_value=False)
    heartbeat._deliver_subagent_results = AsyncMock(return_value=False)
    heartbeat._idle_think = AsyncMock()

    await heartbeat._tick()

    # Should have broadcast announce
    heartbeat.agent_client.broadcast_announce.assert_called_once()
    heartbeat.agent_client.mark_stale_peers.assert_called_once()
```

**Step 2: Run to verify failure**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_heartbeat_announce.py -v`

**Step 3: Update heartbeat.py**

Read `odigos/core/heartbeat.py`. Add:

1. Import `time` (already imported) and add to TYPE_CHECKING:
```python
from odigos.core.agent_client import AgentClient
```

2. Add parameters to `__init__` (after `strategist`):
```python
        agent_client: AgentClient | None = None,
        agent_role: str = "",
        agent_description: str = "",
        announce_interval: int = 60,
```

3. Store in init body:
```python
        self.agent_client = agent_client
        self._agent_role = agent_role
        self._agent_description = agent_description
        self._announce_interval = announce_interval
        self._last_announce: float = 0
```

4. Add to `_tick()` — after Phase 5 (evolution), add Phase 6:
```python
        # Phase 6: Peer announce + stale check
        if self.agent_client:
            await self._peer_maintenance()
```

5. Add new method:
```python
    async def _peer_maintenance(self) -> None:
        """Phase 6: Announce self to peers and mark stale peers offline."""
        now = time.monotonic()
        try:
            if now - self._last_announce >= self._announce_interval:
                self._last_announce = now
                await self.agent_client.broadcast_announce(
                    role=self._agent_role,
                    description=self._agent_description,
                )
                await self.agent_client.mark_stale_peers()
        except Exception:
            logger.debug("Peer maintenance failed", exc_info=True)
```

**Step 4: Update main.py**

Read `odigos/main.py`. Replace PeerClient initialization with AgentClient:

```python
from odigos.core.agent_client import AgentClient
from odigos.core.spawner import Spawner

agent_client = AgentClient(
    peers=settings.peers,
    agent_name=settings.agent.name,
    db=_db,
)

spawner = Spawner(
    db=_db,
    provider=_router,
    parent_name=settings.agent.name,
)
```

Pass to Heartbeat:
```python
agent_client=agent_client,
agent_role=settings.agent.role,
agent_description=settings.agent.description,
```

And set on app.state:
```python
app.state.agent_client = agent_client
app.state.spawner = spawner
```

**Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_heartbeat_announce.py tests/test_heartbeat_strategist.py tests/test_heartbeat_evolution.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add odigos/core/heartbeat.py odigos/main.py tests/test_heartbeat_announce.py
git commit -m "feat: wire AgentClient + Spawner into main, add heartbeat peer announce

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 9: Enhanced Agents Dashboard — Spawn Form + Connection Status

**Files:**
- Modify: `dashboard/src/pages/AgentsPage.tsx`

**Context:** The basic agents page from Phase 2a shows agent cards. Now add: a "Spawn Specialist" form, spawned agents list, and deploy targets display.

**Step 1: Update AgentsPage.tsx**

Read `dashboard/src/pages/AgentsPage.tsx`. Replace with an enhanced version that adds:

1. A "Spawn Specialist" button that opens a form dialog
2. The form takes: name, role, description, specialty, deploy target (dropdown)
3. A "Spawned Agents" section below the registry
4. Deploy targets loaded from `/api/agents/deploy-targets`

```tsx
import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Users, Wifi, WifiOff, Clock, Plus, Server } from 'lucide-react'

interface Agent {
  agent_name: string
  role: string
  description: string
  specialty: string | null
  status: string
  last_seen: string | null
  evolution_score: number | null
  netbird_ip: string
}

interface SpawnedAgent {
  id: string
  agent_name: string
  role: string
  description: string
  deploy_target: string
  status: string
  deployed_at: string | null
  created_at: string
}

interface DeployTarget {
  name: string
  host: string
  method: string
  status: string
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [spawned, setSpawned] = useState<SpawnedAgent[]>([])
  const [targets, setTargets] = useState<DeployTarget[]>([])
  const [showSpawnForm, setShowSpawnForm] = useState(false)
  const [spawnForm, setSpawnForm] = useState({
    agent_name: '', role: '', description: '', specialty: '', deploy_target: '',
  })

  const loadAll = useCallback(async () => {
    try {
      const [a, s, t] = await Promise.all([
        get<{ agents: Agent[] }>('/api/agents'),
        get<{ agents: SpawnedAgent[] }>('/api/agents/spawned'),
        get<{ targets: DeployTarget[] }>('/api/agents/deploy-targets'),
      ])
      setAgents(a.agents)
      setSpawned(s.agents)
      setTargets(t.targets)
    } catch {
      toast.error('Failed to load agent data')
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  async function handleSpawn() {
    if (!spawnForm.agent_name || !spawnForm.role || !spawnForm.description) {
      toast.error('Name, role, and description are required')
      return
    }
    try {
      await post('/api/agents/spawn', spawnForm)
      toast.success(`Specialist ${spawnForm.agent_name} spawn initiated`)
      setShowSpawnForm(false)
      setSpawnForm({ agent_name: '', role: '', description: '', specialty: '', deploy_target: '' })
      loadAll()
    } catch {
      toast.error('Failed to spawn agent')
    }
  }

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-8">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Users className="h-5 w-5" /> Agent Network
          </h1>
          <Button variant="outline" size="sm" onClick={() => setShowSpawnForm(!showSpawnForm)}>
            <Plus className="h-3 w-3 mr-1" /> Spawn Specialist
          </Button>
        </div>

        {/* Spawn form */}
        {showSpawnForm && (
          <div className="p-4 rounded-lg border border-border/40 bg-muted/30 space-y-3">
            <h2 className="text-sm font-medium">Create Specialist Agent</h2>
            <div className="grid grid-cols-2 gap-3">
              <input
                className="px-3 py-2 text-sm rounded border border-border/40 bg-background"
                placeholder="Agent name"
                value={spawnForm.agent_name}
                onChange={(e) => setSpawnForm({ ...spawnForm, agent_name: e.target.value })}
              />
              <input
                className="px-3 py-2 text-sm rounded border border-border/40 bg-background"
                placeholder="Role (e.g. backend_dev)"
                value={spawnForm.role}
                onChange={(e) => setSpawnForm({ ...spawnForm, role: e.target.value })}
              />
              <input
                className="px-3 py-2 text-sm rounded border border-border/40 bg-background"
                placeholder="Specialty tag"
                value={spawnForm.specialty}
                onChange={(e) => setSpawnForm({ ...spawnForm, specialty: e.target.value })}
              />
              <select
                className="px-3 py-2 text-sm rounded border border-border/40 bg-background"
                value={spawnForm.deploy_target}
                onChange={(e) => setSpawnForm({ ...spawnForm, deploy_target: e.target.value })}
              >
                <option value="">Deploy target...</option>
                {targets.map((t) => (
                  <option key={t.name} value={t.name}>{t.name} ({t.host})</option>
                ))}
              </select>
            </div>
            <input
              className="w-full px-3 py-2 text-sm rounded border border-border/40 bg-background"
              placeholder="Description (1-2 sentences)"
              value={spawnForm.description}
              onChange={(e) => setSpawnForm({ ...spawnForm, description: e.target.value })}
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={handleSpawn}>Create</Button>
              <Button variant="ghost" size="sm" onClick={() => setShowSpawnForm(false)}>Cancel</Button>
            </div>
          </div>
        )}

        {/* Registered agents */}
        {agents.length === 0 && !spawned.length && (
          <div className="text-center py-16 text-muted-foreground">
            <Users className="h-8 w-8 mx-auto mb-3 opacity-50" />
            <p>No agents registered yet.</p>
            <p className="text-xs mt-1">Agents will appear here when they join the mesh.</p>
          </div>
        )}

        <div className="grid gap-4">
          {agents.map((a) => (
            <div key={a.agent_name} className="p-4 rounded-lg border border-border/40 bg-muted/30">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{a.agent_name}</span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">{a.role}</span>
                    {a.specialty && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">{a.specialty}</span>
                    )}
                  </div>
                  {a.description && <p className="text-sm text-muted-foreground mt-1">{a.description}</p>}
                </div>
                <div className="flex items-center gap-2">
                  {a.status === 'online' ? (
                    <Wifi className="h-4 w-4 text-green-500" />
                  ) : (
                    <WifiOff className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-xs text-muted-foreground">{a.status}</span>
                </div>
              </div>
              <div className="flex gap-6 mt-3 text-xs text-muted-foreground">
                {a.netbird_ip && <span>IP: {a.netbird_ip}</span>}
                {a.evolution_score !== null && <span>Score: {a.evolution_score.toFixed(1)}</span>}
                {a.last_seen && (
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {new Date(a.last_seen).toLocaleString()}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Spawned agents */}
        {spawned.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-sm font-medium flex items-center gap-2">
              <Server className="h-4 w-4" /> Spawned Specialists
            </h2>
            {spawned.map((s) => (
              <div key={s.id} className="p-3 rounded-lg border border-border/40 bg-muted/30">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-medium text-sm">{s.agent_name}</span>
                    <span className="text-xs text-muted-foreground ml-2">{s.role}</span>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    s.status === 'running' ? 'bg-green-500/10 text-green-500' :
                    s.status === 'deploying' ? 'bg-yellow-500/10 text-yellow-500' :
                    'bg-muted text-muted-foreground'
                  }`}>{s.status}</span>
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  Target: {s.deploy_target} {s.deployed_at && `| Deployed: ${new Date(s.deployed_at).toLocaleString()}`}
                </div>
              </div>
            ))}
          </section>
        )}
      </div>
    </div>
  )
}
```

**Step 2: Verify build**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add dashboard/src/pages/AgentsPage.tsx
git commit -m "feat: enhance Agents page with spawn form, spawned agents list, deploy targets

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 10: Full Verification

**Step 1: Run all Phase 2b Python tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_config_deploy_targets.py tests/test_agent_client.py tests/test_agent_ws.py tests/test_cross_agent_eval.py tests/test_spawner.py tests/test_api_agents_spawn.py tests/test_heartbeat_announce.py -v`
Expected: All tests PASS

**Step 2: Run all Phase 1 + 2a tests (regression)**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_strategist.py tests/test_config_agent_identity.py tests/test_auto_title.py tests/test_api_evolution.py tests/test_heartbeat_strategist.py tests/test_heartbeat_evolution.py tests/test_evolution.py tests/test_evolution_integration.py tests/test_checkpoint.py tests/test_evaluator.py tests/test_section_registry.py tests/test_prompt_builder_dynamic.py -v`
Expected: All 43 tests PASS

**Step 3: Verify all imports**

Run: `cd /Users/jacob/Projects/odigos && python3 -c "from odigos.core.agent_client import AgentClient; from odigos.core.spawner import Spawner; from odigos.api.agent_ws import router; print('All imports OK')"`
Expected: `All imports OK`

**Step 4: Verify migration chain**

Run: `cd /Users/jacob/Projects/odigos && python3 -c "import asyncio; from odigos.db import Database; asyncio.run(Database(':memory:', migrations_dir='migrations').initialize()); print('All migrations OK')"`
Expected: `All migrations OK`

**Step 5: Verify dashboard builds**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npm run build`
Expected: Build succeeds

**Step 6: Final commit if anything remains**

```bash
git status
```
