"""AgentClient: WebSocket-only agent-to-agent communication.

Persistent WebSocket connections for real-time delegation and streaming
over a NetBird WireGuard mesh. Messages are queued to an outbox when
the WebSocket connection is unavailable.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.core.content_filter import ContentFilter

if TYPE_CHECKING:
    from odigos.config import PeerConfig
    from odigos.db import Database

logger = logging.getLogger(__name__)

_content_filter = ContentFilter()

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


class AgentClient:
    """WebSocket-only client for agent-to-agent communication with outbox queuing."""

    def __init__(
        self,
        peers: list[PeerConfig],
        agent_name: str,
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
            # Try to resolve from agent_registry (dynamically discovered peers)
            if self._db:
                row = await self._db.fetch_one(
                    "SELECT netbird_ip, ws_port FROM agent_registry "
                    "WHERE agent_name = ? AND status = 'online'",
                    (peer_name,),
                )
                if row and row["netbird_ip"]:
                    self.add_discovered_peer(peer_name, row["netbird_ip"], row["ws_port"] or 8001)
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

    def build_announce(
        self,
        role: str = "",
        description: str = "",
        specialty: str | None = None,
        capabilities: list[str] | None = None,
        evolution_score: float | None = None,
        allow_external_evaluation: bool = False,
        ws_port: int = 8001,
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
                "ws_port": ws_port,
            },
        )

    async def handle_incoming(self, msg: PeerEnvelope, peer_ip: str = "") -> None:
        """Process an incoming message from a peer agent.

        All inbound content is scanned for prompt injection before being
        stored or routed to handlers. High-risk messages are rejected.
        """
        # Validate recipient
        if msg.to_agent not in (self.agent_name, "*", ""):
            logger.debug("Ignoring message for %s (we are %s)", msg.to_agent, self.agent_name)
            return

        # Prompt injection scan on payload content
        scan_text = json.dumps(msg.payload) if isinstance(msg.payload, dict) else str(msg.payload)
        filter_result = _content_filter.scan(scan_text)
        if filter_result.risk_level == "high":
            logger.warning(
                "REJECTED peer message from %s: high-risk prompt injection detected (%s)",
                msg.from_agent, ", ".join(filter_result.matched_patterns),
            )
            if self._db:
                await self._db.execute(
                    "INSERT INTO peer_messages "
                    "(message_id, direction, peer_name, message_type, content, metadata_json, status, response_to) "
                    "VALUES (?, 'inbound', ?, ?, ?, ?, 'rejected', ?)",
                    (msg.id, msg.from_agent, msg.type, json.dumps(msg.payload),
                     json.dumps({"rejected_reason": "prompt_injection", "patterns": filter_result.matched_patterns}),
                     msg.correlation_id),
                )
            return

        if filter_result.is_suspicious:
            logger.info(
                "Peer message from %s flagged (risk: %s, patterns: %s) -- allowing with annotation",
                msg.from_agent, filter_result.risk_level, ", ".join(filter_result.matched_patterns),
            )
            # Annotate the payload so the agent knows it was flagged
            msg.payload["_injection_warning"] = {
                "risk_level": filter_result.risk_level,
                "matched_patterns": filter_result.matched_patterns,
            }

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

    def on_message(self, message_type: str, handler) -> None:
        """Register a callback for a specific message type."""
        self._handlers.setdefault(message_type, []).append(handler)

    def add_discovered_peer(self, name: str, netbird_ip: str, ws_port: int = 8001) -> None:
        """Dynamically add a peer discovered via announce (not pre-configured)."""
        if name in self._peers or name == self.agent_name:
            return

        from odigos.config import PeerConfig

        self._peers[name] = PeerConfig(name=name, netbird_ip=netbird_ip, ws_port=ws_port)
        logger.info("Discovered peer %s at %s:%d via announce", name, netbird_ip, ws_port)

    async def _handle_announce(self, msg: PeerEnvelope, peer_ip: str) -> None:
        """Upsert agent_registry and auto-discover peer from a registry_announce message."""
        data = msg.payload
        if not isinstance(data, dict):
            return

        if not self._db:
            return

        ws_port = data.get("ws_port", 8001)

        existing = await self._db.fetch_one(
            "SELECT agent_name FROM agent_registry WHERE agent_name = ?",
            (msg.from_agent,),
        )

        now = datetime.now(timezone.utc).isoformat()
        if existing:
            await self._db.execute(
                "UPDATE agent_registry SET role = ?, description = ?, specialty = ?, "
                "netbird_ip = ?, ws_port = ?, capabilities = ?, evolution_score = ?, "
                "allow_external_evaluation = ?, status = 'online', last_seen = ?, updated_at = ? "
                "WHERE agent_name = ?",
                (
                    data.get("role", ""),
                    data.get("description", ""),
                    data.get("specialty"),
                    peer_ip,
                    ws_port,
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
                "(agent_name, role, description, specialty, netbird_ip, ws_port, capabilities, "
                "evolution_score, allow_external_evaluation, status, last_seen, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'online', ?, ?)",
                (
                    msg.from_agent,
                    data.get("role", ""),
                    data.get("description", ""),
                    data.get("specialty"),
                    peer_ip,
                    ws_port,
                    json.dumps(data.get("capabilities", [])),
                    data.get("evolution_score"),
                    1 if data.get("allow_external_evaluation") else 0,
                    now, now,
                ),
            )

        # Bidirectional discovery: add announcing agent as a peer so we can message it back
        if peer_ip:
            self.add_discovered_peer(msg.from_agent, peer_ip, ws_port)

    async def _handle_ping(self, msg: PeerEnvelope) -> None:
        """Update last_seen timestamp for a peer that sent a status ping."""
        if self._db:
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "UPDATE agent_registry SET last_seen = ?, status = 'online' WHERE agent_name = ?",
                (now, msg.from_agent),
            )

    async def broadcast_announce(self, **kwargs) -> None:
        """Send a registry_announce message to all known peers (configured + discovered)."""
        env = self.build_announce(**kwargs)
        peer_names = set(self._peers.keys())

        # Also announce to peers we've discovered but haven't configured
        if self._db:
            rows = await self._db.fetch_all(
                "SELECT agent_name, netbird_ip, ws_port FROM agent_registry "
                "WHERE status = 'online' AND agent_name != ?",
                (self.agent_name,),
            )
            for row in rows:
                name = row["agent_name"]
                if name not in peer_names and row["netbird_ip"]:
                    self.add_discovered_peer(name, row["netbird_ip"], row["ws_port"] or 8001)
                    peer_names.add(name)

        for peer_name in peer_names:
            if peer_name == self.agent_name:
                continue
            try:
                await self.send(peer_name, payload=env.payload, message_type=MSG_REGISTRY_ANNOUNCE)
            except Exception:
                logger.debug("Failed to announce to %s", peer_name, exc_info=True)

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

    async def get_unprocessed_inbound(self, limit: int = 10) -> list[dict]:
        """Fetch inbound peer messages that haven't been processed yet.

        Returns messages with status 'received' (not yet acted on by the agent).
        Excludes registry_announce and status_ping which are handled automatically.
        """
        if not self._db:
            return []
        rows = await self._db.fetch_all(
            "SELECT message_id, peer_name, message_type, content, created_at, response_to "
            "FROM peer_messages "
            "WHERE direction = 'inbound' AND status = 'received' "
            "AND message_type NOT IN ('registry_announce', 'status_ping') "
            "ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    async def mark_processed(self, message_id: str) -> None:
        """Mark an inbound message as processed."""
        if self._db:
            await self._db.execute(
                "UPDATE peer_messages SET status = 'processed' WHERE message_id = ?",
                (message_id,),
            )
