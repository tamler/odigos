"""REST API for contact card and feed entry management.

Dashboard-only endpoints (require global API key, not card keys).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from odigos.api.deps import get_db, require_api_key

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


class GenerateCardRequest(BaseModel):
    type: str
    expires_in_days: int | None = None


class ImportCardRequest(BaseModel):
    card_data: str


@router.get("/cards/issued")
async def list_issued(request: Request):
    card_manager = request.app.state.card_manager
    cards = await card_manager.list_issued()
    return {"cards": cards}


@router.get("/cards/accepted")
async def list_accepted(request: Request):
    card_manager = request.app.state.card_manager
    cards = await card_manager.list_accepted()
    return {"cards": cards}


@router.post("/cards/generate")
async def generate_card(body: GenerateCardRequest, request: Request):
    card_manager = request.app.state.card_manager
    card = await card_manager.generate_card(
        card_type=body.type,
        expires_in_days=body.expires_in_days,
    )
    return {
        "card": card,
        "yaml": card_manager.card_to_yaml(card),
        "compact": card_manager.card_to_compact(card),
    }


@router.post("/cards/import")
async def import_card(body: ImportCardRequest, request: Request):
    card_manager = request.app.state.card_manager
    result = await card_manager.import_card(body.card_data)
    return result


@router.post("/cards/issued/{card_key}/revoke")
async def revoke_issued(card_key: str, request: Request):
    card_manager = request.app.state.card_manager
    await card_manager.revoke_issued(card_key)
    return {"status": "ok"}


@router.post("/cards/accepted/{card_id}/revoke")
async def revoke_accepted(card_id: str, request: Request):
    card_manager = request.app.state.card_manager
    await card_manager.revoke_accepted(card_id)
    return {"status": "ok"}


@router.post("/cards/accepted/{card_id}/mute")
async def mute_accepted(card_id: str, request: Request):
    card_manager = request.app.state.card_manager
    await card_manager.mute_accepted(card_id)
    return {"status": "ok"}


@router.post("/cards/accepted/{card_id}/unmute")
async def unmute_accepted(card_id: str, request: Request):
    card_manager = request.app.state.card_manager
    await card_manager.unmute_accepted(card_id)
    return {"status": "ok"}


@router.get("/feed/entries")
async def list_feed_entries(db=Depends(get_db)):
    entries = await db.fetch_all(
        "SELECT * FROM feed_entries ORDER BY created_at DESC LIMIT 200"
    )
    return {"entries": [dict(e) for e in entries]}


@router.delete("/feed/entries/{entry_id}")
async def delete_feed_entry(entry_id: str, db=Depends(get_db)):
    await db.execute("DELETE FROM feed_entries WHERE id = ?", (entry_id,))
    return {"status": "ok"}
