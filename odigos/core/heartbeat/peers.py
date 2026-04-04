"""Heartbeat peer agent communication module."""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.channels.base import UniversalMessage
from odigos.core.content_filter import ContentFilter
from odigos.core.heartbeat.utils import send_notification

if TYPE_CHECKING:
    from odigos.core.heartbeat_old import Heartbeat

logger = logging.getLogger(__name__)

_peer_filter = ContentFilter()


async def dispatch_as_subagent(
    hb: "Heartbeat", instruction: str, conversation_id: str = ""
) -> str | None:
    """Run a heartbeat task as an internal subagent for multi-step reasoning."""
    if not hb.subagent_manager:
        return None
    try:
        subagent_id = await hb.subagent_manager.spawn(
            instruction=instruction,
            parent_conversation_id=conversation_id or "heartbeat",
        )
        return subagent_id
    except Exception:
        logger.warning("Subagent dispatch failed", exc_info=True)
        return None


async def process_peer_messages(hb: "Heartbeat") -> bool:
    """Phase 4: Process unhandled inbound messages from peer agents."""
    messages = await hb.agent_client.get_unprocessed_inbound(limit=3)
    if not messages:
        return False

    for msg in messages:
        peer = msg["peer_name"]
        msg_type = msg["message_type"]

        if msg_type in ("registry_announce", "status_ping", "status_pong"):
            await hb.agent_client.mark_processed(msg["message_id"])
            continue

        try:
            content_raw = msg["content"]
            payload = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
            message_text = payload.get("content", "") if isinstance(payload, dict) else str(payload)
        except (json.JSONDecodeError, TypeError):
            message_text = str(msg["content"])

        if not message_text.strip() or (
            message_text.strip().startswith("{") and message_text.strip().endswith("}")
        ):
            await hb.agent_client.mark_processed(msg["message_id"])
            logger.debug("Skipped non-content peer message from %s: %s", peer, msg_type)
            continue

        scan = _peer_filter.scan(message_text)
        if scan.risk_level == "high":
            logger.warning("Blocked peer message from %s: high injection risk", peer)
            await hb.agent_client.mark_processed(msg["message_id"])
            continue
        message_text = scan.sanitized_text

        logger.info(
            "Processing inbound %s from peer %s: %s",
            msg_type, peer, message_text[:100],
        )

        try:
            peer_msg = UniversalMessage(
                id=str(uuid.uuid4()),
                channel="peer",
                sender=peer,
                content=f"[Peer message from {peer} (type: {msg_type})]\n\n{message_text}",
                timestamp=datetime.now(timezone.utc),
                metadata={"peer_name": peer, "message_type": msg_type},
            )
            agent_response = await hb.agent.handle_message(peer_msg)

            if agent_response and hb.agent_client:
                await hb.agent_client.send(
                    peer,
                    payload={"content": agent_response},
                    message_type="message",
                    correlation_id=msg.get("response_to"),
                )
        except Exception:
            logger.warning("Failed to process peer message from %s", peer, exc_info=True)

        await hb.agent_client.mark_processed(msg["message_id"])

    return True


async def deliver_subagent_results(hb: "Heartbeat") -> bool:
    """Deliver completed subagent results to their parent conversations."""
    if not hb.subagent_manager:
        return False
    results = await hb.subagent_manager.get_completed_all()
    if not results:
        return False
    for r in results:
        try:
            summary = (
                f"[Subagent result] Task: {r['instruction'][:200]}\n\n"
                f"Status: {r['status']}\n"
                f"Result: {r['result']}"
            )
            conversation_id = r["parent_conversation_id"]
            await send_notification(hb, conversation_id, summary[:4000])
            await hb.subagent_manager.mark_delivered(r["id"])
            logger.info("Delivered subagent result %s to %s", r["id"], conversation_id)
        except Exception:
            logger.exception("Failed to deliver subagent result %s", r["id"])
    return True


async def peer_maintenance(hb: "Heartbeat") -> None:
    """Phase 6: Announce self to peers, flush outbox, mark stale peers offline."""
    if not hb.agent_client.list_peer_names():
        online = await hb.db.fetch_one(
            "SELECT 1 FROM agent_registry WHERE status = 'online' LIMIT 1"
        )
        if not online:
            return

    now = time.monotonic()
    try:
        if now - hb._last_announce >= hb._announce_interval:
            hb._last_announce = now
            await hb.agent_client.broadcast_announce(
                role=hb._agent_role,
                description=hb._agent_description,
                ws_port=hb._ws_port,
            )
            await hb.agent_client.mark_stale_peers()

        await hb.agent_client.flush_outbox()
    except Exception:
        logger.debug("Peer maintenance failed", exc_info=True)
