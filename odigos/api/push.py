"""Push notification subscription management."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from odigos.api.deps import get_db, get_vapid_keys, require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push")


@router.get("/vapid-key", dependencies=[Depends(require_auth)])
async def get_vapid_key(vapid_keys: dict = Depends(get_vapid_keys)):
    """Return the VAPID public key for push subscription."""
    public_key = (vapid_keys or {}).get("public_key", "")
    if not public_key:
        return JSONResponse(
            status_code=404,
            content={"detail": "Push notifications not configured"},
        )
    return {"public_key": public_key}


@router.post("/subscribe", dependencies=[Depends(require_auth)])
async def subscribe(request: Request, db=Depends(get_db)):
    """Store a push subscription for the current user."""
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
async def unsubscribe(request: Request, db=Depends(get_db)):
    """Remove a push subscription."""
    body = await request.json()
    endpoint = body.get("endpoint", "")
    if endpoint:
        await db.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ?",
            (endpoint,),
        )
    return {"status": "unsubscribed"}
