# Standalone Authentication Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace API key browser auth with username/password login using HTTP-only session cookies. API key remains for programmatic access.

**Architecture:** New `users` table in SQLite, `passlib[bcrypt]` for password hashing, `itsdangerous` for signed session cookies. Auth endpoints in `odigos/api/auth.py`. `require_api_key` extended to `require_auth` accepting both Bearer tokens and session cookies. Dashboard LoginPrompt rewritten for login/setup/change-password flows. WebSocket auth extended to accept session cookies.

**Tech Stack:** Python (passlib, itsdangerous, FastAPI), React/TypeScript, SQLite

**Spec:** `docs/superpowers/specs/2026-03-16-auth-design.md`

---

## Chunk 1: Backend Auth Foundation

### Task 1: Add dependencies and migration

**Files:**
- Modify: `pyproject.toml`
- Create: `migrations/025_users.sql`

- [ ] **Step 1: Add passlib and itsdangerous to pyproject.toml**

In `pyproject.toml`, add to the `dependencies` list:
```
"passlib[bcrypt]>=1.7.4",
"itsdangerous>=2.1.0",
```

- [ ] **Step 2: Create users migration**

Create `migrations/025_users.sql`:
```sql
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    must_change_password INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
```

- [ ] **Step 3: Sync dependencies**

Run: `uv sync`
Expected: Installs passlib and itsdangerous

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml migrations/025_users.sql
git commit -m "feat: add users table and auth dependencies (passlib, itsdangerous)"
```

### Task 2: Auth API endpoints

**Files:**
- Create: `odigos/api/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write tests**

Create `tests/test_auth.py`:
```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from odigos.api.auth import router, _hash_password, _verify_password, _create_session, _validate_session


def _make_app(db):
    app = FastAPI()
    app.include_router(router)
    app.state.db = db
    app.state.settings = type("S", (), {"api_key": "test-key", "session_secret": "test-secret-key-for-signing-sessions-1234"})()
    return app


class FakeDB:
    """Minimal async DB fake using a dict for the users table."""
    def __init__(self):
        self.users = {}

    async def fetch_one(self, sql, params=()):
        if "COUNT" in sql:
            return {"count": len(self.users)}
        if "username" in sql and params:
            return self.users.get(params[0])
        if "id" in sql and params:
            for u in self.users.values():
                if u["id"] == params[0]:
                    return u
        return None

    async def execute(self, sql, params=()):
        if "INSERT" in sql:
            self.users[params[1]] = {
                "id": params[0], "username": params[1],
                "password_hash": params[2], "display_name": params[3],
                "must_change_password": params[4], "created_at": params[5],
                "last_login_at": None,
            }
        elif "UPDATE" in sql and "password_hash" in sql:
            for u in self.users.values():
                if u["id"] == params[-1]:
                    u["password_hash"] = params[0]
                    u["must_change_password"] = 0


def test_hash_and_verify():
    h = _hash_password("testpass")
    assert _verify_password("testpass", h)
    assert not _verify_password("wrongpass", h)


def test_session_create_and_validate():
    secret = "test-secret-key-for-signing-sessions-1234"
    token = _create_session("user-123", "jacob", False, secret)
    data = _validate_session(token, secret)
    assert data["user_id"] == "user-123"
    assert data["username"] == "jacob"


def test_setup_creates_user():
    db = FakeDB()
    app = _make_app(db)
    client = TestClient(app)
    resp = client.post("/api/auth/setup", json={"username": "jacob", "password": "securepass1"})
    assert resp.status_code == 200
    assert "odigos_session" in resp.cookies


def test_setup_blocked_when_user_exists():
    db = FakeDB()
    app = _make_app(db)
    client = TestClient(app)
    client.post("/api/auth/setup", json={"username": "jacob", "password": "securepass1"})
    resp = client.post("/api/auth/setup", json={"username": "hacker", "password": "tryagain1"})
    assert resp.status_code == 403


def test_login_success():
    db = FakeDB()
    app = _make_app(db)
    client = TestClient(app)
    client.post("/api/auth/setup", json={"username": "jacob", "password": "securepass1"})
    resp = client.post("/api/auth/login", json={"username": "jacob", "password": "securepass1"})
    assert resp.status_code == 200
    assert "odigos_session" in resp.cookies


def test_login_wrong_password():
    db = FakeDB()
    app = _make_app(db)
    client = TestClient(app)
    client.post("/api/auth/setup", json={"username": "jacob", "password": "securepass1"})
    resp = client.post("/api/auth/login", json={"username": "jacob", "password": "wrong"})
    assert resp.status_code == 401


def test_password_too_short():
    db = FakeDB()
    app = _make_app(db)
    client = TestClient(app)
    resp = client.post("/api/auth/setup", json={"username": "jacob", "password": "short"})
    assert resp.status_code == 400


def test_auth_status_unauthenticated():
    db = FakeDB()
    app = _make_app(db)
    client = TestClient(app)
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    assert resp.json()["setup_required"] is True
    assert resp.json()["authenticated"] is False


def test_change_password():
    db = FakeDB()
    app = _make_app(db)
    client = TestClient(app)
    client.post("/api/auth/setup", json={"username": "jacob", "password": "securepass1"})
    # Login to get session
    login_resp = client.post("/api/auth/login", json={"username": "jacob", "password": "securepass1"})
    cookies = login_resp.cookies
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "securepass1", "new_password": "newpassword1"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    # Verify new password works
    resp2 = client.post("/api/auth/login", json={"username": "jacob", "password": "newpassword1"})
    assert resp2.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_auth.py -x`
