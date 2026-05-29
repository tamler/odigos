"""Tests for session revocation via per-user session_epoch."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from odigos.api.auth import SESSION_COOKIE

from tests.test_auth import FakeDB, _make_auth_app, _CSRF, _VALID_SETUP


@pytest.mark.asyncio
async def test_epoch_bump_invalidates_existing_cookie():
    """Bumping a user's session_epoch in the DB rejects pre-bump cookies."""
    db = FakeDB()
    app = _make_auth_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        setup_resp = await c.post("/api/auth/setup", json=_VALID_SETUP, headers=_CSRF)
        cookie = setup_resp.cookies.get(SESSION_COOKIE)

        # Cookie works before bump
        resp = await c.get("/api/auth/me", cookies={SESSION_COOKIE: cookie})
        assert resp.status_code == 200, resp.text

        # Bump the user's epoch directly in the DB
        uid = next(iter(db._users))
        await db.execute("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?", (uid,))

        # Same cookie is now rejected
        resp = await c.get("/api/auth/me", cookies={SESSION_COOKIE: cookie})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_invalidates_existing_cookie():
    """After logout, the pre-logout cookie is rejected (epoch bumped)."""
    db = FakeDB()
    app = _make_auth_app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        setup_resp = await c.post("/api/auth/setup", json=_VALID_SETUP, headers=_CSRF)
        cookie = setup_resp.cookies.get(SESSION_COOKIE)

        resp = await c.get("/api/auth/me", cookies={SESSION_COOKIE: cookie})
        assert resp.status_code == 200, resp.text

        logout_resp = await c.post(
            "/api/auth/logout", cookies={SESSION_COOKIE: cookie}, headers=_CSRF
        )
        assert logout_resp.status_code == 200, logout_resp.text

        resp = await c.get("/api/auth/me", cookies={SESSION_COOKIE: cookie})
        assert resp.status_code == 401
