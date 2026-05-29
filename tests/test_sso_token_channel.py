"""SSO token channel: POST body + Authorization header (preferred), legacy GET query param.

Reuses the in-process app harness, FakeDB, and JWT mint helper from
tests/test_sso_no_autoprovision.py — no mocks.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from odigos.api.auth import SESSION_COOKIE
from tests.test_sso_no_autoprovision import FakeDB, _make_app, _mint_jwt

_KNOWN_EMAIL = "known@example.com"


def _seed_user(db: FakeDB, email: str = _KNOWN_EMAIL) -> str:
    """Insert a matching user so SSO mints a session instead of 403-ing."""
    uid = uuid.uuid4().hex
    db._users[uid] = {
        "id": uid,
        "username": "known",
        "email": email,
        "password_hash": "x",
        "display_name": "Known",
        "must_change_password": 0,
        "session_epoch": 0,
        "created_at": "",
        "last_login_at": None,
    }
    return uid


def _has_session_cookie(resp) -> bool:
    return any(SESSION_COOKIE in v for v in resp.headers.get_list("set-cookie"))


@pytest.mark.asyncio
async def test_post_sso_with_json_body_mints_session():
    db = FakeDB()
    _seed_user(db)
    app = _make_app(db)
    token = _mint_jwt(_KNOWN_EMAIL)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/auth/sso", json={"token": token})

    assert resp.status_code in (302, 307), resp.text
    assert _has_session_cookie(resp)


@pytest.mark.asyncio
async def test_post_sso_with_bearer_header_mints_session():
    db = FakeDB()
    _seed_user(db)
    app = _make_app(db)
    token = _mint_jwt(_KNOWN_EMAIL)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/auth/sso",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code in (302, 307), resp.text
    assert _has_session_cookie(resp)


@pytest.mark.asyncio
async def test_post_sso_without_token_returns_400():
    db = FakeDB()
    _seed_user(db)
    app = _make_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/auth/sso", json={})

    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_legacy_get_sso_still_works_when_flag_enabled(monkeypatch):
    # Default (unset) keeps the legacy query-param channel enabled for rollout.
    monkeypatch.delenv("ODIGOS_SSO_ALLOW_QUERY_TOKEN", raising=False)
    db = FakeDB()
    _seed_user(db)
    app = _make_app(db)
    token = _mint_jwt(_KNOWN_EMAIL)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/auth/sso", params={"token": token})

    assert resp.status_code in (302, 307), resp.text
    assert _has_session_cookie(resp)
