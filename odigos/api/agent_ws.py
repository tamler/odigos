"""WebSocket endpoint for agent-to-agent communication.

Peer agents connect to /ws/agent to exchange PeerEnvelope messages in real-time.
Authenticated via API key in query parameter.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from odigos.core.agent_client import AgentClient

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    token = websocket.query_params.get("token", "")
    expected = getattr(websocket.app.state, "settings", None)
    api_key = getattr(expected, "api_key", "") if expected else ""

    # Check global API key
    authorized = bool(api_key and token == api_key)

    # Check card key if global key didn't match
    if not authorized and token.startswith("card-sk-"):
        card_manager = getattr(websocket.app.state, "card_manager", None)
        if card_manager:
            card = await card_manager.validate_card_key(token)
            if card and card.get("permissions") == "mesh":
                authorized = True

    if not authorized:
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
