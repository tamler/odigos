"""Auth API: setup, login, logout, change-password, status, me."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from odigos.api.deps import get_db, get_settings
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "odigos_session"


def _check_csrf(request: Request) -> None:
    if not request.headers.get("X-Requested-With"):
        raise HTTPException(status_code=403, detail="Missing CSRF header")


class SetupRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    new_password: str


class ResetPasswordRequest(BaseModel):
    username: str
    new_password: str
_SESSION_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds
_MIN_PASSWORD_LENGTH = 8


# ---------------------------------------------------------------------------
# Helpers (exported for deps.py and ws.py)
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Hash a password with bcrypt (12 rounds)."""
    salt = _bcrypt.gensalt(rounds=12)
    return _bcrypt.hashpw(password.encode(), salt).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return _bcrypt.checkpw(password.encode(), password_hash.encode())


def _create_session(secret: str, payload: dict) -> str:
    """Create a signed session token."""
    s = URLSafeTimedSerializer(secret)
    return s.dumps(payload)


def _validate_session(secret: str, token: str) -> dict | None:
    """Validate and decode a session token. Returns payload or None."""
    if not secret or not token:
        return None
    s = URLSafeTimedSerializer(secret)
    try:
        return s.loads(token, max_age=_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    """Set the session cookie on a response."""
    secure = request.url.scheme == "https"
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=_SESSION_MAX_AGE,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def auth_status(request: Request, db=Depends(get_db), settings=Depends(get_settings)):
    """Return auth status -- no auth required."""
    row = await db.fetch_one("SELECT COUNT(*) as count FROM users")
    has_users = row["count"] > 0 if row else False

    authenticated = False
    must_change = False

    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        secret = settings.session_secret
        session = _validate_session(secret, cookie)
        if session:
            authenticated = True
            must_change = session.get("must_change_password", False)

    return {
        "setup_required": not has_users,
        "authenticated": authenticated,
        "must_change_password": must_change,
    }


@router.post("/setup")
async def auth_setup(body: SetupRequest, request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)):
    """Create the first user. Blocked if any user already exists."""
    _check_csrf(request)
    row = await db.fetch_one("SELECT COUNT(*) as count FROM users")
    if row and row["count"] > 0:
        raise HTTPException(status_code=409, detail="Setup already completed")

    username = body.username.strip()
    password = body.password
    display_name = body.display_name

    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {_MIN_PASSWORD_LENGTH} characters",
        )

    user_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    password_hash = _hash_password(password)

    await db.execute(
        "INSERT INTO users (id, username, password_hash, display_name, must_change_password, created_at, last_login_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, username, password_hash, display_name, 0, now, now),
    )

    secret = settings.session_secret
    token = _create_session(secret, {
        "user_id": user_id,
        "username": username,
        "must_change_password": False,
    })
    _set_session_cookie(response, request, token)

    return {"user_id": user_id, "username": username}


@router.post("/login")
async def auth_login(body: LoginRequest, request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)):
    """Validate credentials and set session cookie."""
    _check_csrf(request)
    username = body.username.strip()
    password = body.password

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    user = await db.fetch_one(
        "SELECT id, username, password_hash, must_change_password FROM users WHERE username = ?",
        (username,),
    )
    if not user or not _verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE users SET last_login_at = ? WHERE id = ?",
        (now, user["id"]),
    )

    must_change = bool(user["must_change_password"])
    secret = settings.session_secret
    token = _create_session(secret, {
        "user_id": user["id"],
        "username": user["username"],
        "must_change_password": must_change,
    })
    _set_session_cookie(response, request, token)

    return {"must_change_password": must_change}


@router.post("/logout")
async def auth_logout(request: Request, response: Response):
    """Clear the session cookie. Redirect to platform if managed."""
    _check_csrf(request)
    response.delete_cookie(key=SESSION_COOKIE)
    platform_url = os.environ.get("ODIGOS_PLATFORM_URL", "").rstrip("/")
    if platform_url:
        return RedirectResponse(f"{platform_url}/api/v1/auth/logout", status_code=303)
    return {"status": "ok"}


@router.post("/change-password")
async def auth_change_password(body: ChangePasswordRequest, request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)):
    """Change password for the authenticated user (session required)."""
    _check_csrf(request)
    secret = settings.session_secret
    cookie = request.cookies.get(SESSION_COOKIE)
    session = _validate_session(secret, cookie)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    new_password = body.new_password
    if len(new_password) < _MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {_MIN_PASSWORD_LENGTH} characters",
        )

    user_id = session["user_id"]

    user = await db.fetch_one("SELECT id FROM users WHERE id = ?", (user_id,))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_hash = _hash_password(new_password)
    await db.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
        (new_hash, user_id),
    )

    # Reissue session with must_change_password cleared
    token = _create_session(secret, {
        "user_id": session["user_id"],
        "username": session["username"],
        "must_change_password": False,
    })
    _set_session_cookie(response, request, token)

    return {"status": "ok"}


