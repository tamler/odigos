# Agent-to-Agent Communication Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable agents to communicate with trusted peers via a `message_peer` tool, with peer config, a REST endpoint for receiving messages, and WebSocket protocol support for real-time agent communication.

**Architecture:** Peers are declared in config.yaml. A `PeerClient` handles outbound HTTP/WS communication. The `message_peer` tool wraps PeerClient for agent use. Inbound messages arrive via `POST /api/agent/message` and are processed through the existing agent pipeline. All peer interactions are visible in the user's conversation.

**Tech Stack:** FastAPI (existing), httpx (already installed) for outbound HTTP, existing WebSocket infrastructure, existing tool/config framework.

---

## Context for the Implementer

**Config** (`odigos/config.py`): Uses pydantic `Settings` with nested config classes. Add `peers` list.

**Tool registration:** Tools are registered in `odigos/tools/registry.py` via `ToolRegistry`. Each tool extends `BaseTool` from `odigos/tools/base.py` with `name`, `description`, `parameters_schema`, and `async execute(params) -> ToolResult`.

**Agent pipeline:** `agent.handle_message(UniversalMessage)` processes messages through the full executor/reflector pipeline. For peer messages, use channel="peer" and conversation_id="peer:{peer_name}".

**Existing patterns:** Check `odigos/tools/` for examples of tool implementations (e.g., `odigos/tools/search.py`).

---

### Task 1: Peer Config

**Files:**
- Modify: `odigos/config.py` — add PeerConfig and peers list
- Test: `tests/test_peer_config.py`

**Step 1: Write the failing test**

```python
# tests/test_peer_config.py
import pytest
from odigos.config import PeerConfig, Settings


class TestPeerConfig:
    def test_peer_config_fields(self):
        peer = PeerConfig(name="sarah-agent", url="https://sarah.example.com", api_key="secret")
        assert peer.name == "sarah-agent"
        assert peer.url == "https://sarah.example.com"
        assert peer.api_key == "secret"

    def test_settings_default_empty_peers(self):
        # Settings with minimal required fields should have empty peers
        s = Settings(
            telegram_bot_token="fake",
            openrouter_api_key="fake",
        )
        assert s.peers == []

    def test_settings_with_peers(self):
        s = Settings(
            telegram_bot_token="fake",
            openrouter_api_key="fake",
            peers=[PeerConfig(name="bob", url="http://bob.local", api_key="key")],
        )
        assert len(s.peers) == 1
        assert s.peers[0].name == "bob"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_peer_config.py -v`
Expected: FAIL (ImportError: cannot import name 'PeerConfig')

**Step 3: Write minimal implementation**

Add to `odigos/config.py`:

```python
class PeerConfig(BaseModel):
    """Configuration for a trusted peer agent."""
    name: str
    url: str
    api_key: str = ""
```

Add to the `Settings` class:
```python
peers: list[PeerConfig] = []
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_peer_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/config.py tests/test_peer_config.py
git commit -m "feat(peers): add peer agent configuration"
```

---

### Task 2: PeerClient — Outbound Communication

**Files:**
- Create: `odigos/core/peers.py`
- Test: `tests/test_peer_client.py`

**Step 1: Write the failing test**

```python
# tests/test_peer_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from odigos.core.peers import PeerClient, PeerMessage


class TestPeerMessage:
    def test_message_fields(self):
        msg = PeerMessage(
            from_agent="my-agent",
            message_type="message",
            content="Hello peer",
        )
        assert msg.from_agent == "my-agent"
        assert msg.message_type == "message"
        assert msg.content == "Hello peer"

    def test_message_with_metadata(self):
        msg = PeerMessage(
            from_agent="my-agent",
            message_type="knowledge_share",
            content="Entity data",
            metadata={"entity_id": "e1"},
        )
        assert msg.metadata["entity_id"] == "e1"


class TestPeerClient:
    @pytest.fixture
    def peers(self):
        from odigos.config import PeerConfig
        return [
            PeerConfig(name="sarah", url="http://sarah.local:8000", api_key="sarah-key"),
            PeerConfig(name="bob", url="http://bob.local:8000", api_key="bob-key"),
        ]

    @pytest.fixture
    def client(self, peers):
        return PeerClient(peers=peers, agent_name="my-agent")

    def test_get_peer(self, client):
        peer = client.get_peer("sarah")
        assert peer is not None
        assert peer.url == "http://sarah.local:8000"

    def test_get_unknown_peer(self, client):
        assert client.get_peer("unknown") is None

    def test_list_peers(self, client):
        names = client.list_peer_names()
        assert "sarah" in names
        assert "bob" in names

    async def test_send_message(self, client):
        with patch("odigos.core.peers.httpx.AsyncClient") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"response": "Got it!", "status": "ok"}
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            result = await client.send("sarah", "Hello Sarah!")
            assert result["response"] == "Got it!"
            mock_client_instance.post.assert_called_once()
            call_args = mock_client_instance.post.call_args
            assert "sarah.local" in call_args[0][0]
            assert call_args[1]["headers"]["Authorization"] == "Bearer sarah-key"

    async def test_send_to_unknown_peer_raises(self, client):
        with pytest.raises(ValueError, match="Unknown peer"):
            await client.send("unknown", "Hello?")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_peer_client.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# odigos/core/peers.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from odigos.config import PeerConfig

logger = logging.getLogger(__name__)


@dataclass
class PeerMessage:
    from_agent: str
    message_type: str  # message, help_request, knowledge_share, task_delegation, status
    content: str
    metadata: dict = field(default_factory=dict)


class PeerClient:
    """Handles outbound communication with trusted peer agents."""

    def __init__(self, peers: list[PeerConfig], agent_name: str = "odigos") -> None:
        self._peers = {p.name: p for p in peers}
        self.agent_name = agent_name

    def get_peer(self, name: str) -> PeerConfig | None:
        return self._peers.get(name)

    def list_peer_names(self) -> list[str]:
        return list(self._peers.keys())

    async def send(
        self,
        peer_name: str,
        content: str,
        message_type: str = "message",
        metadata: dict | None = None,
    ) -> dict:
        peer = self._peers.get(peer_name)
        if not peer:
            raise ValueError(f"Unknown peer: {peer_name}")

        url = f"{peer.url.rstrip('/')}/api/agent/message"
        payload = {
            "from_agent": self.agent_name,
            "message_type": message_type,
            "content": content,
            "metadata": metadata or {},
        }
        headers = {}
        if peer.api_key:
            headers["Authorization"] = f"Bearer {peer.api_key}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            logger.warning("Peer %s returned %d: %s", peer_name, resp.status_code, resp.text[:200])
            return {"status": "error", "response": f"Peer returned {resp.status_code}"}

        return resp.json()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_peer_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/core/peers.py tests/test_peer_client.py
git commit -m "feat(peers): add PeerClient for outbound peer communication"
```

