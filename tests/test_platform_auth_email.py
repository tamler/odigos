"""Platform /auth/callback must normalize email (lowercase) and derive a clean username.

The platform validate-token boundary is stubbed with httpx.MockTransport (built into
httpx, not a mock library) — a real ASGI/httpx transport with a handler function. No
network is touched.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import odigos.api.platform_auth as platform_auth
from odigos.api.auth import SESSION_COOKIE, router as auth_router
from odigos.api.platform_auth import router as platform_router
from odigos.container import Container


class FakeDB:
    """Dict-backed async DB handling the SQL the platform callback uses."""

    class _Row(dict):
        pass

    def __init__(self):
        self._users: dict[str, dict] = {}  # keyed by id

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        sql_lower = sql.lower().strip()

        if "count(*)" in sql_lower and "from users" in sql_lower:
            return self._Row({"count": len(self._users)})

        if "from users where lower(email)" in sql_lower:
            email = params[0]
            for u in self._users.values():
                if (u.get("email") or "").lower() == email:
                    return self._Row(u)
            return None

        if "from users where email" in sql_lower:
            email = params[0]
            for u in self._users.values():
                if u.get("email") == email:
                    return self._Row(u)
            return None

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
            uid = params[0]
            self._users[uid] = {
                "id": uid,
                "username": params[1],
                "password_hash": params[2] if len(params) > 2 else "",
                "display_name": params[3] if len(params) > 3 else "",
                "email": params[4] if len(params) > 4 else "",
                "must_change_password": 0,
                "created_at": params[5] if len(params) > 5 else "",
                "last_login_at": params[6] if len(params) > 6 else None,
                "session_epoch": 0,
            }
            return

        if "update users set last_login_at" in sql_lower:
            uid = params[1]
            if uid in self._users:
                self._users[uid]["last_login_at"] = params[0]
            return


def _seed_user(db: FakeDB, *, email: str, username: str) -> str:
    uid = uuid.uuid4().hex
    db._users[uid] = {
        "id": uid,
        "username": username,
        "password_hash": "x",
        "display_name": username,
        "email": email,
        "must_change_password": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_login_at": None,
        "session_epoch": 0,
    }
    return uid


class _FakeSettings:
    class _Deployment:
        mode = "dev"

    session_secret = "test-session-secret"
    deployment = _Deployment()


def _make_app(db: FakeDB, platform_email: str) -> FastAPI:
    """Build an app whose platform validate-token call returns ``platform_email``.

    The httpx.AsyncClient inside the callback is swapped for one wired to a
    MockTransport, so the POST to the platform never hits the network.
    """
    app = FastAPI()
    app.include_router(platform_router)
    app.include_router(auth_router)
    app.state.container = Container(settings=_FakeSettings(), db=db)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"email": platform_email, "name": "Platform User"})

    transport = httpx.MockTransport(_handler)

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    # Configure the module-level platform constants and inject the transport.
    platform_auth.PLATFORM_URL = "https://platform.test"
    platform_auth.PLATFORM_API_KEY = "platform-key"
    app.state._patched_client = _PatchedClient  # keep a ref
    platform_auth.httpx.AsyncClient = _PatchedClient
    return app


@pytest.fixture(autouse=True)
def _restore_platform_module():
    orig_client = platform_auth.httpx.AsyncClient
    orig_url = platform_auth.PLATFORM_URL
    orig_key = platform_auth.PLATFORM_API_KEY
    yield
    platform_auth.httpx.AsyncClient = orig_client
    platform_auth.PLATFORM_URL = orig_url
    platform_auth.PLATFORM_API_KEY = orig_key


@pytest.mark.asyncio
async def test_callback_matches_existing_user_case_insensitive():
    """A platform email differing only in case must match the existing row."""
    db = FakeDB()
    _seed_user(db, email="user@example.com", username="user")
    app = _make_app(db, platform_email="User@Example.com")

    users_before = len(db._users)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/callback", params={"token": "tok"})

    # Redirect to "/" on success, with a session cookie set.
    assert resp.status_code in (302, 307), resp.text
    assert SESSION_COOKIE in resp.cookies
    # No duplicate account created.
    assert len(db._users) == users_before


@pytest.mark.asyncio
async def test_callback_provisions_username_from_local_part():
    """A brand-new email auto-provisions a user with a derived (sanitized) username."""
    db = FakeDB()
    app = _make_app(db, platform_email="New.User+tag@Example.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/callback", params={"token": "tok"})

    assert resp.status_code in (302, 307), resp.text
    assert len(db._users) == 1
    created = next(iter(db._users.values()))
    # Email stored lowercased.
    assert created["email"] == "new.user+tag@example.com"
    # Username derived from local-part, stripped of non [a-z0-9_], not the raw email.
    assert created["username"] == "newusertag"
    assert "@" not in created["username"]
