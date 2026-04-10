"""REST API for notebook CRUD and entry management."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import get_db, require_auth, require_feature
from odigos.core.resource_store import ResourceStore

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/notebooks",
    tags=["notebooks"],
    dependencies=[Depends(require_auth), Depends(require_feature("notebooks"))],
)

BACKUP_DIR = Path("data/notebooks")


# -- Request models --

_DEFAULT_MODES = {"general", "journal", "research", "creative", "meetings", "recipes", "music", "fitness", "finance", "travel"}
_COLLAB = Literal["read", "suggest", "active"]


class CreateNotebookRequest(BaseModel):
    title: str
    mode: str = "general"
    collaboration: _COLLAB = "read"
    share_with_agent: int = 0


class UpdateNotebookRequest(BaseModel):
    title: str | None = None
    mode: str | None = None
    collaboration: _COLLAB | None = None
    share_with_agent: int | None = None


class CreateEntryRequest(BaseModel):
    content: str
    entry_type: str = "user"
    status: str = "active"
    mood: str | None = None
    metadata: str | None = None
    quote: str | None = None
    trigger_type: str | None = None
    parent_id: str | None = None


class UpdateEntryRequest(BaseModel):
    content: str | None = None
    status: str | None = None
    mood: str | None = None
    metadata: str | None = None
    quote: str | None = None
    viewed_at: str | None = None


# -- Helpers --

def _notebooks_store(db) -> ResourceStore:
    return ResourceStore(db, "notebooks")


def _entries_store(db) -> ResourceStore:
    return ResourceStore(db, "notebook_entries", parent_key="notebook_id")


async def _get_entry_or_404(entry_store: ResourceStore, notebook_id: str, entry_id: str) -> dict:
    """Fetch an entry and verify it belongs to the specified notebook."""
    entry = await entry_store.get(entry_id)
    if not entry or entry["notebook_id"] != notebook_id:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


# Module-level lock map for per-notebook backup serialization
_backup_locks: dict[str, asyncio.Lock] = {}
_backup_locks_guard = asyncio.Lock()


async def _get_backup_lock(notebook_id: str) -> asyncio.Lock:
    """Get or create a lock for the given notebook_id."""
    async with _backup_locks_guard:
        if notebook_id not in _backup_locks:
            _backup_locks[notebook_id] = asyncio.Lock()
        return _backup_locks[notebook_id]


async def _backup_to_disk(db, notebook_id: str) -> None:
    """Export notebook + entries to markdown files in data/notebooks/.

    Writes TWO files:
    - {notebook_id}.md        : user's journal (user + agent_suggestion entries)
    - {notebook_id}.note.md   : agent review sidecar (agent entries, active + dead)

    Serialized per-notebook via asyncio.Lock to prevent concurrent file write collisions.
    """
    lock = await _get_backup_lock(notebook_id)
    async with lock:
        await _write_backup_files(db, notebook_id)


async def _write_backup_files(db, notebook_id: str) -> None:
    """Render and write both backup files. Must be called under the per-notebook lock."""
    store = _notebooks_store(db)
    entry_store = _entries_store(db)
    nb = await store.get(notebook_id)
    if not nb:
        return

    all_entries = await entry_store.list(
        notebook_id=notebook_id, order_by="created_at ASC",
    )

    user_entries = [
        e for e in all_entries
        if e.get("entry_type") in ("user", "agent_suggestion")
        and e.get("status") not in ("rejected",)
    ]

    agent_entries = [
        e for e in all_entries
        if e.get("entry_type") == "agent"
        and e.get("status") in ("active", "dead", "stale")
    ]

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Backup dir create failed for %s: %s", notebook_id[:8], exc)
        return

    # Write user journal file
    try:
        main_content = _render_user_journal(nb, user_entries)
        (BACKUP_DIR / f"{notebook_id}.md").write_text(main_content, encoding="utf-8")
        logger.debug("Backed up notebook %s to disk", notebook_id[:8])
    except OSError as exc:
        logger.warning("Notebook backup failed for %s: %s", notebook_id[:8], exc)

    # Write or delete agent sidecar file
    sidecar_path = BACKUP_DIR / f"{notebook_id}.note.md"
    try:
        if agent_entries:
            sidecar_content = _render_agent_sidecar(nb, notebook_id, agent_entries)
            sidecar_path.write_text(sidecar_content, encoding="utf-8")
        else:
            if sidecar_path.exists():
                sidecar_path.unlink()
    except OSError as exc:
        logger.warning("Notebook sidecar backup failed for %s: %s", notebook_id[:8], exc)


def _render_user_journal(nb: dict, user_entries: list[dict]) -> str:
    """Render the user's journal entries as markdown."""
    share_label = "yes" if nb["share_with_agent"] else "no"
    lines = [
        f"# {nb['title']}",
        f"Mode: {nb['mode']} | Collaboration: {nb['collaboration']} | Share: {share_label}",
        "",
    ]
    for entry in user_entries:
        lines.append("---")
        lines.append("")
        lines.append(f"## {entry['created_at']}")
        if entry.get("mood"):
            lines.append(f"Mood: {entry['mood']}")
        lines.append("")
        lines.append(entry["content"])
        lines.append("")
    return "\n".join(lines)