Expected: ImportError

- [ ] **Step 3: Write auth.py**

Create `odigos/api/auth.py`:
```python
"""Authentication API: setup, login, logout, change-password, status, me."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.hash import bcrypt
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

SESSION_COOKIE = "odigos_session"
SESSION_TTL = 7 * 24 * 3600  # 7 days
MIN_PASSWORD_LENGTH = 8


def _hash_password(password: str) -> str:
    return bcrypt.using(rounds=12).hash(password)


def _verify_password(password: str, hash: str) -> bool:
    return bcrypt.verify(password, hash)


def _get_secret(request: Request) -> str:
    return getattr(request.app.state.settings, "session_secret", "") or "fallback-insecure"


def _create_session(user_id: str, username: str, must_change: bool, secret: str) -> str:
    s = URLSafeTimedSerializer(secret)
    return s.dumps({
        "user_id": user_id,
        "username": username,
        "must_change_password": must_change,
    })


def _validate_session(token: str, secret: str, max_age: int = SESSION_TTL) -> dict | None:
    s = URLSafeTimedSerializer(secret)
    try:
        return s.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def _set_cookie(response: Response, token: str, request: Request) -> None:
    is_https = request.url.scheme == "https"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=SESSION_TTL,
        path="/",
    )


async def _user_count(db) -> int:
    row = await db.fetch_one("SELECT COUNT(*) as count FROM users")
    return row["count"] if row else 0


class SetupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("/status")
async def auth_status(request: Request):
    db = request.app.state.db
    count = await _user_count(db)
    setup_required = count == 0

    authenticated = False
    must_change = False
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        secret = _get_secret(request)
        data = _validate_session(cookie, secret)
        if data:
            authenticated = True
            must_change = data.get("must_change_password", False)

    return {
        "setup_required": setup_required,
        "authenticated": authenticated,
        "must_change_password": must_change,
    }


@router.post("/setup")
async def auth_setup(body: SetupRequest, request: Request, response: Response):
    db = request.app.state.db
    count = await _user_count(db)
    if count > 0:
        raise HTTPException(status_code=403, detail="Account already exists")

    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    pw_hash = _hash_password(body.password)

    await db.execute(
        "INSERT INTO users (id, username, password_hash, display_name, must_change_password, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, body.username.strip(), pw_hash, body.username.strip(), 0, now),
    )

    secret = _get_secret(request)
    token = _create_session(user_id, body.username.strip(), False, secret)
    _set_cookie(response, token, request)

    return {"status": "ok", "user_id": user_id}


@router.post("/login")
async def auth_login(body: LoginRequest, request: Request, response: Response):
    db = request.app.state.db
    user = await db.fetch_one(
        "SELECT id, username, password_hash, must_change_password FROM users WHERE username = ?",
        (body.username.strip(),),
    )
    if not user or not _verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    now = datetime.now(timezone.utc).isoformat()
    await db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user["id"]))

    must_change = bool(user["must_change_password"])
    secret = _get_secret(request)
    token = _create_session(user["id"], user["username"], must_change, secret)
    _set_cookie(response, token, request)

    return {"status": "ok", "must_change_password": must_change}


@router.post("/logout")
async def auth_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "ok"}


@router.post("/change-password")
async def auth_change_password(body: ChangePasswordRequest, request: Request, response: Response):
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")

    secret = _get_secret(request)
    session = _validate_session(cookie, secret)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    if len(body.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    db = request.app.state.db
    user = await db.fetch_one(
        "SELECT id, password_hash FROM users WHERE id = ?",
        (session["user_id"],),
    )
    if not user or not _verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    new_hash = _hash_password(body.new_password)
    await db.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
        (new_hash, user["id"]),
    )

    token = _create_session(user["id"], session["username"], False, secret)
    _set_cookie(response, token, request)

    return {"status": "ok"}


@router.get("/me")
async def auth_me(request: Request):
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")

    secret = _get_secret(request)
    session = _validate_session(cookie, secret)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    db = request.app.state.db
    user = await db.fetch_one(
        "SELECT id, username, display_name, created_at, last_login_at FROM users WHERE id = ?",
        (session["user_id"],),
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "created_at": user["created_at"],
        "last_login_at": user["last_login_at"],
    }
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_auth.py -xvs`
Expected: All 9 pass

