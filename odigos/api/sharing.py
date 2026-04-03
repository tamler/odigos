"""Public sharing endpoints for notebooks and kanban boards."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from odigos.api.deps import get_db, get_settings, require_auth

# Authenticated endpoints for managing shares
router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

# Public endpoints (no auth)
public_router = APIRouter(prefix="/shared")


def _generate_token() -> str:
    return secrets.token_hex(16)


# -- Notebook sharing --

@router.post("/notebooks/{notebook_id}/share")
async def share_notebook(notebook_id: str, db=Depends(get_db)):
    """Generate a public share link for a notebook."""
    notebook = await db.fetch_one("SELECT id, share_token FROM notebooks WHERE id = ?", (notebook_id,))
    if not notebook:
        raise HTTPException(status_code=404, detail="Notebook not found")

    token = notebook["share_token"]
    if not token:
        token = _generate_token()
        await db.execute("UPDATE notebooks SET share_token = ? WHERE id = ?", (token, notebook_id))

    return {"share_token": token, "url": f"/shared/notebook/{token}"}


@router.delete("/notebooks/{notebook_id}/share")
async def unshare_notebook(notebook_id: str, db=Depends(get_db)):
    """Revoke the public share link for a notebook."""
    await db.execute("UPDATE notebooks SET share_token = NULL WHERE id = ?", (notebook_id,))
    return {"status": "revoked"}


@public_router.get("/notebook/{token}")
async def get_shared_notebook(token: str, db=Depends(get_db), settings=Depends(get_settings)):
    """Public read-only view of a shared notebook."""
    notebook = await db.fetch_one(
        "SELECT id, title, mode FROM notebooks WHERE share_token = ?", (token,)
    )
    if not notebook:
        return JSONResponse(status_code=404, content={"detail": "Shared link not found or revoked"})

    entries = await db.fetch_all(
        "SELECT id, content, entry_type, mood, created_at FROM notebook_entries "
        "WHERE notebook_id = ? AND status = 'active' ORDER BY created_at DESC",
        (notebook["id"],),
    )

    return {
        "title": notebook["title"],
        "mode": notebook["mode"],
        "agent_name": settings.agent.name,
        "entries": [dict(e) for e in entries],
    }


# -- Kanban sharing --

@router.post("/kanban/boards/{board_id}/share")
async def share_board(board_id: str, db=Depends(get_db)):
    """Generate a public share link for a kanban board."""
    board = await db.fetch_one("SELECT id, share_token FROM kanban_boards WHERE id = ?", (board_id,))
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    token = board["share_token"]
    if not token:
        token = _generate_token()
        await db.execute("UPDATE kanban_boards SET share_token = ? WHERE id = ?", (token, board_id))

    return {"share_token": token, "url": f"/shared/board/{token}"}


@router.delete("/kanban/boards/{board_id}/share")
async def unshare_board(board_id: str, db=Depends(get_db)):
    """Revoke the public share link for a kanban board."""
    await db.execute("UPDATE kanban_boards SET share_token = NULL WHERE id = ?", (board_id,))
    return {"status": "revoked"}


@public_router.get("/board/{token}")
async def get_shared_board(token: str, db=Depends(get_db), settings=Depends(get_settings)):
    """Public read-only view of a shared kanban board."""
    board = await db.fetch_one(
        "SELECT id, title, description FROM kanban_boards WHERE share_token = ?", (token,)
    )
    if not board:
        return JSONResponse(status_code=404, content={"detail": "Shared link not found or revoked"})

    columns = await db.fetch_all(
        "SELECT id, title, position FROM kanban_columns WHERE board_id = ? ORDER BY position",
        (board["id"],),
    )
    cards = await db.fetch_all(
        "SELECT id, column_id, title, description, position, priority, due_at "
        "FROM kanban_cards WHERE board_id = ? ORDER BY position",
        (board["id"],),
    )

    return {
        "title": board["title"],
        "description": board["description"],
        "agent_name": settings.agent.name,
        "columns": [dict(c) for c in columns],
        "cards": [dict(c) for c in cards],
    }
