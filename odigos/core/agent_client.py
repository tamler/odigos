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

MSG_TASK_REQUEST = "task_request"
MSG_TASK_RESPONSE = "task_response"
MSG_TASK_STREAM = "task_stream"
MSG_EVAL_REQUEST = "evaluation_request"
MSG_EVAL_RESPONSE = "evaluation_response"
MSG_REGISTRY_ANNOUNCE = "registry_announce"
MSG_STATUS_PING = "status_ping"


@dataclass
class AgentMessage:
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
    """WebSocket-primary, HTTP-fallback client for agent-to-agent communication."""

    def __init__(
        self,
        peers: list[PeerConfig],
        agent_name: str = "Odigos",
        db: Database | None = None,
    ) -> None:
        self._peers = {p.name: p for p in peers}
        self.agent_name = agent_name
        self._db = db
        self._ws_connections: dict[str, object] = {}
        self._handlers: dict[str, list] = {}

    def get_peer(self, name: str) -> PeerConfig | None:
        return self._peers.get(name)

    def list_peer_names(self) -> list[str]:
        return list(self._peers.keys())

    def has_ws_peer(self, name: str) -> bool:
        peer = self._peers.get(name)
        return bool(peer and peer.netbird_ip)

    async def send(
        self,
        peer_name: str,
        content: str,
        message_type: str = "message",
        metadata: dict | None = None,
    ) -> dict:
        """Send a message to a peer. Tries WebSocket first, falls back to HTTP."""
        peer = self._peers.get(peer_name)
        if not peer:
            raise ValueError(f"Unknown peer: {peer_name}")

        msg = AgentMessage(
            type=message_type,
            from_agent=self.agent_name,
            content=content,
            metadata=metadata or {},
        )

        if self._db:
            await self._db.execute(
                "INSERT INTO peer_messages "
                "(message_id, direction, peer_name, message_type, content, metadata_json, status) "
                "VALUES (?, 'outbound', ?, ?, ?, ?, 'queued')",
                (msg.message_id, peer_name, message_type, content, json.dumps(metadata or {})),
            )

        # Try WebSocket if we have an active connection
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

        # Fall back to HTTP
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
        """Build a registry_announce message for broadcasting identity to peers."""
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
        """Process an incoming message from a peer agent."""
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

        for handler in self._handlers.get(msg.type, []):
            try:
                await handler(msg)
            except Exception:
                logger.warning("Handler for %s failed", msg.type, exc_info=True)

    def on_message(self, message_type: str, handler) -> None:
        """Register a callback for a specific message type."""
        self._handlers.setdefault(message_type, []).append(handler)

    async def _handle_announce(self, msg: AgentMessage, peer_ip: str) -> None:
        """Upsert agent_registry from a registry_announce message."""
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
                    now, now,
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
                    now, now,
                ),
            )

    async def _handle_ping(self, msg: AgentMessage) -> None:
        """Update last_seen timestamp for a peer that sent a status ping."""
        if self._db:
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "UPDATE agent_registry SET last_seen = ?, status = 'online' WHERE agent_name = ?",
                (now, msg.from_agent),
            )

    async def broadcast_announce(self, **kwargs) -> None:
        """Send a registry_announce message to all configured peers."""
        msg = self.build_announce(**kwargs)
        for peer_name in self._peers:
            try:
                await self.send(peer_name, msg.content, message_type=MSG_REGISTRY_ANNOUNCE)
            except Exception:
                logger.debug("Failed to announce to %s", peer_name, exc_info=True)

    async def mark_stale_peers(self, stale_minutes: int = 5) -> int:
        """Mark agents as offline if not seen within stale_minutes."""
        if not self._db:
            return 0
        result = await self._db.execute(
            "UPDATE agent_registry SET status = 'offline' "
            "WHERE status = 'online' AND last_seen < datetime('now', ?)",
            (f"-{stale_minutes} minutes",),
        )
        return result if isinstance(result, int) else 0