- [ ] **Step 5: Commit**

```bash
git add odigos/api/auth.py tests/test_auth.py
git commit -m "feat: auth API endpoints (setup, login, logout, change-password, status, me)"
```

### Task 3: Update auth middleware (deps.py) and register router

**Files:**
- Modify: `odigos/api/deps.py`
- Modify: `odigos/main.py`
- Modify: `odigos/api/ws.py`

- [ ] **Step 1: Update require_api_key to require_auth**

In `odigos/api/deps.py`, rename `require_api_key` to `require_auth` and extend it to also check session cookies:

```python
from odigos.api.auth import SESSION_COOKIE, _validate_session


async def require_auth(request: Request):
    """Validate auth via Bearer token OR session cookie.

    Bearer token: existing API key behavior for programmatic access.
    Session cookie: new, for browser sessions.
    """
    settings = request.app.state.settings

    # 1. Check Bearer token (API key)
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split(" ", 1)
        if len(parts) == 2 and parts[0] == "Bearer":
            token = parts[1]
            configured_key = settings.api_key
            if configured_key and _safe_compare(token, configured_key):
                return
            raise HTTPException(status_code=403, detail="Invalid API key")

    # 2. Check session cookie
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        secret = getattr(settings, "session_secret", "") or "fallback-insecure"
        data = _validate_session(cookie, secret)
        if data:
            request.state.user = data
            return

    # 3. Legacy mode: if no users exist and API key is set, allow API key only
    # (handled by Bearer check above)

    raise HTTPException(status_code=401, detail="Authentication required")
```

Keep the old `require_api_key` name as an alias for backward compatibility:
```python
require_api_key = require_auth
```

Also update `require_card_or_api_key` to check session cookies after the existing checks.

- [ ] **Step 2: Add session_secret to Settings**

In `odigos/config.py`, add to the `Settings` class:
```python
session_secret: str = ""
```