def _render_agent_sidecar(nb: dict, notebook_id: str, agent_entries: list[dict]) -> str:
    """Render the agent review sidecar with TOC + entries newest-first."""
    # Newest first
    sorted_entries = sorted(
        agent_entries, key=lambda e: e["created_at"], reverse=True
    )
    active_count = sum(1 for e in sorted_entries if e.get("status") == "active")
    dead_count = sum(1 for e in sorted_entries if e.get("status") == "dead")
    stale_count = sum(1 for e in sorted_entries if e.get("status") == "stale")
    latest_updated = sorted_entries[0]["created_at"] if sorted_entries else ""

    lines = [
        "---",
        f"file: data/notebooks/{notebook_id}.md",
        f"title: {nb['title']}",
        f"updated: {latest_updated}",
        f"entries: {len(sorted_entries)}",
        f"active: {active_count}",
        f"dead: {dead_count}",
    ]
    if stale_count:
        lines.append(f"stale: {stale_count}")
    lines.append("---")
    lines.append("")
    lines.append("## Contents")
    lines.append("")

    for i, entry in enumerate(sorted_entries, start=1):
        preview = (entry.get("content") or "")[:60].replace("\n", " ")
        time_str = entry["created_at"][:16].replace("T", " ")
        label = f"[{time_str} · agent] {preview}"
        if entry.get("status") == "dead":
            lines.append(f"{i}. ~~{label}~~ (dead)")
        elif entry.get("status") == "stale":
            lines.append(f"{i}. {label} _(stale)_")
        else:
            lines.append(f"{i}. {label}")
    lines.append("")

    for entry in sorted_entries:
        lines.append("---")
        lines.append("")
        trigger = entry.get("trigger_type") or "unknown"
        header = f"## {entry['created_at']} · agent · {trigger}"
        if entry.get("status") == "dead":
            header += " <dead/>"
        elif entry.get("status") == "stale":
            header += " <stale/>"
        lines.append(header)
        lines.append("")
        if entry.get("quote"):
            for quote_line in entry["quote"].splitlines():
                lines.append(f"> {quote_line}")
            lines.append("")
        lines.append(entry["content"])
        lines.append("")

    return "\n".join(lines)


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