@router.post("/reset-password")
async def auth_reset_password(body: ResetPasswordRequest, request: Request, db=Depends(get_db), settings=Depends(get_settings)):
    """Reset a user's password. Requires API key (admin only)."""
    _check_csrf(request)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer ") or not settings.api_key:
        raise HTTPException(status_code=401, detail="API key required")
    import hmac
    token = auth_header.split(" ", 1)[1]
    if not hmac.compare_digest(token.encode(), settings.api_key.encode()):
        raise HTTPException(status_code=403, detail="Invalid API key")

    username = body.username.strip()
    new_password = body.new_password

    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if len(new_password) < _MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {_MIN_PASSWORD_LENGTH} characters",
        )

    user = await db.fetch_one("SELECT id FROM users WHERE username = ?", (username,))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_hash = _hash_password(new_password)
    await db.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
        (new_hash, user["id"]),
    )
    return {"status": "ok", "must_change_password": True}


@router.get("/me")
async def auth_me(request: Request, db=Depends(get_db), settings=Depends(get_settings)):
    """Return info about the currently authenticated user (session required)."""
    secret = settings.session_secret
    cookie = request.cookies.get(SESSION_COOKIE)
    session = _validate_session(secret, cookie)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = await db.fetch_one(
        "SELECT id, username, display_name, must_change_password, created_at, last_login_at "
        "FROM users WHERE id = ?",
        (session["user_id"],),
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    profile = None
    try:
        profile_row = await db.fetch_one(
            "SELECT communication_style, expertise_areas, preferences, "
            "recurring_topics, correction_patterns, summary, last_analyzed_at "
            "FROM user_profile WHERE id = 'owner'"
        )
        if profile_row:
            profile = {
                "communication_style": profile_row["communication_style"] or "",
                "expertise_areas": profile_row["expertise_areas"] or "",
                "preferences": profile_row["preferences"] or "",
                "recurring_topics": profile_row["recurring_topics"] or "",
                "correction_patterns": profile_row["correction_patterns"] or "",
                "summary": profile_row["summary"] or "",
                "last_analyzed_at": profile_row["last_analyzed_at"],
            }
    except Exception:
        pass

    return {
        "user_id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "must_change_password": bool(user["must_change_password"]),
        "created_at": user["created_at"],
        "last_login_at": user["last_login_at"],
        "profile": profile,
    }


@router.get("/facts")
async def get_facts(request: Request, db=Depends(get_db), settings=Depends(get_settings)):
    """Return all stored user facts (session required)."""
    secret = settings.session_secret
    cookie = request.cookies.get(SESSION_COOKIE)
    session = _validate_session(secret, cookie)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    rows = await db.fetch_all(
        "SELECT * FROM user_facts ORDER BY updated_at DESC"
    )
    return {"facts": [dict(row) for row in rows]}


@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: str, request: Request, db=Depends(get_db), settings=Depends(get_settings)):
    """Delete a user fact by ID (session required)."""
    secret = settings.session_secret
    cookie = request.cookies.get(SESSION_COOKIE)
    session = _validate_session(secret, cookie)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    await db.execute("DELETE FROM user_facts WHERE id = ?", (fact_id,))
    return {"status": "ok"}


class ProfileUpdate(BaseModel):
    communication_style: str | None = None
    expertise_areas: str | None = None
    preferences: str | None = None
    recurring_topics: str | None = None
    correction_patterns: str | None = None
    summary: str | None = None


@router.put("/profile")
async def update_profile(body: ProfileUpdate, request: Request, db=Depends(get_db), settings=Depends(get_settings)):
    """Update the owner's learned profile fields (session required)."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")
    secret = settings.session_secret
    session = _validate_session(secret, cookie)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    updates = []
    params: list[str] = []
    for field in (
        "communication_style",
        "expertise_areas",
        "preferences",
        "recurring_topics",
        "correction_patterns",
        "summary",
    ):
        value = getattr(body, field)
        if value is not None:
            updates.append(f"{field} = ?")
            params.append(value)

    if updates:
        params.append("owner")
        await db.execute(
            f"UPDATE user_profile SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )

    return {"status": "ok"}
