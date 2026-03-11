"""WebSocket endpoint for agent-to-agent communication.

Peer agents connect to /ws/agent to exchange messages in real-time.
Authenticated via API key in query parameter.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

if TYPE_CHECKING:
    from odigos.core.agent_client import AgentClient, AgentMessage

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    token = websocket.query_params.get("token", "")
    expected = getattr(websocket.app.state, "settings", None)
    api_key = getattr(expected, "api_key", "") if expected else ""

    if not api_key or token != api_key:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    agent_client = websocket.app.state.agent_client
    peer_name = None
    peer_ip = websocket.client.host if websocket.client else ""

    try:
        while True:
            data = await websocket.receive_json()

            if not isinstance(data, dict) or "type" not in data:
                await websocket.send_json({"type": "error", "content": "Invalid message format"})
                continue

            from odigos.core.agent_client import AgentMessage
            msg = AgentMessage.from_dict(data)

            if peer_name is None:
                peer_name = msg.from_agent
                logger.info("Agent connection from %s (%s)", peer_name, peer_ip)

            if msg.type == "status_ping":
                await websocket.send_json({
                    "type": "status_pong",
                    "from_agent": agent_client.agent_name,
                    "content": "",
                })

            await agent_client.handle_incoming(msg, peer_ip=peer_ip)

    except WebSocketDisconnect:
        logger.info("Agent %s disconnected", peer_name or "unknown")
    except Exception:
        logger.warning("Agent WebSocket error", exc_info=True)
