"""Auth API: setup, login, logout, change-password, status, me."""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from odigos.api.deps import get_db, get_settings
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

router = APIRouter(prefix="/api/auth", tags=["auth"])

logger = logging.getLogger(__name__)

SESSION_COOKIE = "odigos_session"

# Permissive email regex — good enough to catch typos, not a full RFC 5322 parser.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _check_csrf(request: Request) -> None:
    if not request.headers.get("X-Requested-With"):
        raise HTTPException(status_code=403, detail="Missing CSRF header")


def _validate_email(email: str) -> str:
    """Strip and validate an email address. Raises HTTPException on failure."""
    addr = (email or "").strip()
    if not addr:
        raise HTTPException(status_code=400, detail="Email is required")
    if len(addr) > 254:
        raise HTTPException(status_code=400, detail="Email is too long")
    if not _EMAIL_RE.match(addr):
        raise HTTPException(status_code=400, detail="Invalid email format")
    return addr


class SetupRequest(BaseModel):
    username: str
    email: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str = ""
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


# Precomputed once at import: used on the no-user login path so an unknown
# username still incurs a bcrypt verify, preventing timing-based enumeration.
_DUMMY_HASH = _hash_password("invalid-placeholder")


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


async def _validate_session_with_epoch(secret: str, token: str | None, db) -> dict | None:
    """Validate a session token and confirm its epoch matches the user's current epoch."""
    session = _validate_session(secret, token)
    if not session:
        return None
    row = await db.fetch_one(
        "SELECT session_epoch FROM users WHERE id = ?", (session["user_id"],)
    )
    if not row or session.get("epoch", 0) != row["session_epoch"]:
        return None
    return session


def _set_session_cookie(response: Response, request: Request, token: str, force_secure: bool = False) -> None:
    """Set the session cookie. Honors X-Forwarded-Proto behind a TLS proxy.

    force_secure pins Secure=True regardless of the (spoofable) header — used in
    hosted mode where the app is always behind Caddy TLS.
    """
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    secure = force_secure or proto == "https"
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
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
        session = await _validate_session_with_epoch(secret, cookie, db)
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

    username = body.username.strip().lower()
    password = body.password
    display_name = body.display_name
    email = _validate_email(body.email)

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
        "INSERT INTO users (id, username, email, password_hash, display_name, must_change_password, created_at, last_login_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, username, email, password_hash, display_name, 0, now, now),
    )

    secret = settings.session_secret
    token = _create_session(secret, {
        "user_id": user_id,
        "username": username,
        "must_change_password": False,
        "epoch": 0,
    })
    _set_session_cookie(response, request, token, force_secure=(settings.deployment.mode == "hosted"))

    return {"user_id": user_id, "username": username}


@router.post("/login")
async def auth_login(body: LoginRequest, request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)):
    """Validate credentials and set session cookie."""
    _check_csrf(request)
    username = body.username.strip().lower()
    password = body.password

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    user = await db.fetch_one(
        "SELECT id, username, password_hash, must_change_password, session_epoch FROM users WHERE username = ?",
        (username,),
    )
    if not user:
        # Run a dummy verify so a missing username costs the same as a wrong
        # password — avoids leaking account existence via response timing.
        _verify_password(password, _DUMMY_HASH)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not _verify_password(password, user["password_hash"]):
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
        "epoch": user["session_epoch"],
    })
    _set_session_cookie(response, request, token, force_secure=(settings.deployment.mode == "hosted"))

    return {"must_change_password": must_change}