- [ ] **Step 3: Register auth router and seed user in main.py**

In `odigos/main.py`:
- Import and include the auth router: `from odigos.api.auth import router as auth_router` and `app.include_router(auth_router)`
- Add seed user logic after DB initialization:
```python
# Seed user from data/seed_user.json (for provisioned deploys)
seed_path = Path("data/seed_user.json")
if seed_path.exists():
    import json
    from odigos.api.auth import _hash_password
    seed = json.loads(seed_path.read_text())
    user_count = await db.fetch_one("SELECT COUNT(*) as count FROM users")
    if user_count and user_count["count"] == 0:
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO users (id, username, password_hash, display_name, must_change_password, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, seed["username"], _hash_password(seed["password"]), seed["username"], 1 if seed.get("must_change_password") else 0, now),
        )
        logger.info("Seeded user '%s' from seed_user.json", seed["username"])
    seed_path.unlink()
```

- Generate SESSION_SECRET if not set:
```python
if not settings.session_secret:
    import secrets as _secrets
    secret = _secrets.token_urlsafe(48)
    object.__setattr__(settings, "session_secret", secret)
    # Persist to .env
    env_path = Path(".env")
    with open(env_path, "a") as f:
        f.write(f"\nSESSION_SECRET={secret}\n")
```

- [ ] **Step 4: Update WebSocket auth**

In `odigos/api/ws.py`, modify `_authenticate_ws` to check session cookie before falling back to first-message auth:

After the `if not configured_key` check and before the query param check, add:
```python
# Check session cookie (browser sends it automatically on WS upgrade)
from odigos.api.auth import SESSION_COOKIE, _validate_session
cookie = websocket.cookies.get(SESSION_COOKIE)
if cookie:
    secret = getattr(settings, "session_secret", "") or "fallback-insecure"
    data = _validate_session(cookie, secret)
    if data:
        logger.debug("WebSocket authenticated via session cookie (user: %s)", data.get("username"))
        return True
```

Also relax the `if not configured_key` check -- when auth mode is active (users exist), we don't need an API key configured. Change the early return to:
```python
if not configured_key:
    # In auth mode, session cookie is enough. Only fail if no cookie either.
    cookie = websocket.cookies.get(SESSION_COOKIE)
    if cookie:
        ...validate and return...
    await websocket.close(code=4003, reason="Authentication required")
    return False
```

- [ ] **Step 5: Run all tests**

Run: `.venv/bin/python -m pytest tests/ --ignore=tests/e2e -x -q`
Expected: All pass (auth tests + existing tests)

- [ ] **Step 6: Commit**

```bash
git add odigos/api/deps.py odigos/api/ws.py odigos/config.py odigos/main.py
git commit -m "feat: integrate auth middleware, seed users, session cookie in WebSocket

require_api_key renamed to require_auth, accepts both Bearer token
and session cookie. WebSocket auth extended for cookie-based login.
Seed user from data/seed_user.json on startup for provisioned deploys."
```

---

## Chunk 2: Dashboard Auth Flow

### Task 4: Rewrite frontend auth

**Files:**
- Modify: `dashboard/src/lib/auth.ts`
- Modify: `dashboard/src/lib/api.ts`
- Modify: `dashboard/src/lib/ws.ts`
- Rewrite: `dashboard/src/components/LoginPrompt.tsx`
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Simplify auth.ts**

Rewrite `dashboard/src/lib/auth.ts`:
```typescript
// Cookie-based auth -- the browser handles session cookies automatically.
// These helpers call the auth API endpoints.

export async function getAuthStatus(): Promise<{
  setup_required: boolean
  authenticated: boolean
  must_change_password: boolean
}> {
  const res = await fetch('/api/auth/status')
  if (!res.ok) throw new Error('Failed to check auth status')
  return res.json()
}

export async function login(username: string, password: string): Promise<{ must_change_password: boolean }> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (res.status === 401) throw new Error('Invalid username or password')
  if (!res.ok) throw new Error('Login failed')
  return res.json()
}

export async function setup(username: string, password: string): Promise<void> {
  const res = await fetch('/api/auth/setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || 'Setup failed')
  }
}

export async function logout(): Promise<void> {
  await fetch('/api/auth/logout', { method: 'POST' })
  window.location.reload()
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const res = await fetch('/api/auth/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || 'Failed to change password')
  }
}
```

