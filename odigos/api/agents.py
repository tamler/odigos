"""Agent registry API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import get_db, get_spawner, require_api_key
from odigos.db import Database

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


class SpawnRequest(BaseModel):
    agent_name: str
    role: str
    description: str
    specialty: str = ""
    proposal_id: str = ""


@router.get("/agents")
async def list_agents(db: Database = Depends(get_db)):
    """List all registered agents."""
    rows = await db.fetch_all(
        "SELECT * FROM agent_registry ORDER BY agent_name"
    )
    return {"agents": [dict(r) for r in rows]}


@router.post("/agents/spawn")
async def spawn_agent(req: SpawnRequest, spawner=Depends(get_spawner)):
    """Spawn a new specialist agent."""
    result = await spawner.spawn(
        agent_name=req.agent_name,
        role=req.role,
        description=req.description,
        specialty=req.specialty or None,
        proposal_id=req.proposal_id or None,
    )
    return result


@router.get("/agents/spawned")
async def list_spawned(db: Database = Depends(get_db)):
    """List all spawned specialist agents."""
    rows = await db.fetch_all(
        "SELECT * FROM spawned_agents ORDER BY created_at DESC"
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
