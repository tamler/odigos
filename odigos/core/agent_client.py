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


# Backward compatibility alias -- remove once all references are updated
AgentMessage = PeerEnvelope


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

        msg = PeerEnvelope(
            type=message_type,
            from_agent=self.agent_name,
            to_agent=peer_name,
            payload={"content": content, **(metadata or {})},
        )

        if self._db:
            await self._db.execute(
                "INSERT INTO peer_messages "
                "(message_id, direction, peer_name, message_type, content, metadata_json, status) "
                "VALUES (?, 'outbound', ?, ?, ?, ?, 'queued')",
                (msg.id, peer_name, message_type, content, json.dumps(metadata or {})),
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
                        (msg.id,),
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
                    (msg.id,),
                )
            return {"status": "error", "response": f"No HTTP URL for {peer_name} and WebSocket unavailable"}

        url = f"{peer.url.rstrip('/')}/api/agent/message"
        payload = {
            "from_agent": self.agent_name,
            "message_type": message_type,
            "content": content,
            "metadata": {**(metadata or {}), "message_id": msg.id},
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
                    (msg.id,),
                )
            return {"status": "error", "response": f"Peer returned {resp.status_code}"}

        if self._db:
            await self._db.execute(
                "UPDATE peer_messages SET status = 'delivered', delivered_at = datetime('now') "
                "WHERE message_id = ?",
                (msg.id,),
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
    ) -> PeerEnvelope:
        """Build a registry_announce message for broadcasting identity to peers."""
        return PeerEnvelope(
            type=MSG_REGISTRY_ANNOUNCE,
            from_agent=self.agent_name,
            to_agent="*",
            payload={
                "role": role,
                "description": description,
                "specialty": specialty,
                "capabilities": capabilities or [],
                "evolution_score": evolution_score,
                "allow_external_evaluation": allow_external_evaluation,
            },
        )

    async def handle_incoming(self, msg: PeerEnvelope, peer_ip: str = "") -> None:
        """Process an incoming message from a peer agent."""
        if self._db:
            await self._db.execute(
                "INSERT INTO peer_messages "
                "(message_id, direction, peer_name, message_type, content, metadata_json, status) "
                "VALUES (?, 'inbound', ?, ?, ?, ?, 'received')",
                (msg.id, msg.from_agent, msg.type, json.dumps(msg.payload), json.dumps(msg.payload)),
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

    async def _handle_announce(self, msg: PeerEnvelope, peer_ip: str) -> None:
        """Upsert agent_registry from a registry_announce message."""
        data = msg.payload
        if not isinstance(data, dict):
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

    async def _handle_ping(self, msg: PeerEnvelope) -> None:
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
                await self.send(peer_name, json.dumps(msg.payload), message_type=MSG_REGISTRY_ANNOUNCE)
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
