"""Notification list and feedback API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
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


@router.post("/notifications/{notification_id}/discuss")
async def discuss_notification(notification_id: str, request: Request,
                                db: Database = Depends(get_db)):
    """Start a conversation about a notification. Returns conversation_id."""
    notif = await db.fetch_one("SELECT * FROM notifications WHERE id = ?", (notification_id,))
    if not notif:
        return JSONResponse({"error": "not found"}, status_code=404)

    await db.execute(
        "UPDATE notifications SET discussed_at = datetime('now'), read = 1 WHERE id = ?",
        (notification_id,),
    )

    if notif["conversation_id"]:
        return {"conversation_id": notif["conversation_id"]}

    container = request.app.state.container
    conv_id = await container.message_bus.create_conversation(channel="web")

    artifact_content = ""
    if notif.get("artifact_path"):
        from pathlib import Path
        p = Path(notif["artifact_path"])
        if p.exists():
            artifact_content = p.read_text(encoding="utf-8")[:4000]

    if artifact_content:
        await container.message_bus.publish(
            conversation_id=conv_id, role="user",
            content=f"Let's discuss your finding: {notif['title']}\n\n{artifact_content}",
            channel="web",
        )

    await db.execute("UPDATE notifications SET conversation_id = ? WHERE id = ?", (conv_id, notification_id))
    return {"conversation_id": conv_id}


class ProactiveSettingsUpdate(BaseModel):
    enabled: bool | None = None
    max_cycles_per_hour: int | None = None


@router.patch("/settings/proactive")
async def update_proactive_settings(update: ProactiveSettingsUpdate, request: Request,
                                     db: Database = Depends(get_db)):
    """Update proactive engine settings."""
    container = request.app.state.container
    config = getattr(container.heartbeat, '_proactive_config', None) if container.heartbeat else None
    if not config:
        return {"error": "proactive config not available"}
    if update.enabled is not None:
        config.enabled = update.enabled
    if update.max_cycles_per_hour is not None:
        config.max_cycles_per_hour = max(1, min(12, update.max_cycles_per_hour))
    return {"status": "ok", "enabled": config.enabled, "max_cycles_per_hour": config.max_cycles_per_hour}


@router.get("/settings/proactive")
async def get_proactive_settings(request: Request):
    """Get current proactive engine settings."""
    container = request.app.state.container
    config = getattr(container.heartbeat, '_proactive_config', None) if container.heartbeat else None
    if not config:
        return {"enabled": True, "max_cycles_per_hour": 4}
    return {"enabled": config.enabled, "max_cycles_per_hour": config.max_cycles_per_hour}
