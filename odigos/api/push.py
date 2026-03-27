"""Push notification subscription management."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from odigos.api.deps import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push")


@router.get("/vapid-key", dependencies=[Depends(require_auth)])
async def get_vapid_key(request: Request):
    """Return the VAPID public key for push subscription."""
    vapid_keys = getattr(request.app.state, "vapid_keys", {})
    public_key = vapid_keys.get("public_key", "")
    if not public_key:
        return JSONResponse(
            status_code=404,
            content={"detail": "Push notifications not configured"},
        )
    return {"public_key": public_key}


@router.post("/subscribe", dependencies=[Depends(require_auth)])
async def subscribe(request: Request):
    """Store a push subscription for the current user."""
    db = request.app.state.db
    body = await request.json()
    subscription = body.get("subscription")
    if not subscription:
        return JSONResponse(
            status_code=400,
            content={"detail": "No subscription provided"},
        )

    await db.execute(
        """
        INSERT OR REPLACE INTO push_subscriptions
            (endpoint, subscription_json)
        VALUES (?, ?)
        """,
        (subscription.get("endpoint", ""), json.dumps(subscription)),
    )
    logger.info("Push subscription stored")
    return {"status": "subscribed"}


@router.delete("/subscribe", dependencies=[Depends(require_auth)])
async def unsubscribe(request: Request):
    """Remove a push subscription."""
    db = request.app.state.db
    body = await request.json()
    endpoint = body.get("endpoint", "")
    if endpoint:
        await db.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ?",
            (endpoint,),
        )
    return {"status": "unsubscribed"}
