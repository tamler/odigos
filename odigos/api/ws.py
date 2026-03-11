"""WebSocket endpoint for real-time chat, subscriptions, and event streaming."""

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from odigos.channels.base import UniversalMessage

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
    except Exception:
        pass


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint with auth, chat, and subscribe support."""
    settings = websocket.app.state.settings
    configured_key = settings.api_key

    # Auth: always require token
    token = websocket.query_params.get("token")
    if not configured_key:
        await websocket.close(code=4003, reason="API key not configured")
        return
    if not token or token != configured_key:
        await websocket.close(code=4003, reason="Invalid or missing token")
        return

    await websocket.accept()

    session_id = uuid.uuid4().hex[:12]
    conversation_id = f"web:{session_id}"

    web_channel = websocket.app.state.web_channel
    web_channel.register_connection(conversation_id, websocket)

    try:
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "conversation_id": conversation_id,
        })

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "chat":
                # Extract chat_id from conversation_id so agent resolves to same id
                chat_id = conversation_id.split(":", 1)[1]
                msg = UniversalMessage(
                    id=uuid.uuid4().hex,
                    channel="web",
                    sender=session_id,
                    content=data.get("content", ""),
                    timestamp=datetime.now(timezone.utc),
                    metadata={"chat_id": chat_id},
                )
                agent = websocket.app.state.agent
                response = await agent.handle_message(msg)
                await websocket.send_json({
                    "type": "chat_response",
                    "content": response,
                    "conversation_id": conversation_id,
                })
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
