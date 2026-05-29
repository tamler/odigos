"""Platform SSO: optional /auth/callback for odigos.one managed login."""

import os
import secrets
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from odigos.api.deps import get_db, get_settings
from odigos.api.auth import (
    SESSION_COOKIE,
    _create_session,
    _hash_password,
    _SESSION_MAX_AGE,
)

router = APIRouter(tags=["platform-auth"])

PLATFORM_URL = os.environ.get("ODIGOS_PLATFORM_URL", "").rstrip("/")
PLATFORM_API_KEY = os.environ.get("ODIGOS_PLATFORM_API_KEY", "")


@router.get("/auth/callback")
async def platform_auth_callback(
    token: str,
    request: Request,
    db=Depends(get_db),
    settings=Depends(get_settings),
):
    if not PLATFORM_URL:
        raise HTTPException(404, "Platform integration not configured")
    if not PLATFORM_API_KEY:
        raise HTTPException(500, "Platform API key not configured")

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{PLATFORM_URL}/api/v1/auth/validate-token",
            json={"token": token},
            headers={"Authorization": f"Bearer {PLATFORM_API_KEY}"},
        )

    if r.status_code != 200:
        return RedirectResponse(f"{PLATFORM_URL}/login")

    platform_user = r.json()
    email = platform_user.get("email", "")
    name = platform_user.get("name", email)

    if not email:
        raise HTTPException(400, "Platform did not provide an email")

    local_user = await db.fetch_one(
        "SELECT id, username FROM users WHERE email = ?", (email,)
    )

    if not local_user:
        user_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        random_password = _hash_password(secrets.token_hex(32))
        await db.execute(
            "INSERT INTO users (id, username, password_hash, display_name, email, must_change_password, created_at, last_login_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (user_id, email, random_password, name, email, now, now),
        )
        username = email
    else:
        user_id = local_user["id"]
        username = local_user["username"]
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?", (now, user_id)
        )

    secret = settings.session_secret
    session_token = _create_session(secret, {
        "user_id": user_id,
        "username": username,
        "must_change_password": False,
    })

    response = RedirectResponse("/")
    secure = (settings.deployment.mode == "hosted") or (
        request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    )
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=_SESSION_MAX_AGE,
    )
    return response
