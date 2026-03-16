"""Auth API: setup, login, logout, change-password, status, me."""

import uuid
from datetime import datetime, timezone

import bcrypt as _bcrypt
from fastapi import APIRouter, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "odigos_session"
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
async def auth_status(request: Request):
    """Return auth status -- no auth required."""
    db = request.app.state.db
    row = await db.fetch_one("SELECT COUNT(*) as count FROM users")
    has_users = row["count"] > 0 if row else False

    authenticated = False
    must_change = False

    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        secret = request.app.state.settings.session_secret
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
async def auth_setup(request: Request, response: Response):
    """Create the first user. Blocked if any user already exists."""
    db = request.app.state.db
    row = await db.fetch_one("SELECT COUNT(*) as count FROM users")
    if row and row["count"] > 0:
        raise HTTPException(status_code=409, detail="Setup already completed")

    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    display_name = body.get("display_name", "")

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

    secret = request.app.state.settings.session_secret
    token = _create_session(secret, {
        "user_id": user_id,
        "username": username,
        "must_change_password": False,
    })
    _set_session_cookie(response, request, token)

    return {"user_id": user_id, "username": username}


@router.post("/login")
async def auth_login(request: Request, response: Response):
    """Validate credentials and set session cookie."""
    db = request.app.state.db
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")

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
    secret = request.app.state.settings.session_secret
    token = _create_session(secret, {
        "user_id": user["id"],
        "username": user["username"],
        "must_change_password": must_change,
    })
    _set_session_cookie(response, request, token)

    return {"must_change_password": must_change}


@router.post("/logout")
async def auth_logout(response: Response):
    """Clear the session cookie."""
    response.delete_cookie(key=SESSION_COOKIE)
    return {"status": "ok"}


@router.post("/change-password")
async def auth_change_password(request: Request, response: Response):
    """Change password for the authenticated user (session required)."""
    secret = request.app.state.settings.session_secret
    cookie = request.cookies.get(SESSION_COOKIE)
    session = _validate_session(secret, cookie)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    body = await request.json()
    new_password = body.get("new_password", "")
    if len(new_password) < _MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {_MIN_PASSWORD_LENGTH} characters",
        )

    user_id = session["user_id"]
    db = request.app.state.db

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


@router.get("/me")
async def auth_me(request: Request):
    """Return info about the currently authenticated user (session required)."""
    secret = request.app.state.settings.session_secret
    cookie = request.cookies.get(SESSION_COOKIE)
    session = _validate_session(secret, cookie)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    db = request.app.state.db
    user = await db.fetch_one(
        "SELECT id, username, display_name, must_change_password, created_at, last_login_at "
        "FROM users WHERE id = ?",
        (session["user_id"],),
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "must_change_password": bool(user["must_change_password"]),
        "created_at": user["created_at"],
        "last_login_at": user["last_login_at"],
    }
