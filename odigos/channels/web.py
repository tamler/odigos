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
        self._connections: dict[str, set] = defaultdict(set)
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
        payload = {
            "type": "chat",
            "content": text,
            "conversation_id": conversation_id,
            "role": "assistant",
        }
        await self._send_to_connections(conversation_id, payload)

    async def broadcast_event(self, conversation_id: str, event: dict) -> None:
        if "events" not in self._subscriptions.get(conversation_id, set()):
            return
        await self._send_to_connections(conversation_id, event)

    async def broadcast_status(self, conversation_id: str, status: dict) -> None:
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
