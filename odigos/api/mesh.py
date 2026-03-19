"""Mesh API -- peer status, messaging, and connection management."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import get_db, require_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/mesh",
    dependencies=[Depends(require_auth)],
)


class SendMessageRequest(BaseModel):
    content: str


@router.get("/peers")
async def list_peers(db=Depends(get_db)):
    """List configured peers with online status and message counts."""
    # Get peer status from agent_registry
    registry_rows = await db.fetch_all(
        "SELECT agent_name, status, last_seen, netbird_ip, ws_port "
        "FROM agent_registry ORDER BY agent_name"
    )
    registry = {r["agent_name"]: dict(r) for r in registry_rows}

    # Get message counts per peer
    msg_counts = await db.fetch_all(
        "SELECT peer_name, direction, COUNT(*) as cnt "
        "FROM peer_messages GROUP BY peer_name, direction"
    )
    counts: dict[str, dict] = {}
    for row in msg_counts:
        name = row["peer_name"]
        if name not in counts:
            counts[name] = {"sent": 0, "received": 0}
        if row["direction"] == "outbound":
            counts[name]["sent"] = row["cnt"]
        else:
            counts[name]["received"] = row["cnt"]

    # Merge registry info with message counts
    peer_names = set(registry.keys()) | set(counts.keys())
    peers = []
    for name in sorted(peer_names):
        reg = registry.get(name, {})
        cnt = counts.get(name, {"sent": 0, "received": 0})
        peers.append({
            "name": name,
            "status": reg.get("status", "unknown"),
            "last_seen": reg.get("last_seen"),
            "netbird_ip": reg.get("netbird_ip"),
            "ws_port": reg.get("ws_port"),
            "messages_sent": cnt["sent"],
            "messages_received": cnt["received"],
        })

    return {"peers": peers}


@router.post("/peers/{peer_name}/message")
async def send_peer_message(peer_name: str, body: SendMessageRequest, db=Depends(get_db)):
    """Send a message to a peer agent."""
    from fastapi import Request

    # Get agent_client from app state (injected at startup)
    import inspect
    frame = inspect.currentframe()
    # Use a simpler approach -- get from the request
    raise HTTPException(status_code=501, detail="Use the chat interface to message peers via message_peer tool")


@router.post("/peers/{peer_name}/ping")
async def ping_peer(peer_name: str, db=Depends(get_db)):
    """Test connectivity to a peer."""
    # Check if peer is in registry
    row = await db.fetch_one(
        "SELECT status, last_seen FROM agent_registry WHERE agent_name = ?",
        (peer_name,),
    )
    if not row:
        return {"reachable": False, "error": "Peer not in registry"}

    return {
        "reachable": row["status"] == "online",
        "status": row["status"],
        "last_seen": row["last_seen"],
    }


@router.get("/messages")
async def list_messages(limit: int = 50, peer_name: str | None = None, db=Depends(get_db)):
    """List recent peer messages."""
    if peer_name:
        rows = await db.fetch_all(
            "SELECT message_id, direction, peer_name, message_type, content, status, created_at "
            "FROM peer_messages WHERE peer_name = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (peer_name, limit),
        )
    else:
        rows = await db.fetch_all(
            "SELECT message_id, direction, peer_name, message_type, content, status, created_at "
            "FROM peer_messages ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

    messages = []
    for row in rows:
        msg = dict(row)
        # Parse content from JSON if possible
        try:
            msg["content"] = json.loads(msg["content"])
        except (json.JSONDecodeError, TypeError):
            pass
        messages.append(msg)

    return {"messages": messages}
