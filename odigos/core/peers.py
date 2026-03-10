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
            return {"status": "error", "response": f"Peer returned {resp.status_code}"}
        return resp.json()