async def _exchange_sso_token(token: str, request: Request, db, settings) -> RedirectResponse:
    """Verify a platform JWT and mint an agent session cookie on a redirect.

    Shared by both the POST (preferred) and legacy GET SSO channels. Verifies
    the JWT (HS256, shared secret with platform), looks up the agent's local
    user by the email in the `sub` claim, sets a session cookie, and returns a
    302 redirect to the dashboard root. Raises HTTPException on any failure.
    """
    import jwt as _jwt
    from datetime import datetime

    secret = settings.platform_jwt_secret
    audience = settings.platform_audience
    if not secret or not audience:
        raise HTTPException(503, "Platform SSO not configured on this agent")

    try:
        claims = _jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=audience,
            options={"require": ["sub", "exp", "aud", "iat"]},
        )
    except _jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid SSO token: {type(e).__name__}")

    email = (claims.get("sub") or "").strip().lower()
    if not email:
        raise HTTPException(401, "SSO token missing email")

    user = await db.fetch_one(
        "SELECT id, username, must_change_password, session_epoch FROM users WHERE LOWER(email) = ?",
        (email,),
    )
    if not user:
        if not settings.sso_auto_provision:
            raise HTTPException(403, f"No agent account for {email} — sign up locally first")
        # Auto-provision: derive username from email local-part, dedupe on collision
        base_username = re.sub(r"[^a-z0-9_]", "", email.split("@")[0].lower()) or "user"
        username = base_username
        suffix = 1
        while await db.fetch_one("SELECT 1 FROM users WHERE username = ?", (username,)):
            suffix += 1
            username = f"{base_username}{suffix}"
        user_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        # Random password the user never sees — SSO is their only login path
        password_hash = _hash_password(uuid.uuid4().hex)
        display_name = (claims.get("name") or "").strip() or username
        await db.execute(
            "INSERT INTO users (id, username, email, password_hash, display_name, must_change_password, created_at, last_login_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, email, password_hash, display_name, 0, now, now),
        )
        user = {"id": user_id, "username": username, "must_change_password": 0, "session_epoch": 0}

    now = datetime.now(timezone.utc).isoformat()
    await db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user["id"]))

    sess_token = _create_session(settings.session_secret, {
        "user_id": user["id"],
        "username": user["username"],
        "must_change_password": bool(user["must_change_password"]),
        "epoch": user["session_epoch"],
    })
    redirect = RedirectResponse(url="/", status_code=302)
    _set_session_cookie(redirect, request, sess_token, force_secure=(settings.deployment.mode == "hosted"))
    return redirect


class SsoTokenRequest(BaseModel):
    token: str = ""


@router.post("/sso")
async def auth_sso_post(body: SsoTokenRequest, request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)):
    """Exchange a platform-issued JWT for an agent session cookie.

    Preferred SSO channel: the token is read from the JSON body (`token`) or an
    `Authorization: Bearer <jwt>` header, keeping it out of URLs/logs/history.
    """
    token = body.token or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(400, "Missing SSO token")
    return await _exchange_sso_token(token, request, db, settings)


# Legacy query-param SSO channel. The token rides in the URL, so it leaks into
# proxy logs, browser history, and Referer headers — prefer POST /sso above.
# Gated by env var ODIGOS_SSO_ALLOW_QUERY_TOKEN: unset/"1"/"true" keep it enabled
# (default, for rollout); "0"/"false" returns 410 Gone. The platform repo
# (tamler/odigos-platform) must switch to POST before this is disabled.
def _query_sso_enabled() -> bool:
    val = os.environ.get("ODIGOS_SSO_ALLOW_QUERY_TOKEN", "").strip().lower()
    return val not in ("0", "false")


@router.get("/sso")
async def auth_sso(token: str, request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)):
    """Deprecated: exchange a platform JWT passed as a query param for a session.

    Kept behind a deprecation flag for rollout. Use POST /api/auth/sso instead.
    """
    if not _query_sso_enabled():
        raise HTTPException(410, "Query-param SSO is disabled; use POST /api/auth/sso")
    logger.warning(
        "Deprecated query-param SSO used (GET /api/auth/sso?token=...); "
        "platform must migrate to POST /api/auth/sso"
    )
    return await _exchange_sso_token(token, request, db, settings)


