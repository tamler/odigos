"""Agent registry API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from odigos.api.deps import get_db, require_api_key
from odigos.db import Database

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


@router.get("/agents")
async def list_agents(db: Database = Depends(get_db)):
    """List all registered agents."""
    rows = await db.fetch_all(
        "SELECT * FROM agent_registry ORDER BY agent_name"
    )
    return {"agents": [dict(r) for r in rows]}


@router.get("/agents/{agent_name}")
async def get_agent(agent_name: str, db: Database = Depends(get_db)):
    """Get details for a specific agent."""
    row = await db.fetch_one(
        "SELECT * FROM agent_registry WHERE agent_name = ?", (agent_name,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return dict(row)
