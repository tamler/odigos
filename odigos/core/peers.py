from __future__ import annotations

import json
import logging
import uuid
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
    def __init__(self, peers: list[PeerConfig], agent_name: str = "odigos", db=None) -> None:
        self._peers = {p.name: p for p in peers}
        self.agent_name = agent_name
        self._db = db

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

        message_id = str(uuid.uuid4())

        # Record outbound message
        if self._db:
            await self._db.execute(
                "INSERT INTO peer_messages "
                "(message_id, direction, peer_name, message_type, content, metadata_json, status) "
                "VALUES (?, 'outbound', ?, ?, ?, ?, 'queued')",
                (message_id, peer_name, message_type, content, json.dumps(metadata or {})),
            )

        url = f"{peer.url.rstrip('/')}/api/agent/message"
        payload = {
            "from_agent": self.agent_name,
            "message_type": message_type,
            "content": content,
            "metadata": {**(metadata or {}), "message_id": message_id},
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
                    (message_id,),
                )
            return {"status": "error", "response": f"Peer returned {resp.status_code}"}

        if self._db:
            await self._db.execute(
                "UPDATE peer_messages SET status = 'delivered', delivered_at = datetime('now') "
                "WHERE message_id = ?",
                (message_id,),
            )
        return resp.json()