---

### Task 3: message_peer Tool

**Files:**
- Create: `odigos/tools/peer.py`
- Test: `tests/test_peer_tool.py`

**Step 1: Write the failing test**

```python
# tests/test_peer_tool.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from odigos.tools.peer import MessagePeerTool


class TestMessagePeerTool:
    @pytest.fixture
    def peer_client(self):
        client = MagicMock()
        client.list_peer_names.return_value = ["sarah", "bob"]
        client.send = AsyncMock(return_value={"response": "Got it!", "status": "ok"})
        return client

    @pytest.fixture
    def tool(self, peer_client):
        return MessagePeerTool(peer_client=peer_client)

    def test_tool_metadata(self, tool):
        assert tool.name == "message_peer"
        assert "peer" in tool.description.lower()

    async def test_send_message(self, tool, peer_client):
        result = await tool.execute({"peer": "sarah", "message": "Hello!"})
        assert result.success
        assert "Got it!" in result.data
        peer_client.send.assert_called_once_with(
            "sarah", "Hello!", message_type="message", metadata=None,
        )

    async def test_missing_peer_param(self, tool):
        result = await tool.execute({"message": "Hello!"})
        assert not result.success

    async def test_missing_message_param(self, tool):
        result = await tool.execute({"peer": "sarah"})
        assert not result.success

    async def test_unknown_peer(self, tool, peer_client):
        peer_client.send = AsyncMock(side_effect=ValueError("Unknown peer: unknown"))
        result = await tool.execute({"peer": "unknown", "message": "Hello?"})
        assert not result.success
        assert "unknown" in result.error.lower() or "Unknown" in result.error

    async def test_message_type_param(self, tool, peer_client):
        result = await tool.execute({
            "peer": "sarah",
            "message": "Can you help with X?",
            "message_type": "help_request",
        })
        assert result.success
        peer_client.send.assert_called_once_with(
            "sarah", "Can you help with X?", message_type="help_request", metadata=None,
        )
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_peer_tool.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

First, read `odigos/tools/base.py` to understand the BaseTool interface and ToolResult.

```python
# odigos/tools/peer.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.core.peers import PeerClient

logger = logging.getLogger(__name__)


class MessagePeerTool(BaseTool):
    """Send a message to a trusted peer agent."""

    name = "message_peer"
    description = (
        "Send a message to a trusted peer agent. "
        "Use this to ask peers questions, request help, share knowledge, or delegate tasks."
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
                "enum": ["message", "help_request", "knowledge_share", "task_delegation"],
                "description": "Type of message (default: message)",
            },
        },
        "required": ["peer", "message"],
    }

    def __init__(self, peer_client: PeerClient) -> None:
        self.peer_client = peer_client

    async def execute(self, params: dict) -> ToolResult:
        peer = params.get("peer")
        message = params.get("message")
        message_type = params.get("message_type", "message")

        if not peer:
            return ToolResult(success=False, data="", error="Missing 'peer' parameter")
        if not message:
            return ToolResult(success=False, data="", error="Missing 'message' parameter")

        try:
            result = await self.peer_client.send(
                peer, message, message_type=message_type, metadata=None,
            )
        except ValueError as e:
            return ToolResult(success=False, data="", error=str(e))
        except Exception as e:
            logger.warning("Peer communication failed: %s", e)
            return ToolResult(success=False, data="", error=f"Failed to reach peer: {e}")

        response_text = result.get("response", "No response from peer")
        return ToolResult(success=True, data=response_text)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_peer_tool.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/tools/peer.py tests/test_peer_tool.py
