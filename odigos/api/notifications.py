"""Notification list and feedback API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from odigos.api.deps import get_db, require_auth
from odigos.db import Database

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


@router.get("/notifications")
async def list_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    unread_only: bool = Query(default=False),
    db: Database = Depends(get_db),
):
    """List notifications, newest first."""
    where = "WHERE read = 0" if unread_only else ""
    rows = await db.fetch_all(
        f"SELECT * FROM notifications {where} ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return {"notifications": rows}


class NotificationUpdate(BaseModel):
    read: bool | None = None
    reaction: str | None = None


@router.patch("/notifications/{notification_id}")
async def update_notification(
    notification_id: str,
    update: NotificationUpdate,
    db: Database = Depends(get_db),
):
    """Mark notification as read or add a reaction."""
    sets: list[str] = []
    params: list = []
    if update.read is not None:
        sets.append("read = ?")
        params.append(1 if update.read else 0)
    if update.reaction is not None:
        if update.reaction not in ("thumbs_up", "not_relevant", "dismiss"):
            return {"error": "invalid reaction"}
        sets.append("reaction = ?")
        params.append(update.reaction)
    if not sets:
        return {"status": "no changes"}
    params.append(notification_id)
    await db.execute(
        f"UPDATE notifications SET {', '.join(sets)} WHERE id = ?",
        tuple(params),
    )
    return {"status": "ok"}
