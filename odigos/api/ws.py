"""WebSocket endpoint for real-time chat, subscriptions, and event streaming."""
from __future__ import annotations

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

_VALID_ACTIONS = {"navigate", "refresh", "open_chat", "create", "create_and_navigate", "theme", "focus_entry", "stop_tts", "highlight"}


def _extract_ui_actions(response: str) -> list[dict]:
    """Extract UI action directives from LLM response text.

    Looks for JSON objects with an "action" key, either inline or in code blocks.
    """
    import json as _json
    import re
    actions = []

    # Find ```json blocks
    for match in re.finditer(r'```json\s*\n?(.*?)\n?```', response, re.DOTALL):
        try:
            obj = _json.loads(match.group(1).strip())
            if isinstance(obj, dict) and obj.get("action") in _VALID_ACTIONS:
                actions.append(obj)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict) and item.get("action") in _VALID_ACTIONS:
                        actions.append(item)
        except (ValueError, TypeError):
            pass

    return actions

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
    settings = websocket.app.state.container.settings

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

    web_channel = websocket.app.state.container.web_channel
    web_channel.register_connection(conversation_id, websocket)

    first_message = True
    chat_queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUED_MESSAGES)
    processor_task: asyncio.Task | None = None
    cancel_event: asyncio.Event | None = None
    background_tasks: set[asyncio.Task] = set()
    recent_turns: list[dict] = []

    async def _process_chat_queue():
        """Process queued chat messages one at a time."""
        nonlocal conversation_id, first_message, cancel_event, recent_turns
        while True:
            data = await chat_queue.get()
            try:
                # Use client-provided conversation_id if resuming.
                # "new" or absent = generate fresh ID for new conversation.
                client_conv_id = data.get("conversation_id")
                if client_conv_id and client_conv_id != "new":
                    conversation_id = client_conv_id
                elif client_conv_id == "new" or not client_conv_id:
                    conversation_id = f"web:{uuid.uuid4().hex[:16]}"

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
                    try:
                        await websocket.send_json({"type": "status", "text": text})
                    except Exception:
                        pass  # Client disconnected

                streamed = False

                async def send_chunk(text: str) -> None:
                    nonlocal streamed
                    streamed = True
                    try:
                        await websocket.send_json({
                            "type": "chat_chunk",
                            "content": text,
                            "conversation_id": conversation_id,
                        })
                    except Exception:
                        pass  # Client disconnected

                agent_service = websocket.app.state.container.agent_service
                cancel_event = asyncio.Event()
                user_content = data.get("content", "")
                recent_turns.append({"role": "user", "content": user_content[:500]})
                response = await agent_service.handle_message(
                    msg, status_callback=send_status, stream_callback=send_chunk,
                    abort_event=cancel_event,
                    recent_turns=recent_turns,
                )
                cancel_event = None

                # Track assistant turn and keep last 6 messages (3 turns)
                recent_turns.append({"role": "assistant", "content": (response or "")[:500]})
                if len(recent_turns) > 6:
                    recent_turns = recent_turns[-6:]

                # Notify frontend of new conversation so sidebar updates
                try:
                    if first_message:
                        first_message = False
                        await websocket.send_json({
                            "type": "conversation_started",
                            "conversation_id": conversation_id,
                        })

                    # Extract UI actions from response (```json blocks with "action" key)
                    ui_actions = _extract_ui_actions(response)

                    # When streaming was used, client already has the content.
                    # Only send content when NOT streaming (e.g., tool-only responses).
                    response_msg = {
                        "type": "chat_response",
                        "conversation_id": conversation_id,
                    }
                    if not streamed:
                        response_msg["content"] = response
                    if ui_actions:
                        response_msg["actions"] = ui_actions
                    await websocket.send_json(response_msg)

                    # Send suggested actions if the agent offered options
                    agent = agent_service.agent
                    actions_map = getattr(agent, "_suggested_actions_by_convo", {})
                    actions = actions_map.pop(conversation_id, None)
                    if actions:
                        await websocket.send_json({
                            "type": "suggested_actions",
                            "actions": actions,
                            "conversation_id": conversation_id,
                        })

                    # Send task_started if background tasks were initiated
                    bg_tasks_map = getattr(agent, "_background_tasks_by_convo", {})
                    bg_tasks = bg_tasks_map.pop(conversation_id, None)
                    if bg_tasks:
                        for bt in bg_tasks:
                            await websocket.send_json({
                                "type": "task_started",
                                "task": bt,
                                "conversation_id": conversation_id,
                            })
                except Exception:
                    pass  # Client disconnected, response is still saved in DB
                agent = agent_service.agent
                task = asyncio.create_task(_auto_title_and_notify(
                    websocket, agent.db, agent.executor.provider,
                    conversation_id, data.get("content", ""), response,
                ))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
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
                try:
                    await websocket.send_json({
                        "type": "queue_update",
                        "queued": chat_queue.qsize(),
                    })
                except Exception:
                    pass  # Client may have disconnected

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

            elif msg_type == "cancel":
                if cancel_event is not None:
                    cancel_event.set()
                    try:
                        await websocket.send_json({
                            "type": "stream_end",
                            "cancelled": True,
                            "conversation_id": conversation_id,
                        })
                    except Exception:
                        pass

            elif msg_type == "edit":
                # Truncate conversation history and re-send edited content
                edit_index = data.get("message_index")
                edit_content = data.get("content", "")
                if edit_index is not None and edit_content:
                    try:
                        db = websocket.app.state.container.agent_service.agent.db
                        rows = await db.fetch_all(
                            "SELECT id FROM messages WHERE conversation_id = ? ORDER BY timestamp",
                            (conversation_id,),
                        )
                        if edit_index < len(rows):
                            ids_to_delete = [r["id"] for r in rows[edit_index:]]
                            placeholders = ",".join("?" * len(ids_to_delete))
                            await db.execute(
                                f"DELETE FROM messages WHERE id IN ({placeholders})",
                                ids_to_delete,
                            )
                    except Exception as e:
                        logger.warning("Edit truncation failed: %s", e)
                    # Re-send as a chat message
                    if not chat_queue.full():
                        chat_queue.put_nowait({"type": "chat", "content": edit_content,
                                               "conversation_id": data.get("conversation_id")})

            elif msg_type == "undo":
                # Remove the last user+assistant exchange
                try:
                    db = websocket.app.state.container.agent_service.agent.db
                    last_two = await db.fetch_all(
                        "SELECT id, role FROM messages WHERE conversation_id = ? "
                        "ORDER BY timestamp DESC LIMIT 2",
                        (conversation_id,),
                    )
                    if last_two:
                        ids = [r["id"] for r in last_two]
                        placeholders = ",".join("?" * len(ids))
                        await db.execute(
                            f"DELETE FROM messages WHERE id IN ({placeholders})", ids,
                        )
                        await websocket.send_json({
                            "type": "undo_complete",
                            "conversation_id": conversation_id,
                            "removed": len(ids),
                        })
                except Exception as e:
                    logger.warning("Undo failed: %s", e)

            elif msg_type == "retry":
                # Remove last assistant response, then re-send the last user message
                try:
                    db = websocket.app.state.container.agent_service.agent.db
                    last_asst = await db.fetch_one(
                        "SELECT id FROM messages WHERE conversation_id = ? AND role = 'assistant' "
                        "ORDER BY timestamp DESC LIMIT 1",
                        (conversation_id,),
                    )
                    if last_asst:
                        await db.execute("DELETE FROM messages WHERE id = ?", (last_asst["id"],))
                    last_user = await db.fetch_one(
                        "SELECT content FROM messages WHERE conversation_id = ? AND role = 'user' "
                        "ORDER BY timestamp DESC LIMIT 1",
                        (conversation_id,),
                    )
                    if last_user and not chat_queue.full():
                        chat_queue.put_nowait({
                            "type": "chat",
                            "content": last_user["content"],
                            "conversation_id": conversation_id,
                        })
                except Exception as e:
                    logger.warning("Retry failed: %s", e)

            elif msg_type == "compress":
                # User-triggered context compression
                try:
                    agent = websocket.app.state.container.agent_service.agent
                    if hasattr(agent, 'context_assembler') and agent.context_assembler.summarizer:
                        await agent.context_assembler.summarizer.summarize_if_needed(
                            conversation_id, force=True,
                        )
                        await websocket.send_json({
                            "type": "compress_complete",
                            "conversation_id": conversation_id,
                        })
                    else:
                        await websocket.send_json({
                            "type": "status",
                            "text": "Compression not available",
                        })
                except Exception as e:
                    logger.warning("Compress failed: %s", e)

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
        for task in background_tasks:
            task.cancel()
        background_tasks.clear()
        web_channel.unregister_connection(conversation_id, websocket)
