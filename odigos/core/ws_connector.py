"""Outgoing WebSocket connection manager for agent-to-agent mesh.

Proactively connects to configured peers on startup, authenticates,
and maintains persistent connections with reconnect and heartbeat.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.config import PeerConfig
    from odigos.core.agent_client import AgentClient

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # seconds between pings
MAX_BACKOFF = 60  # max reconnect delay in seconds


class WSConnector:
    """Manages outgoing WebSocket connections to configured peers."""

    def __init__(
        self,
        agent_client: AgentClient,
        agent_name: str,
        peers: list[PeerConfig],
    ) -> None:
        self._agent_client = agent_client
        self._agent_name = agent_name
        self._peers = [p for p in peers if p.netbird_ip]
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    async def start(self) -> None:
        """Start connection tasks for all peers with IP addresses."""
        self._running = True
        for peer in self._peers:
            self._tasks[peer.name] = asyncio.create_task(
                self._connect_loop(peer),
                name=f"ws-connect-{peer.name}",
            )
        if self._peers:
            logger.info("WSConnector started for %d peer(s)", len(self._peers))

    async def stop(self) -> None:
        """Cancel all connection tasks and clean up."""
        self._running = False
        for name, task in self._tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("WSConnector stopped")

    async def _connect_loop(self, peer: PeerConfig) -> None:
        """Connect to a peer, reconnect on failure with exponential backoff."""
        backoff = 1.0
        while self._running:
            try:
                await self._connect_to_peer(peer)
                backoff = 1.0  # reset on successful connection that ran for a while
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._running:
                    break
                logger.warning(
                    "Connection to %s failed: %s. Retry in %.0fs",
                    peer.name, e, backoff,
                )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

    async def _connect_to_peer(self, peer: PeerConfig) -> None:
        """Establish and maintain a single WebSocket connection to a peer."""
        import websockets

        port = peer.ws_port or 8001
        uri = f"ws://{peer.netbird_ip}:{port}/ws/agent"

        async with websockets.connect(uri, open_timeout=10, close_timeout=5) as ws:
            # Step 1: Authenticate with the peer's API key
            await ws.send(json.dumps({"type": "auth", "token": peer.api_key}))

            # Step 2: Wait for auth_ok
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                auth_response = json.loads(raw)
                if auth_response.get("type") == "error":
                    raise ConnectionRefusedError(
                        f"Auth rejected by {peer.name}: {auth_response.get('payload', {}).get('message', 'unknown')}"
                    )
                if auth_response.get("type") == "auth_ok":
                    remote_name = auth_response.get("agent_name", peer.name)
                    logger.info("Authenticated with %s (remote: %s)", peer.name, remote_name)
            except asyncio.TimeoutError:
                raise ConnectionError(f"Auth timeout from {peer.name}")

            # Step 3: Identify ourselves via announce
            announce = self._agent_client.build_announce()
            await ws.send(json.dumps(announce.to_dict()))

            # Step 4: Register connection for outbound messages
            self._agent_client._ws_connections[peer.name] = ws
            logger.info("Connected to peer %s at %s:%d", peer.name, peer.netbird_ip, port)

            # Step 5: Flush any queued messages
            flushed = await self._agent_client.flush_outbox()
            if flushed:
                logger.info("Flushed %d queued messages to %s", flushed, peer.name)

            # Step 6: Message loop with heartbeat
            try:
                await self._message_loop(ws, peer)
            finally:
                if peer.name in self._agent_client._ws_connections:
                    del self._agent_client._ws_connections[peer.name]
                logger.info("Disconnected from %s", peer.name)

    async def _message_loop(self, ws, peer: PeerConfig) -> None:
        """Listen for incoming messages and send periodic heartbeat pings."""
        from odigos.core.agent_client import PeerEnvelope

        while self._running:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=HEARTBEAT_INTERVAL)
                data = json.loads(raw)
                msg = PeerEnvelope.from_dict(data)
                await self._agent_client.handle_incoming(msg, peer_ip=peer.netbird_ip)
            except asyncio.TimeoutError:
                # No message received -- send heartbeat
                ping = PeerEnvelope(
                    from_agent=self._agent_name,
                    to_agent=peer.name,
                    type="status_ping",
                    payload={},
                )
                await ws.send(json.dumps(ping.to_dict()))
            except Exception as e:
                if not self._running:
                    break
                raise  # will be caught by _connect_loop for reconnect
