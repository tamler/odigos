"""Tests for the auth system: password hashing, sessions, and auth API endpoints."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.auth import (
    SESSION_COOKIE,
    _create_session,
    _hash_password,
    _validate_session,
    _verify_password,
    router as auth_router,
)

_TEST_SECRET = "test-session-secret-for-unit-tests"


# ---------------------------------------------------------------------------
# FakeDB -- dict-based async DB that handles the queries auth.py uses
# ---------------------------------------------------------------------------

class FakeDB:
    """Minimal async DB substitute backed by a plain dict.

    Handles the SQL patterns used by the auth endpoints without mocks.
    """

    def __init__(self):
        self._users: dict[str, dict] = {}  # keyed by id

    # -- helpers to make row dicts behave like aiosqlite.Row --
    class _Row(dict):
        def __getitem__(self, key):
            return super().__getitem__(key)

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        sql_lower = sql.lower().strip()

        if "count(*)" in sql_lower and "from users" in sql_lower:
            return self._Row({"count": len(self._users)})

        if "from users where username" in sql_lower:
            username = params[0]
            for u in self._users.values():
                if u["username"] == username:
                    return self._Row(u)
            return None

        if "from users where id" in sql_lower:
            user_id = params[0]
            return self._Row(self._users[user_id]) if user_id in self._users else None

        return None

    async def execute(self, sql: str, params: tuple = ()) -> None:
        sql_lower = sql.lower().strip()

        if sql_lower.startswith("insert into users"):
            # params: (id, username, password_hash, display_name, must_change_password, created_at, last_login_at)
            # or:     (id, username, password_hash, display_name, must_change_password, created_at)
            uid = params[0]
            self._users[uid] = {
                "id": uid,
                "username": params[1],
                "password_hash": params[2],
                "display_name": params[3],
                "must_change_password": params[4] if len(params) > 4 else 0,
                "created_at": params[5] if len(params) > 5 else "",
                "last_login_at": params[6] if len(params) > 6 else None,
            }
            return

        if "update users set password_hash" in sql_lower:
            new_hash = params[0]
            uid = params[1]
            if uid in self._users:
                self._users[uid]["password_hash"] = new_hash
                self._users[uid]["must_change_password"] = 0
            return

        if "update users set last_login_at" in sql_lower:
            ts = params[0]
            uid = params[1]
            if uid in self._users:
                self._users[uid]["last_login_at"] = ts
            return


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _make_auth_app(db: FakeDB | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)

    class _FakeSettings:
        api_key = "test-api-key"
        session_secret = _TEST_SECRET

    app.state.settings = _FakeSettings()
    app.state.db = db or FakeDB()
    return app


# ---------------------------------------------------------------------------
# Unit tests: password hashing
# ---------------------------------------------------------------------------

def test_hash_and_verify_password():
    pw = "supersecret123"
    hashed = _hash_password(pw)
    assert hashed != pw
    assert _verify_password(pw, hashed)


def test_verify_wrong_password():
    hashed = _hash_password("correct-password")
    assert not _verify_password("wrong-password", hashed)


# ---------------------------------------------------------------------------
# Unit tests: session tokens
# ---------------------------------------------------------------------------

def test_create_and_validate_session():
    payload = {"user_id": "abc", "username": "alice", "must_change_password": False}
    token = _create_session(_TEST_SECRET, payload)
    result = _validate_session(_TEST_SECRET, token)
    assert result is not None
    assert result["user_id"] == "abc"
    assert result["username"] == "alice"


def test_validate_session_bad_token():
    result = _validate_session(_TEST_SECRET, "totally-invalid-token")
    assert result is None


def test_validate_session_wrong_secret():
    token = _create_session(_TEST_SECRET, {"user_id": "x"})
    result = _validate_session("different-secret", token)
    assert result is None


def test_validate_session_empty_inputs():
    assert _validate_session("", "some-token") is None
    assert _validate_session(_TEST_SECRET, "") is None


# ---------------------------------------------------------------------------
# Integration tests: auth API endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auth_status_unauthenticated():
    app = _make_auth_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["setup_required"] is True
    assert data["authenticated"] is False
    assert data["must_change_password"] is False


@pytest.mark.asyncio
async def test_setup_creates_user_and_sets_cookie():
    db = FakeDB()
    app = _make_auth_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/auth/setup", json={
            "username": "admin",
            "password": "longpassword123",
            "display_name": "Admin User",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert "user_id" in data
    # Cookie should be set
    assert SESSION_COOKIE in resp.cookies
    # DB should have 1 user
    assert len(db._users) == 1


@pytest.mark.asyncio
async def test_setup_blocked_when_user_exists():
    db = FakeDB()
    app = _make_auth_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/auth/setup", json={
            "username": "admin",
            "password": "longpassword123",
        })
        resp = await c.post("/api/auth/setup", json={
            "username": "admin2",
            "password": "anotherpass123",
        })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_setup_password_too_short():
    app = _make_auth_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/auth/setup", json={
            "username": "admin",
            "password": "short",
        })
    assert resp.status_code == 400
    assert "8 characters" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_success():
    db = FakeDB()
    app = _make_auth_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Setup first
        await c.post("/api/auth/setup", json={
            "username": "admin",
            "password": "longpassword123",
        })
        # Now login
        resp = await c.post("/api/auth/login", json={
            "username": "admin",
            "password": "longpassword123",
        })
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is False
    assert SESSION_COOKIE in resp.cookies


@pytest.mark.asyncio
async def test_login_wrong_password():
    db = FakeDB()
    app = _make_auth_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/auth/setup", json={
            "username": "admin",
            "password": "longpassword123",
        })
        resp = await c.post("/api/auth/login", json={
            "username": "admin",
            "password": "wrongpassword",
        })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_change_password_flow():
    db = FakeDB()
    app = _make_auth_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Setup user
        setup_resp = await c.post("/api/auth/setup", json={
            "username": "admin",
            "password": "longpassword123",
        })
        cookie = setup_resp.cookies.get(SESSION_COOKIE)

        # Change password
        resp = await c.post(
            "/api/auth/change-password",
            json={"new_password": "newlongpassword456"},
            cookies={SESSION_COOKIE: cookie},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify old password no longer works, new one does
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp_old = await c.post("/api/auth/login", json={
            "username": "admin",
            "password": "longpassword123",
        })
        resp_new = await c.post("/api/auth/login", json={
            "username": "admin",
            "password": "newlongpassword456",
        })
    assert resp_old.status_code == 401
    assert resp_new.status_code == 200


@pytest.mark.asyncio
async def test_change_password_too_short():
    db = FakeDB()
    app = _make_auth_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        setup_resp = await c.post("/api/auth/setup", json={
            "username": "admin",
            "password": "longpassword123",
        })
        cookie = setup_resp.cookies.get(SESSION_COOKIE)
        resp = await c.post(
            "/api/auth/change-password",
            json={"new_password": "short"},
            cookies={SESSION_COOKIE: cookie},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_me_endpoint():
    db = FakeDB()
    app = _make_auth_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        setup_resp = await c.post("/api/auth/setup", json={
            "username": "admin",
            "password": "longpassword123",
            "display_name": "The Admin",
        })
        cookie = setup_resp.cookies.get(SESSION_COOKIE)
        resp = await c.get("/api/auth/me", cookies={SESSION_COOKIE: cookie})
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["display_name"] == "The Admin"


@pytest.mark.asyncio
async def test_me_unauthenticated():
    app = _make_auth_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/auth/me")
    assert resp.status_code == 401
