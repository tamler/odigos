"""REST API for notebook CRUD and entry management."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import get_db, require_feature
from odigos.core.resource_store import ResourceStore

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/notebooks",
    tags=["notebooks"],
    dependencies=[Depends(require_feature("notebooks"))],
)

BACKUP_DIR = Path("data/notebooks")


# -- Request models --

class CreateNotebookRequest(BaseModel):
    title: str
    mode: str = "general"
    collaboration: str = "read"
    share_with_agent: int = 0


class UpdateNotebookRequest(BaseModel):
    title: str | None = None
    mode: str | None = None
    collaboration: str | None = None
    share_with_agent: int | None = None


class CreateEntryRequest(BaseModel):
    content: str
    entry_type: str = "user"
    status: str = "active"
    mood: str | None = None
    metadata: str | None = None


class UpdateEntryRequest(BaseModel):
    content: str | None = None
    status: str | None = None
    mood: str | None = None
    metadata: str | None = None


# -- Helpers --

def _notebooks_store(db) -> ResourceStore:
    return ResourceStore(db, "notebooks")


def _entries_store(db) -> ResourceStore:
    return ResourceStore(db, "notebook_entries", parent_key="notebook_id")


async def _backup_to_disk(db, notebook_id: str) -> None:
    """Export notebook + entries to a markdown file in data/notebooks/."""
    store = _notebooks_store(db)
    entry_store = _entries_store(db)
    nb = await store.get(notebook_id)
    if not nb:
        return

    entries = await entry_store.list(
        notebook_id=notebook_id, order_by="created_at ASC",
    )

    share_label = "yes" if nb["share_with_agent"] else "no"
    lines = [
        f"# {nb['title']}",
        f"Mode: {nb['mode']} | Collaboration: {nb['collaboration']} | Share: {share_label}",
        "",
    ]

    for entry in entries:
        if entry["status"] in ("rejected",):
            continue
        lines.append("---")
        lines.append("")
        lines.append(f"## {entry['created_at']}")
        if entry.get("mood"):
            lines.append(f"Mood: {entry['mood']}")
        lines.append("")
        lines.append(entry["content"])
        lines.append("")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    (BACKUP_DIR / f"{notebook_id}.md").write_text("\n".join(lines), encoding="utf-8")
    logger.debug("Backed up notebook %s to disk", notebook_id[:8])


# -- Endpoints --

@router.get("")
async def list_notebooks(db=Depends(get_db)):
    store = _notebooks_store(db)
    notebooks = await store.list()
    return {"notebooks": notebooks}


@router.post("", status_code=201)
async def create_notebook(body: CreateNotebookRequest, db=Depends(get_db)):
    store = _notebooks_store(db)
    nb_id = await store.create(
        title=body.title,
        mode=body.mode,
        collaboration=body.collaboration,
        share_with_agent=body.share_with_agent,
    )
    return await store.get(nb_id)


@router.get("/{notebook_id}")
async def get_notebook(notebook_id: str, db=Depends(get_db)):
    store = _notebooks_store(db)
    nb = await store.get(notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")
    entry_store = _entries_store(db)
    entries = await entry_store.list(
        notebook_id=notebook_id, order_by="created_at DESC",
    )
    return {**nb, "entries": entries}


@router.patch("/{notebook_id}")
async def update_notebook(
    notebook_id: str, body: UpdateNotebookRequest, db=Depends(get_db),
):
    store = _notebooks_store(db)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = await store.update(notebook_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Notebook not found")
    return await store.get(notebook_id)


@router.delete("/{notebook_id}")
async def delete_notebook(notebook_id: str, db=Depends(get_db)):
    store = _notebooks_store(db)
    deleted = await store.delete(notebook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Notebook not found")
    backup_file = BACKUP_DIR / f"{notebook_id}.md"
    if backup_file.exists():
        backup_file.unlink()
    return {"deleted": True}


# -- Entry endpoints --

@router.post("/{notebook_id}/entries", status_code=201)
async def create_entry(
    notebook_id: str, body: CreateEntryRequest, db=Depends(get_db),
):
    nb_store = _notebooks_store(db)
    nb = await nb_store.get(notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")

    entry_store = _entries_store(db)
    entry_id = await entry_store.create(
        notebook_id=notebook_id,
        content=body.content,
        entry_type=body.entry_type,
        status=body.status,
        mood=body.mood,
        metadata=body.metadata,
    )
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)


@router.patch("/{notebook_id}/entries/{entry_id}")
async def update_entry(
    notebook_id: str, entry_id: str, body: UpdateEntryRequest, db=Depends(get_db),
):
    entry_store = _entries_store(db)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = await entry_store.update(entry_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Entry not found")
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)


@router.delete("/{notebook_id}/entries/{entry_id}")
async def delete_entry(notebook_id: str, entry_id: str, db=Depends(get_db)):
    entry_store = _entries_store(db)
    deleted = await entry_store.delete(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    await _backup_to_disk(db, notebook_id)
    return {"deleted": True}


@router.post("/{notebook_id}/entries/{entry_id}/accept")
async def accept_suggestion(notebook_id: str, entry_id: str, db=Depends(get_db)):
    entry_store = _entries_store(db)
    entry = await entry_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry["entry_type"] != "agent_suggestion":
        raise HTTPException(status_code=400, detail="Entry is not an agent suggestion")
    await entry_store.update(entry_id, status="accepted", entry_type="agent")
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)


@router.post("/{notebook_id}/entries/{entry_id}/reject")
async def reject_suggestion(notebook_id: str, entry_id: str, db=Depends(get_db)):
    entry_store = _entries_store(db)
    entry = await entry_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry["entry_type"] != "agent_suggestion":
        raise HTTPException(status_code=400, detail="Entry is not an agent suggestion")
    await entry_store.update(entry_id, status="rejected")
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)
