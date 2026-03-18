"""Cron scheduler API endpoints — backed by the unified Scheduler."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import get_scheduler, require_auth
from odigos.core.scheduler import Scheduler

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)


class CronCreateRequest(BaseModel):
    name: str
    schedule: str
    action: str
    conversation_id: str | None = None


class CronToggleRequest(BaseModel):
    enabled: bool


@router.get("/cron")
async def list_cron_entries(
    scheduler: Scheduler = Depends(get_scheduler),
):
    """List all scheduled tasks (backward-compatible endpoint)."""
    tasks = await scheduler.list_tasks()
    return {"entries": tasks}


@router.post("/cron")
async def create_cron_entry(
    body: CronCreateRequest,
    scheduler: Scheduler = Depends(get_scheduler),
):
    """Create a new recurring scheduled task."""
    try:
        task_id = await scheduler.schedule_recurring(
            name=body.name,
            action=body.action,
            cron_expression=body.schedule,
            action_type="execute",
            conversation_id=body.conversation_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Return the created task for the client
    tasks = await scheduler.list_tasks()
    for t in tasks:
        if t["id"] == task_id:
            return t
    return {"id": task_id, "status": "created"}


@router.delete("/cron/{entry_id}")
async def delete_cron_entry(
    entry_id: str,
    scheduler: Scheduler = Depends(get_scheduler),
):
    """Remove a scheduled task."""
    await scheduler.cancel(entry_id)
    return {"status": "deleted"}


@router.patch("/cron/{entry_id}")
async def toggle_cron_entry(
    entry_id: str,
    body: CronToggleRequest,
    scheduler: Scheduler = Depends(get_scheduler),
):
    """Toggle a scheduled task enabled/disabled."""
    await scheduler.toggle(entry_id, body.enabled)
    return {"status": "updated", "enabled": body.enabled}
