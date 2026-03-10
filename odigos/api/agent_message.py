"""Inbound peer-agent message endpoint."""

import uuid
from datetime import datetime, timezone

import uuid as uuid_mod

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from odigos.api.deps import get_agent, require_api_key
from odigos.channels.base import UniversalMessage
from odigos.core.agent import Agent

router = APIRouter(
    prefix="/api/agent",
    dependencies=[Depends(require_api_key)],
)


class PeerMessageRequest(BaseModel):
    from_agent: str
    message_type: str = "message"
    content: str = Field(min_length=1)
    metadata: dict = Field(default_factory=dict)


@router.post("/message")
async def receive_peer_message(
    body: PeerMessageRequest,
    request: Request,
    agent: Agent = Depends(get_agent),
):
    message_id = body.metadata.get("message_id", str(uuid_mod.uuid4()))
    db = request.app.state.db

    # Check for duplicate
    existing = await db.fetch_one(
        "SELECT 1 FROM peer_messages WHERE message_id = ?", (message_id,)
    )
    if existing:
        return {"status": "duplicate", "message": "Message already processed"}

    # Record inbound
    await db.execute(
        "INSERT INTO peer_messages "
        "(message_id, direction, peer_name, message_type, content, status) "
        "VALUES (?, 'inbound', ?, ?, ?, 'received')",
        (message_id, body.from_agent, body.message_type, body.content),
    )

    formatted_content = f"[{body.message_type} from {body.from_agent}]: {body.content}"

    msg = UniversalMessage(
        id=uuid.uuid4().hex,
        channel="peer",
        sender=body.from_agent,
        content=formatted_content,
        timestamp=datetime.now(timezone.utc),
        metadata={
            "chat_id": body.from_agent,
            "message_type": body.message_type,
            **body.metadata,
        },
    )

    response = await agent.handle_message(msg)
    return {"status": "ok", "response": response}
