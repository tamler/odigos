"""WebSocket endpoint for real-time chat, subscriptions, and event streaming."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from odigos.channels.base import UniversalMessage

logger = logging.getLogger(__name__)

router = APIRouter()


async def _auto_title_and_notify(ws: WebSocket, db, provider, conversation_id: str,
                                  user_msg: str, assistant_resp: str):
    """Run auto-title in background and push the result to the client."""
    from odigos.core.auto_title import maybe_auto_title
    try:
        await maybe_auto_title(db, provider, conversation_id, user_msg, assistant_resp)
        conv = await db.fetch_one(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        )
        if conv and conv["title"]:
            await ws.send_json({
                "type": "title_updated",
                "conversation_id": conversation_id,
                "title": conv["title"],
            })
    except Exception as exc:
        logger.warning("Auto-title/notify failed: %s", exc)


async def _authenticate_ws(websocket: WebSocket) -> bool:
    """Authenticate WebSocket via first message or legacy query param.

    Accepts either:
    - First message: {"type": "auth", "token": "<key>"}
    - Query param: ?token=<key> (deprecated, logged as warning)
    """
    settings = websocket.app.state.settings
    configured_key = settings.api_key
    if not configured_key:
        await websocket.close(code=4003, reason="API key not configured")
        return False

    # Support legacy query param (log warning so operators know to migrate)
    token = websocket.query_params.get("token")
    if token:
        if token == configured_key:
            logger.debug("WebSocket authenticated via query param (deprecated)")
            return True
        await websocket.close(code=4003, reason="Invalid token")
        return False

    # No query param -- accept and wait for auth message
    await websocket.accept()
    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except (asyncio.TimeoutError, Exception):
        await websocket.close(code=4003, reason="Auth timeout")
        return False

    if data.get("type") != "auth" or data.get("token") != configured_key:
        await websocket.send_json({"type": "error", "message": "Invalid credentials"})
        await websocket.close(code=4003, reason="Invalid credentials")
        return False

    return True


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint with auth, chat, and subscribe support."""
    # Try auth-in-first-message flow
    already_accepted = not websocket.query_params.get("token")
    authenticated = await _authenticate_ws(websocket)
    if not authenticated:
        return

    # If auth was via query param, we still need to accept
    if not already_accepted:
        await websocket.accept()

    session_id = uuid.uuid4().hex[:12]
    conversation_id = f"web:{session_id}"

    web_channel = websocket.app.state.web_channel
    web_channel.register_connection(conversation_id, websocket)

    first_message = True

    try:
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "conversation_id": conversation_id,
        })

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # Ignore duplicate auth messages after initial auth
            if msg_type == "auth":
                continue

            if msg_type == "chat":
                # Use client-provided conversation_id if resuming
                client_conv_id = data.get("conversation_id")
                if client_conv_id:
                    conversation_id = client_conv_id

                chat_id = conversation_id.split(":", 1)[1] if ":" in conversation_id else conversation_id
                msg = UniversalMessage(
                    id=uuid.uuid4().hex,
                    channel="web",
                    sender=session_id,
                    content=data.get("content", ""),
                    timestamp=datetime.now(timezone.utc),
                    metadata={"chat_id": chat_id},
                )
                agent_service = websocket.app.state.agent_service
                response = await agent_service.handle_message(msg)

                # Notify frontend of new conversation so sidebar updates
                if first_message:
                    first_message = False
                    await websocket.send_json({
                        "type": "conversation_started",
                        "conversation_id": conversation_id,
                    })

                await websocket.send_json({
                    "type": "chat_response",
                    "content": response,
                    "conversation_id": conversation_id,
                })
                agent = agent_service.agent
                asyncio.create_task(_auto_title_and_notify(
                    websocket, agent.db, agent.executor.provider,
                    conversation_id, data.get("content", ""), response,
                ))

            elif msg_type == "peer_connect":
                # Peer agent identifying itself
                peer_name = data.get("agent_name", "")
                if peer_name:
                    # Re-register under peer conversation_id
                    web_channel.unregister_connection(conversation_id, websocket)
                    conversation_id = f"peer:{peer_name}"
                    web_channel.register_connection(conversation_id, websocket)
                    await websocket.send_json({
                        "type": "peer_connected",
                        "conversation_id": conversation_id,
                        "agent_name": peer_name,
                    })

            elif msg_type == "approval_response":
                approval_id = data.get("approval_id", "")
                decision = data.get("decision", "denied")
                if approval_id and hasattr(agent_service, "resolve_approval"):
                    resolved = agent_service.resolve_approval(approval_id, decision)
                    await websocket.send_json({
                        "type": "approval_resolved",
                        "approval_id": approval_id,
                        "decision": decision,
                        "resolved": resolved,
                    })

            elif msg_type == "subscribe":
                channels = data.get("channels", [])
                for channel_name in channels:
                    web_channel.add_subscription(conversation_id, channel_name)
                await websocket.send_json({
                    "type": "subscribed",
                    "channels": channels,
                })

    except WebSocketDisconnect:
        pass
    finally:
        web_channel.unregister_connection(conversation_id, websocket)
