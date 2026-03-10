"""Inbound peer-agent message endpoint."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
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
    agent: Agent = Depends(get_agent),
):
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
