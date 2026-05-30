"""Login timing-oracle test: the no-user path must still run bcrypt verify.

Skipping bcrypt when the username does not exist leaks (via response time)
whether a username is registered. The login handler must run a dummy verify on
the no-user path so timing is indistinguishable from a wrong-password attempt.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import odigos.api.auth as auth_mod
from tests.test_auth import _CSRF, _VALID_SETUP, FakeDB, _make_auth_app


@pytest.mark.asyncio
async def test_login_unknown_user_still_runs_verify(monkeypatch):
    db = FakeDB()
    app = _make_auth_app(db)

    calls: list[tuple[str, str]] = []

    def _spy(pw: str, h: str) -> bool:
        calls.append((pw, h))
        return False

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Seed at least one user so the DB is populated.
        await c.post("/api/auth/setup", json=_VALID_SETUP, headers=_CSRF)

        monkeypatch.setattr(auth_mod, "_verify_password", _spy)

        resp = await c.post(
            "/api/auth/login",
            json={"username": "ghost", "password": "whatever"},
            headers=_CSRF,
        )

    assert resp.status_code == 401
    assert calls, "dummy bcrypt verify must run even when the user does not exist"