- [ ] **Step 2: Update api.ts -- remove Authorization header**

In `dashboard/src/lib/api.ts`, change the `headers()` function to stop sending Authorization:
```typescript
function headers(): HeadersInit {
  return {
    'Content-Type': 'application/json',
  }
}
```

Remove `getToken()` function entirely. The browser sends the session cookie automatically.

Keep `uploadFile()` working -- it also doesn't need the auth header since cookies are sent.

- [ ] **Step 3: Update ws.ts -- remove API key auth**

Rewrite `dashboard/src/lib/ws.ts` to not send auth first message (cookie is sent on WS upgrade):
```typescript
export class ChatSocket {
  private ws: WebSocket | null = null
  private baseHandler: (msg: Record<string, unknown>) => void
  private onStatusChange: (connected: boolean) => void
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  onMessage: ((msg: Record<string, unknown>) => void) | null = null

  constructor(
    baseHandler: (msg: Record<string, unknown>) => void,
    onStatusChange: (connected: boolean) => void,
  ) {
    this.baseHandler = baseHandler
    this.onStatusChange = onStatusChange
  }

  connect(): void {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.ws = new WebSocket(`${proto}//${window.location.host}/api/ws`)

    this.ws.onopen = () => {
      // Session cookie sent automatically on upgrade -- no manual auth needed
      this.onStatusChange(true)
    }
    this.ws.onclose = () => {
      this.onStatusChange(false)
      this.scheduleReconnect()
    }
    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        this.baseHandler(msg)
        if (this.onMessage) this.onMessage(msg)
      } catch { /* ignore parse errors */ }
    }
  }

  send(type: string, data: Record<string, unknown> = {}): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, ...data }))
    }
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.ws = null
  }

  private scheduleReconnect(): void {
    this.reconnectTimer = setTimeout(() => this.connect(), 3000)
  }
}
```

- [ ] **Step 4: Rewrite LoginPrompt.tsx**

Rewrite `dashboard/src/components/LoginPrompt.tsx` to handle setup, login, and forced password change:

```tsx
import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { login, setup, changePassword } from '@/lib/auth'

interface Props {
  setupRequired: boolean
  mustChangePassword: boolean
  onAuth: () => void
}

