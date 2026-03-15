"""API endpoints for listing, reading, and editing prompt files."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import require_api_key

router = APIRouter(prefix="/api/prompts", tags=["prompts"], dependencies=[Depends(require_api_key)])

# Mutable for test patching
_PROMPT_DIRS: dict[str, str] = {
    "agent": "data/agent",
    "prompts": "data/prompts",
}


class PromptUpdate(BaseModel):
    content: str


@router.get("")
async def list_prompts():
    """List all prompt files from both directories."""
    results = []
    for directory, dir_path in _PROMPT_DIRS.items():
        p = Path(dir_path)
        if not p.exists():
            continue
        for f in sorted(p.glob("*.md")):
            results.append({
                "name": f.stem,
                "directory": directory,
                "path": str(f),
            })
    return results


@router.get("/{directory}/{name}")
async def read_prompt(directory: str, name: str):
    """Read a prompt file's content."""
    if directory not in _PROMPT_DIRS:
        raise HTTPException(status_code=400, detail=f"Invalid directory: {directory}. Must be one of: {list(_PROMPT_DIRS.keys())}")

    path = Path(_PROMPT_DIRS[directory]) / f"{name}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Prompt not found: {directory}/{name}")

    return {"name": name, "directory": directory, "content": path.read_text()}


@router.put("/{directory}/{name}")
async def update_prompt(directory: str, name: str, body: PromptUpdate):
    """Update a prompt file's content."""
    if directory not in _PROMPT_DIRS:
        raise HTTPException(status_code=400, detail=f"Invalid directory: {directory}")

    dir_path = Path(_PROMPT_DIRS[directory])
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{name}.md"
    path.write_text(body.content)

    return {"name": name, "directory": directory, "status": "updated"}
