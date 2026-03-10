"""Programmatic message submission endpoint."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from odigos.api.deps import get_agent, require_api_key
from odigos.channels.base import UniversalMessage
from odigos.core.agent import Agent

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


class MessageRequest(BaseModel):
    content: str = Field(min_length=1)
    conversation_id: str | None = None


@router.post("/message")
async def submit_message(
    body: MessageRequest,
    agent: Agent = Depends(get_agent),
):
    conversation_id = body.conversation_id or f"api:{uuid.uuid4().hex[:12]}"

    # The agent derives conversation_id from f"{msg.channel}:{chat_id}"
    # where chat_id = msg.metadata.get("chat_id", msg.sender).
    # We set chat_id in metadata so that the agent resolves to our conversation_id.
    chat_id = conversation_id.split(":", 1)[1] if ":" in conversation_id else conversation_id

    msg = UniversalMessage(
        id=uuid.uuid4().hex,
        channel="api",
        sender="api",
        content=body.content,
        timestamp=datetime.now(timezone.utc),
        metadata={"chat_id": chat_id},
    )

    response = await agent.handle_message(msg)
    return {"response": response, "conversation_id": conversation_id}
