"""WebSocket endpoint for agent-to-agent communication.

Peer agents connect to /ws/agent to exchange PeerEnvelope messages in real-time.
Authenticated via first message (preferred) or query parameter (deprecated).
After auth, server sends auth_ok with its identity. Peer identification
happens via registry_announce or from_agent field on first message.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from odigos.core.agent_client import AgentClient

logger = logging.getLogger(__name__)

router = APIRouter()


async def _authenticate_agent_ws(websocket: WebSocket) -> tuple[bool, bool]:
    """Authenticate agent WebSocket via first message or legacy query param.

    Returns (authenticated, already_accepted).
    """
    expected = getattr(websocket.app.state, "settings", None)
    api_key = getattr(expected, "api_key", "") if expected else ""

    token = websocket.query_params.get("token", "")

    # Legacy query param flow
    if token:
        authorized = bool(api_key and hmac.compare_digest(token.encode(), api_key.encode()))
        if not authorized and token.startswith("card-sk-"):
            card_manager = getattr(websocket.app.state, "card_manager", None)
            if card_manager:
                card = await card_manager.validate_card_key(token)
                if card and card.get("permissions") == "mesh":
                    authorized = True
        if not authorized:
            await websocket.close(code=4001, reason="Unauthorized")
        return authorized, False

    # First-message auth flow
    await websocket.accept()
    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except (asyncio.TimeoutError, Exception):
        await websocket.close(code=4001, reason="Auth timeout")
        return False, True

    if data.get("type") != "auth":
        await websocket.close(code=4001, reason="Expected auth message")
        return False, True

    auth_token = data.get("token", "")
    authorized = bool(api_key and hmac.compare_digest(auth_token.encode(), api_key.encode()))
    if not authorized and auth_token.startswith("card-sk-"):
        card_manager = getattr(websocket.app.state, "card_manager", None)
        if card_manager:
            card = await card_manager.validate_card_key(auth_token)
            if card and card.get("permissions") == "mesh":
                authorized = True

    if not authorized:
        await websocket.send_json({"type": "error", "payload": {"message": "Unauthorized"}})
        await websocket.close(code=4001, reason="Unauthorized")

    return authorized, True


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    authenticated, was_accepted = await _authenticate_agent_ws(websocket)
    if not authenticated:
        return

    if not was_accepted:
        await websocket.accept()

    agent_client: AgentClient = websocket.app.state.agent_client
    peer_name = None
    peer_ip = websocket.client.host if websocket.client else ""

    # Send auth_ok with our identity so the peer knows who we are
    await websocket.send_json({
        "type": "auth_ok",
        "agent_name": agent_client.agent_name,
    })

    try:
        while True:
            data = await websocket.receive_json()

            # Skip auth messages after initial auth
            if isinstance(data, dict) and data.get("type") == "auth":
                continue

            if not isinstance(data, dict) or "type" not in data:
                await websocket.send_json({"type": "error", "payload": {"message": "Invalid message format"}})
                continue

            from odigos.core.agent_client import PeerEnvelope
            msg = PeerEnvelope.from_dict(data)

            if peer_name is None:
                peer_name = msg.from_agent
                logger.info("Agent connection from %s (%s)", peer_name, peer_ip)
                # Register this WS connection for outbox flushing + sending
                agent_client._ws_connections[peer_name] = websocket
                # Flush any queued outbound messages to this peer
                flushed = await agent_client.flush_outbox()
                if flushed:
                    logger.info("Flushed %d queued messages to %s", flushed, peer_name)

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
    except Exception:
        logger.warning("Agent WebSocket error", exc_info=True)
    finally:
        if peer_name and peer_name in agent_client._ws_connections:
            del agent_client._ws_connections[peer_name]
