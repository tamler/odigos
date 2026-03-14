"""Cron scheduler API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import get_cron_manager, require_api_key
from odigos.core.cron import CronManager

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
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
    cron_manager: CronManager = Depends(get_cron_manager),
):
    """List all cron entries."""
    entries = await cron_manager.list()
    return {"entries": [_entry_to_dict(e) for e in entries]}


@router.post("/cron")
async def create_cron_entry(
    body: CronCreateRequest,
    cron_manager: CronManager = Depends(get_cron_manager),
):
    """Create a new cron entry."""
    try:
        entry = await cron_manager.add(
            name=body.name,
            schedule=body.schedule,
            action=body.action,
            conversation_id=body.conversation_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _entry_to_dict(entry)


@router.delete("/cron/{entry_id}")
async def delete_cron_entry(
    entry_id: str,
    cron_manager: CronManager = Depends(get_cron_manager),
):
    """Remove a cron entry."""
    await cron_manager.remove(entry_id)
    return {"status": "deleted"}


@router.patch("/cron/{entry_id}")
async def toggle_cron_entry(
    entry_id: str,
    body: CronToggleRequest,
    cron_manager: CronManager = Depends(get_cron_manager),
):
    """Toggle a cron entry enabled/disabled."""
    await cron_manager.toggle(entry_id, body.enabled)
    return {"status": "updated", "enabled": body.enabled}


def _entry_to_dict(entry) -> dict:
    return {
        "id": entry.id,
        "name": entry.name,
        "schedule": entry.schedule,
        "action": entry.action,
        "enabled": entry.enabled,
        "created_at": entry.created_at,
        "last_run_at": entry.last_run_at,
        "next_run_at": entry.next_run_at,
        "conversation_id": entry.conversation_id,
    }
