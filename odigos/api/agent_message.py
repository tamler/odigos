"""Peer agent discovery endpoint.

Provides POST /api/agent/peer/announce for peers to register their
WebSocket coordinates. Not used for messaging -- all messaging is WS-only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from odigos.api.deps import get_agent_client, get_db, require_api_key

router = APIRouter(
    prefix="/api/agent",
    dependencies=[Depends(require_api_key)],
)


class PeerAnnounceRequest(BaseModel):
    agent_name: str
    ws_host: str = ""
    ws_port: int = 8001
    role: str = ""
    description: str = ""
    specialty: str | None = None
    capabilities: list[str] = []


@router.post("/peer/announce")
async def peer_announce(
    body: PeerAnnounceRequest,
    db=Depends(get_db),
    agent_client=Depends(get_agent_client),
):
    """Register a peer agent's WebSocket coordinates for future communication."""
    now = datetime.now(timezone.utc).isoformat()

    existing = await db.fetch_one(
        "SELECT agent_name FROM agent_registry WHERE agent_name = ?",
        (body.agent_name,),
    )

    if existing:
        await db.execute(
            "UPDATE agent_registry SET role = ?, description = ?, specialty = ?, "
            "netbird_ip = ?, ws_port = ?, capabilities = ?, "
            "status = 'online', last_seen = ?, updated_at = ? "
            "WHERE agent_name = ?",
            (body.role, body.description, body.specialty,
             body.ws_host, body.ws_port, json.dumps(body.capabilities),
             now, now, body.agent_name),
        )
    else:
        await db.execute(
            "INSERT INTO agent_registry "
            "(agent_name, role, description, specialty, netbird_ip, ws_port, "
            "capabilities, status, last_seen, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'online', ?, ?)",
            (body.agent_name, body.role, body.description, body.specialty,
             body.ws_host, body.ws_port, json.dumps(body.capabilities),
             now, now),
        )

    # Bidirectional discovery: add announcing peer so we can message it back
    if agent_client and body.ws_host:
        agent_client.add_discovered_peer(body.agent_name, body.ws_host, body.ws_port)

    return {"status": "ok", "message": f"Peer {body.agent_name} registered"}