git commit -m "feat(peers): add message_peer tool"
```

---

### Task 4: Inbound Peer Message Endpoint

**Files:**
- Create: `odigos/api/agent_message.py`
- Test: `tests/test_api_agent_message.py`

**Step 1: Write the failing test**

```python
# tests/test_api_agent_message.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.agent_message import router


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.handle_message = AsyncMock(return_value="I'll look into that!")
    return agent


@pytest.fixture
def app(mock_agent):
    a = FastAPI()
    a.state.agent = mock_agent
    a.state.settings = type("S", (), {"api_key": ""})()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestAgentMessageEndpoint:
    async def test_receive_peer_message(self, client, mock_agent):
        resp = await client.post("/api/agent/message", json={
            "from_agent": "sarah-agent",
            "message_type": "message",
            "content": "Do you know about Project X?",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "look into" in data["response"].lower() or len(data["response"]) > 0

        mock_agent.handle_message.assert_called_once()
        msg = mock_agent.handle_message.call_args[0][0]
        assert msg.channel == "peer"
        assert "sarah-agent" in msg.sender

    async def test_missing_content(self, client):
        resp = await client.post("/api/agent/message", json={
            "from_agent": "sarah-agent",
            "message_type": "message",
        })
        assert resp.status_code == 422

    async def test_help_request_type(self, client, mock_agent):
        resp = await client.post("/api/agent/message", json={
            "from_agent": "bob",
            "message_type": "help_request",
            "content": "How do I do X?",
        })
        assert resp.status_code == 200
        msg = mock_agent.handle_message.call_args[0][0]
        assert msg.metadata.get("message_type") == "help_request"

    async def test_auth_required_when_configured(self):
        a = FastAPI()
        a.state.agent = MagicMock()
        a.state.settings = type("S", (), {"api_key": "secret"})()
        a.include_router(router)
        async with AsyncClient(transport=ASGITransport(app=a), base_url="http://test") as c:
            resp = await c.post("/api/agent/message", json={
                "from_agent": "sarah",
                "message_type": "message",
                "content": "Hello",
            })
            assert resp.status_code == 401
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_agent_message.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# odigos/api/agent_message.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from odigos.api.deps import get_agent, require_api_key
from odigos.channels.base import UniversalMessage

router = APIRouter(prefix="/api/agent", dependencies=[Depends(require_api_key)])


class AgentMessageRequest(BaseModel):
    from_agent: str
    message_type: str = "message"
    content: str = Field(..., min_length=1)
    metadata: dict = {}


@router.post("/message")
async def receive_agent_message(body: AgentMessageRequest, agent=Depends(get_agent)):
    msg = UniversalMessage(
        id=str(uuid.uuid4()),
        channel="peer",
        sender=body.from_agent,
        content=f"[{body.message_type} from {body.from_agent}]: {body.content}",
        timestamp=datetime.now(timezone.utc),
        metadata={
            "chat_id": body.from_agent,
            "message_type": body.message_type,
            "peer_metadata": body.metadata,
        },
    )

    response = await agent.handle_message(msg)
    return {"status": "ok", "response": response}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_agent_message.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/api/agent_message.py tests/test_api_agent_message.py
git commit -m "feat(peers): add inbound peer message endpoint"
```

---

### Task 5: Wire PeerClient and Tool into main.py

**Files:**
- Modify: `odigos/main.py` — create PeerClient, register message_peer tool, mount agent_message router
- Test: `tests/test_peer_integration.py`

**Step 1: Write the failing test**

```python
# tests/test_peer_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient


class TestPeerEndpointMounted:
    async def test_agent_message_endpoint_exists(self):
        from odigos.main import app

        app.state.agent = MagicMock()
        app.state.agent.handle_message = AsyncMock(return_value="ok")
        app.state.settings = type("S", (), {"api_key": ""})()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/agent/message", json={
                "from_agent": "test-peer",
                "message_type": "message",
                "content": "ping",
            })
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_peer_integration.py -v`
Expected: FAIL (404)

**Step 3: Wire into main.py**

Add imports:
```python
from odigos.api.agent_message import router as agent_message_router
from odigos.core.peers import PeerClient
from odigos.tools.peer import MessagePeerTool
```

Add `app.include_router(agent_message_router)` with other router includes.

In the lifespan, after settings are loaded and before tool_registry is built:
```python
peer_client = PeerClient(peers=settings.peers, agent_name="odigos")
```

After tool_registry is created, register the tool:
```python
if peer_client.list_peer_names():
    tool_registry.register(MessagePeerTool(peer_client=peer_client))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_peer_integration.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All pass

**Step 6: Commit**

```bash
git add odigos/main.py tests/test_peer_integration.py
git commit -m "feat(peers): wire PeerClient, message_peer tool, and inbound endpoint into main app"
```