@router.get("/{notebook_id}/entries")
async def list_entries(
    notebook_id: str,
    entry_type: str | None = None,
    include_dead: bool = False,
    db=Depends(get_db),
):
    """List entries with optional type and status filters."""
    nb_store = _notebooks_store(db)
    nb = await nb_store.get(notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")

    filters = {"notebook_id": notebook_id}
    if entry_type:
        filters["entry_type"] = entry_type

    entry_store = _entries_store(db)
    entries = await entry_store.list(order_by="created_at DESC", **filters)

    if not include_dead:
        entries = [e for e in entries if e.get("status") != "dead"]
    # Always exclude rejected entries from this endpoint
    entries = [e for e in entries if e.get("status") != "rejected"]

    unread_count = 0
    if entry_type == "agent":
        unread_count = sum(
            1 for e in entries
            if e.get("entry_type") == "agent"
            and e.get("status") == "active"
            and not e.get("viewed_at")
        )

    return {"entries": entries, "unread_count": unread_count}


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
        quote=body.quote,
        trigger_type=body.trigger_type,
        parent_id=body.parent_id,
    )
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)


@router.patch("/{notebook_id}/entries/{entry_id}")
async def update_entry(
    notebook_id: str, entry_id: str, body: UpdateEntryRequest, db=Depends(get_db),
):
    entry_store = _entries_store(db)
    await _get_entry_or_404(entry_store, notebook_id, entry_id)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    await entry_store.update(entry_id, **fields)
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)


@router.delete("/{notebook_id}/entries/{entry_id}")
async def delete_entry(notebook_id: str, entry_id: str, db=Depends(get_db)):
    entry_store = _entries_store(db)
    await _get_entry_or_404(entry_store, notebook_id, entry_id)
    await entry_store.delete(entry_id)
    await _backup_to_disk(db, notebook_id)
    return {"deleted": True}


@router.post("/{notebook_id}/entries/{entry_id}/view")
async def mark_entry_viewed(
    notebook_id: str, entry_id: str, db=Depends(get_db),
):
    """Mark an entry as viewed by the user."""
    entry_store = _entries_store(db)
    await _get_entry_or_404(entry_store, notebook_id, entry_id)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await entry_store.update(entry_id, viewed_at=now)
    return {"ok": True}


@router.post("/{notebook_id}/mark-all-viewed")
async def mark_all_entries_viewed(
    notebook_id: str,
    entry_type: str | None = None,
    db=Depends(get_db),
):
    """Mark all unviewed entries (optionally filtered by type) as viewed."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # Count first, then update
    count_sql = (
        "SELECT COUNT(*) as c FROM notebook_entries "
        "WHERE notebook_id = ? AND viewed_at IS NULL AND status = 'active'"
    )
    count_params: list = [notebook_id]
    if entry_type:
        count_sql += " AND entry_type = ?"
        count_params.append(entry_type)

    count_row = await db.fetch_one(count_sql, tuple(count_params))
    marked = count_row["c"] if count_row else 0

    update_sql = (
        "UPDATE notebook_entries SET viewed_at = ? "
        "WHERE notebook_id = ? AND viewed_at IS NULL AND status = 'active'"
    )
    update_params: list = [now, notebook_id]
    if entry_type:
        update_sql += " AND entry_type = ?"
        update_params.append(entry_type)

    await db.execute(update_sql, tuple(update_params))
    return {"ok": True, "marked": marked}


@router.post("/{notebook_id}/entries/{entry_id}/accept")
async def accept_suggestion(notebook_id: str, entry_id: str, db=Depends(get_db)):
    entry_store = _entries_store(db)
    entry = await _get_entry_or_404(entry_store, notebook_id, entry_id)
    if entry["entry_type"] != "agent_suggestion":
        raise HTTPException(status_code=400, detail="Entry is not an agent suggestion")
    await entry_store.update(entry_id, status="accepted", entry_type="agent")
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)


@router.post("/{notebook_id}/entries/{entry_id}/reject")
async def reject_suggestion(notebook_id: str, entry_id: str, db=Depends(get_db)):
    entry_store = _entries_store(db)
    entry = await _get_entry_or_404(entry_store, notebook_id, entry_id)
    if entry["entry_type"] != "agent_suggestion":
        raise HTTPException(status_code=400, detail="Entry is not an agent suggestion")
    await entry_store.update(entry_id, status="rejected")
    await _backup_to_disk(db, notebook_id)
    return await entry_store.get(entry_id)