export default function LoginPrompt({ setupRequired, mustChangePassword, onAuth }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmNewPassword, setConfirmNewPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSetup(e: React.FormEvent) {
    e.preventDefault()
    if (password !== confirmPassword) { setError('Passwords do not match'); return }
    if (password.length < 8) { setError('Password must be at least 8 characters'); return }
    setLoading(true)
    try {
      await setup(username.trim(), password)
      onAuth()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      const result = await login(username.trim(), password)
      if (result.must_change_password) {
        // Stay on this page but switch to change password mode
        window.location.reload()
      } else {
        onAuth()
      }
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault()
    if (newPassword !== confirmNewPassword) { setError('Passwords do not match'); return }
    if (newPassword.length < 8) { setError('Password must be at least 8 characters'); return }
    setLoading(true)
    try {
      await changePassword(password, newPassword)
      onAuth()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (mustChangePassword) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>Change Password</CardTitle>
            <p className="text-sm text-muted-foreground">You must set a new password before continuing.</p>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleChangePassword} className="space-y-4">
              <div className="space-y-2">
                <Label>Current Password</Label>
                <Input type="password" value={password} onChange={(e) => { setPassword(e.target.value); setError('') }} autoFocus />
              </div>
              <div className="space-y-2">
                <Label>New Password</Label>
                <Input type="password" value={newPassword} onChange={(e) => { setNewPassword(e.target.value); setError('') }} />
              </div>
              <div className="space-y-2">
                <Label>Confirm New Password</Label>
                <Input type="password" value={confirmNewPassword} onChange={(e) => { setConfirmNewPassword(e.target.value); setError('') }} />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={loading}>{loading ? 'Saving...' : 'Set Password'}</Button>
            </form>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (setupRequired) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>Create Account</CardTitle>
            <p className="text-sm text-muted-foreground">Set up your Odigos account.</p>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSetup} className="space-y-4">
              <div className="space-y-2">
                <Label>Username</Label>
                <Input value={username} onChange={(e) => { setUsername(e.target.value); setError('') }} autoFocus />
              </div>
              <div className="space-y-2">
                <Label>Password</Label>
                <Input type="password" value={password} onChange={(e) => { setPassword(e.target.value); setError('') }} />
              </div>
              <div className="space-y-2">
                <Label>Confirm Password</Label>
                <Input type="password" value={confirmPassword} onChange={(e) => { setConfirmPassword(e.target.value); setError('') }} />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={loading || !username.trim() || !password}>{loading ? 'Creating...' : 'Create Account'}</Button>
            </form>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-center h-screen bg-background">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign In</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <Label>Username</Label>
              <Input value={username} onChange={(e) => { setUsername(e.target.value); setError('') }} autoFocus />
            </div>
            <div className="space-y-2">
              <Label>Password</Label>
              <Input type="password" value={password} onChange={(e) => { setPassword(e.target.value); setError('') }} />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading || !username.trim() || !password}>{loading ? 'Signing in...' : 'Sign In'}</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
```

- [ ] **Step 5: Update App.tsx**

Rewrite `dashboard/src/App.tsx` to use `/api/auth/status`:
```tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Toaster } from '@/components/ui/sonner'
import { getAuthStatus } from './lib/auth'
import AppLayout from './layouts/AppLayout'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'
import LoginPrompt from './components/LoginPrompt'

