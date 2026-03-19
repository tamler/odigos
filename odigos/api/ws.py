"""WebSocket endpoint for real-time chat, subscriptions, and event streaming."""

import asyncio
import hmac
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from odigos.api.auth import SESSION_COOKIE, _validate_session
from odigos.channels.base import UniversalMessage

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_QUEUED_MESSAGES = 3


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


async def _authenticate_ws(websocket: WebSocket) -> tuple[bool, bool]:
    """Authenticate WebSocket via cookie, query param, or first message.

    Returns (authenticated, already_accepted).
    - Cookie auth: authenticated before accept, so already_accepted=False.
    - Query param auth: authenticated before accept, so already_accepted=False.
    - First-message auth: we accept() first, so already_accepted=True.
    """
    settings = websocket.app.state.settings

    # 1. Try session cookie (available before accept)
    cookie = websocket.cookies.get(SESSION_COOKIE)
    if cookie:
        secret = settings.session_secret
        session = _validate_session(secret, cookie)
        if session:
            logger.debug("WebSocket authenticated via session cookie")
            return True, False

    configured_key = settings.api_key

    # 2. Try legacy query param (before accept)
    token = websocket.query_params.get("token")
    if token:
        if configured_key and hmac.compare_digest(token.encode(), configured_key.encode()):
            logger.debug("WebSocket authenticated via query param (deprecated)")
            return True, False
        await websocket.close(code=4003, reason="Invalid token")
        return False, False

    # 3. No API key configured and no valid cookie -- reject
    if not configured_key:
        await websocket.close(code=4003, reason="No valid authentication")
        return False, False

    # 4. Accept and wait for auth message
    await websocket.accept()
    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except (asyncio.TimeoutError, Exception):
        await websocket.close(code=4003, reason="Auth timeout")
        return False, True

    if data.get("type") != "auth" or not hmac.compare_digest(
        (data.get("token") or "").encode(), configured_key.encode()
    ):
        await websocket.send_json({"type": "error", "message": "Invalid credentials"})
        await websocket.close(code=4003, reason="Invalid credentials")
        return False, True

    return True, True


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint with auth, chat, and subscribe support.

    Chat messages are queued and processed sequentially. If a message
    arrives while the agent is processing, it is queued and the user
    is notified. The queue has a max size to prevent runaway input.
    """
    authenticated, already_accepted = await _authenticate_ws(websocket)
    if not authenticated:
        return

    # If not yet accepted (cookie auth or query param auth), accept now
    if not already_accepted:
        await websocket.accept()

    session_id = uuid.uuid4().hex[:12]
    conversation_id = f"web:{session_id}"

    web_channel = websocket.app.state.web_channel
    web_channel.register_connection(conversation_id, websocket)

    first_message = True
    chat_queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUED_MESSAGES)
    processor_task: asyncio.Task | None = None

    async def _process_chat_queue():
        """Process queued chat messages one at a time."""
        nonlocal conversation_id, first_message
        while True:
            data = await chat_queue.get()
            try:
                # Use client-provided conversation_id if resuming
                client_conv_id = data.get("conversation_id")
                if client_conv_id:
                    conversation_id = client_conv_id

                chat_id = conversation_id.split(":", 1)[1] if ":" in conversation_id else conversation_id
                msg_metadata = {"chat_id": chat_id}
                if data.get("context"):
                    msg_metadata["context"] = data["context"]
                msg = UniversalMessage(
                    id=uuid.uuid4().hex,
                    channel="web",
                    sender=session_id,
                    content=data.get("content", ""),
                    timestamp=datetime.now(timezone.utc),
                    metadata=msg_metadata,
                )

                async def send_status(text: str) -> None:
                    await websocket.send_json({"type": "status", "text": text})

                agent_service = websocket.app.state.agent_service
                response = await agent_service.handle_message(msg, status_callback=send_status)

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
            except Exception:
                logger.exception("Error processing queued chat message")
                try:
                    await websocket.send_json({
                        "type": "chat_response",
                        "content": "Something went wrong processing your message. Please try again.",
                        "conversation_id": conversation_id,
                    })
                except Exception:
                    pass
            finally:
                chat_queue.task_done()
                # Tell frontend how many messages remain queued
                await websocket.send_json({
                    "type": "queue_update",
                    "queued": chat_queue.qsize(),
                })

    try:
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "conversation_id": conversation_id,
        })

        # Start the chat message processor
        processor_task = asyncio.create_task(_process_chat_queue())

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # Ignore duplicate auth messages after initial auth
            if msg_type == "auth":
                continue

            if msg_type == "chat":
                if chat_queue.full():
                    await websocket.send_json({
                        "type": "queue_full",
                        "message": "Message queue is full. Please wait for current messages to be processed.",
                        "queued": chat_queue.qsize(),
                    })
                else:
                    chat_queue.put_nowait(data)
                    queued = chat_queue.qsize()
                    # If there are messages ahead, tell the user theirs is queued
                    if queued > 1:
                        await websocket.send_json({
                            "type": "message_queued",
                            "queued": queued,
                            "message": f"Message queued ({queued} pending). I'll get to it shortly.",
                        })

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
        if processor_task:
            processor_task.cancel()
            try:
                await processor_task
            except asyncio.CancelledError:
                pass
        web_channel.unregister_connection(conversation_id, websocket)
