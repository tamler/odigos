"""Skills CRUD API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import get_skill_registry, require_auth

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)


class SkillCreate(BaseModel):
    name: str
    description: str
    system_prompt: str
    tools: list[str] = []
    complexity: str = "standard"


class SkillUpdate(BaseModel):
    description: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    complexity: str | None = None


@router.get("/skills")
async def list_skills(registry=Depends(get_skill_registry)):
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "tools": s.tools,
                "complexity": s.complexity,
                "system_prompt": s.system_prompt,
                "builtin": s.builtin,
            }
            for s in registry.list()
        ]
    }


@router.get("/skills/{name}")
async def get_skill(name: str, registry=Depends(get_skill_registry)):
    skill = registry.get(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return {
        "name": skill.name,
        "description": skill.description,
        "tools": skill.tools,
        "complexity": skill.complexity,
        "system_prompt": skill.system_prompt,
        "builtin": skill.builtin,
    }


@router.post("/skills")
async def create_skill(body: SkillCreate, registry=Depends(get_skill_registry)):
    try:
        skill = registry.create(
            name=body.name,
            description=body.description,
            system_prompt=body.system_prompt,
            tools=body.tools,
            complexity=body.complexity,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": skill.name, "status": "created"}


@router.put("/skills/{name}")
async def update_skill(
    name: str, body: SkillUpdate, registry=Depends(get_skill_registry)
):
    try:
        skill = registry.update(
            name=name,
            description=body.description,
            instructions=body.system_prompt,
            tools=body.tools,
            complexity=body.complexity,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": skill.name, "status": "updated"}


@router.delete("/skills/{name}")
async def delete_skill(name: str, registry=Depends(get_skill_registry)):
    skill = registry.get(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    if skill.builtin:
        raise HTTPException(status_code=400, detail="Cannot delete built-in skills")
    registry.delete(name)
    return {"name": name, "status": "deleted"}