export default function App() {
  const [authState, setAuthState] = useState<{
    setup_required: boolean
    authenticated: boolean
    must_change_password: boolean
  } | null>(null)

  useEffect(() => {
    getAuthStatus()
      .then(setAuthState)
      .catch(() => setAuthState({ setup_required: true, authenticated: false, must_change_password: false }))
  }, [])

  if (authState === null) {
    return <div className="flex items-center justify-center h-screen text-muted-foreground text-sm">Loading...</div>
  }

  const needsAuth = !authState.authenticated || authState.setup_required || authState.must_change_password

  return (
    <>
      <Toaster position="top-right" richColors />
      {needsAuth ? (
        <LoginPrompt
          setupRequired={authState.setup_required}
          mustChangePassword={authState.must_change_password}
          onAuth={() => {
            getAuthStatus().then(setAuthState)
          }}
        />
      ) : (
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/" element={<ChatPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      )}
    </>
  )
}
```

Note: the `needsSetup` prop on SettingsPage can be removed since the setup wizard is now in the auth flow, not in Settings. Clean up SettingsPage to remove that prop.

- [ ] **Step 6: Type-check**

Run: `cd dashboard && npx tsc --noEmit`

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/
git commit -m "feat(dashboard): cookie-based auth flow with login/setup/change-password

Replace API key prompt with username/password login. Session cookie
sent automatically by browser. WebSocket auth via cookie on upgrade."
```

---

## Chunk 3: Account Tab, Install Scripts, Deploy

### Task 5: Account tab in Settings

**Files:**
- Create: `dashboard/src/pages/settings/AccountTab.tsx`
- Modify: `dashboard/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Create AccountTab**

Create `dashboard/src/pages/settings/AccountTab.tsx` with:
- Display username and display name (from `/api/auth/me`)
- Change password form
- API key display (read-only, from `/api/settings`)
- Logout button

- [ ] **Step 2: Add to SettingsPage**

Import AccountTab and add as the first tab in the TABS array:
```typescript
{ id: 'account', label: 'Account' },
```

Remove the `needsSetup` prop from SettingsPage (no longer needed).

- [ ] **Step 3: Type-check and build**

Run: `cd dashboard && npx tsc --noEmit && npm run build`

- [ ] **Step 4: Commit**

```bash
git add dashboard/
git commit -m "feat(dashboard): add Account tab in Settings with password change and logout"
```

### Task 6: Install script updates

**Files:**
- Modify: `install.sh`
- Modify: `install-bare.sh`

- [ ] **Step 1: Add SESSION_SECRET generation**

In both install scripts, after the API_KEY generation section, add:
```bash
# Generate SESSION_SECRET for cookie signing
if ! grep -q "^SESSION_SECRET=.\+" .env 2>/dev/null; then
    session_secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    echo "SESSION_SECRET=${session_secret}" >> .env
    info "Generated SESSION_SECRET"
fi
```

- [ ] **Step 2: Add optional account creation**

After the voice setup section, add:
```bash
echo ""
read -rp "$(echo -e "${BOLD}Create owner account now? [Y/n]:${NC} ")" create_account
create_account=${create_account:-Y}

if [[ "$create_account" =~ ^[Yy]$ ]]; then
    read -rp "  Username: " owner_username
    while [ -z "$owner_username" ]; do
        read -rp "  Username: " owner_username
    done
    read -srp "  Password (min 8 chars): " owner_password
    echo ""
    while [ ${#owner_password} -lt 8 ]; do
        read -srp "  Password too short. Try again (min 8 chars): " owner_password
        echo ""
    done
    mkdir -p data
    cat > data/seed_user.json << EOF
{"username": "$owner_username", "password": "$owner_password", "must_change_password": false}
EOF
    info "Account will be created on first startup"
fi
```

- [ ] **Step 3: Commit**

```bash
git add install.sh install-bare.sh
git commit -m "feat: add SESSION_SECRET generation and optional account creation to install scripts"
```

### Task 7: Deploy script updates

**Files:**
- Modify: `deploy-testers.sh`

- [ ] **Step 1: Update deploy script**

In `deploy-testers.sh`:
- Add `SESSION_SECRET` generation to the shared `.env` (if not present)
- For each tester, generate a seed_user.json instead of just an API key:
```bash
temp_password=$(python3 -c "import secrets; print(secrets.token_urlsafe(12))")
cat > "$dir/data/seed_user.json" << SEED
{"username": "$name", "password": "$temp_password", "must_change_password": true}
SEED
```
- Update the summary output to print username + temp password instead of API key

- [ ] **Step 2: Commit**

```bash
git add deploy-testers.sh
git commit -m "feat: deploy script generates seed users with temp passwords"
```

### Task 8: Final build, test, push, deploy

- [ ] **Step 1: Full test suite**

Run: `.venv/bin/python -m pytest tests/ --ignore=tests/e2e -x -q`

- [ ] **Step 2: Dashboard build**

Run: `cd dashboard && npx tsc --noEmit && npm run build`

- [ ] **Step 3: Commit and push**

```bash
git add dashboard/dist/
git commit -m "build: rebuild dashboard with auth flow"
git push
```

- [ ] **Step 4: Deploy to personal VPS**

```bash
ssh root@82.25.91.86 "cd /opt/odigos && git pull && uv sync && systemctl restart odigos"
```

Note: The first visit to the dashboard will show the "Create Account" wizard since no users exist yet.

- [ ] **Step 5: Deploy to tester VPS**

```bash
ssh root@100.89.147.103 "cd /opt/odigos/repo && git pull && cd /opt/odigos && docker compose build --no-cache && docker compose down && docker compose up -d"
```

Note: Tester containers will need seed_user.json files created. Run the updated deploy-testers.sh or manually create them.
