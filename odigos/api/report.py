"""Message report endpoint — user flags bad/unhelpful responses."""
from __future__ import annotations

import uuid
from enum import Enum

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from odigos.api.deps import require_auth


router = APIRouter(
    prefix="/api/conversations",
    dependencies=[Depends(require_auth)],
)


class ReportReason(str, Enum):
    wrong = "wrong"
    unhelpful = "unhelpful"
    harmful = "harmful"


class ReportBody(BaseModel):
    message_index: int
    reason: ReportReason
    message_content: str


@router.post("/{conversation_id}/report")
async def report_message(
    conversation_id: str,
    body: ReportBody,
    request: Request,
):
    """Flag a message as bad. Creates a negative evaluation record for AREW."""
    db = request.app.state.db
    eval_id = uuid.uuid4().hex[:16]

    await db.execute(
        "INSERT INTO evaluations (id, message_id, conversation_id, task_type, "
        "overall_score, improvement_signal, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            eval_id,
            f"msg-{body.message_index}",
            conversation_id,
            "user_report",
            -1.0,
            f"User reported: {body.reason.value} — {body.message_content[:200]}",
        ),
    )

    return {"status": "reported", "evaluation_id": eval_id}