@router.post("/logout")
async def auth_logout(request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)):
    """Clear the session cookie. Redirect to platform if managed."""
    _check_csrf(request)
    cookie = request.cookies.get(SESSION_COOKIE)
    session = _validate_session(settings.session_secret, cookie)
    if session:
        await db.execute(
            "UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?",
            (session["user_id"],),
        )
    response.delete_cookie(key=SESSION_COOKIE)
    platform_url = os.environ.get("ODIGOS_PLATFORM_URL", "").rstrip("/")
    if platform_url:
        return RedirectResponse(f"{platform_url}/api/v1/auth/logout", status_code=303)
    return {"status": "ok"}


@router.post("/change-password")
async def auth_change_password(body: ChangePasswordRequest, request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)):
    """Change password for the authenticated user (session required).

    Requires the current password. The exception is when must_change_password
    is set on the user (operator-provisioned account on first login) — in that
    case the temp password they used to log in is sufficient and the current
    password check is skipped.
    """
    _check_csrf(request)
    secret = settings.session_secret
    cookie = request.cookies.get(SESSION_COOKIE)
    session = await _validate_session_with_epoch(secret, cookie, db)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    new_password = body.new_password
    if len(new_password) < _MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {_MIN_PASSWORD_LENGTH} characters",
        )

    user_id = session["user_id"]

    user = await db.fetch_one(
        "SELECT id, password_hash, must_change_password, session_epoch FROM users WHERE id = ?",
        (user_id,),
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify current password unless the account is in forced-change mode
    # (first-login flow for operator-seeded accounts).
    if not user["must_change_password"]:
        if not body.current_password:
            raise HTTPException(status_code=400, detail="Current password is required")
        if not _verify_password(body.current_password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Current password is incorrect")

    new_hash = _hash_password(new_password)
    await db.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
        (new_hash, user_id),
    )

    # Invalidate all prior sessions, then reissue with the new epoch
    await db.execute(
        "UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?",
        (user_id,),
    )
    new_epoch = user["session_epoch"] + 1

    # Reissue session with must_change_password cleared
    token = _create_session(secret, {
        "user_id": session["user_id"],
        "username": session["username"],
        "must_change_password": False,
        "epoch": new_epoch,
    })
    _set_session_cookie(response, request, token, force_secure=(settings.deployment.mode == "hosted"))

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

    username = body.username.strip().lower()
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
        "UPDATE users SET password_hash = ?, must_change_password = 1, "
        "session_epoch = session_epoch + 1 WHERE id = ?",
        (new_hash, user["id"]),
    )
    return {"status": "ok", "must_change_password": True}


@router.get("/me")
async def auth_me(request: Request, db=Depends(get_db), settings=Depends(get_settings)):
    """Return info about the currently authenticated user (session required)."""
    secret = settings.session_secret
    cookie = request.cookies.get(SESSION_COOKIE)
    session = await _validate_session_with_epoch(secret, cookie, db)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = await db.fetch_one(
        "SELECT id, username, email, display_name, must_change_password, created_at, last_login_at "
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
        "email": user["email"] or "",
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
    session = await _validate_session_with_epoch(secret, cookie, db)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    rows = await db.fetch_all(
        "SELECT id, content as fact, source_type as category, confidence, created_at, updated_at "
        "FROM memories WHERE memory_type = 'fact' AND status = 'active' ORDER BY updated_at DESC"
    )
    return {"facts": [dict(row) for row in rows]}


@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: str, request: Request, db=Depends(get_db), settings=Depends(get_settings)):
    """Delete a user fact by ID (session required)."""
    _check_csrf(request)
    secret = settings.session_secret
    cookie = request.cookies.get(SESSION_COOKIE)
    session = await _validate_session_with_epoch(secret, cookie, db)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    await db.execute("UPDATE memories SET status = 'deleted' WHERE id = ? AND memory_type = 'fact'", (fact_id,))
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
    _check_csrf(request)
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")
    secret = settings.session_secret
    session = await _validate_session_with_epoch(secret, cookie, db)
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
