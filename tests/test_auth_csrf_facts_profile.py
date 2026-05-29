"""CSRF enforcement tests for delete_fact and update_profile endpoints."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from odigos.api.auth import SESSION_COOKIE

from tests.test_auth import _CSRF, _VALID_SETUP, FakeDB, _make_auth_app


async def _authed_cookie(c: AsyncClient) -> str:
    """Run setup to create a user and return its session cookie."""
    resp = await c.post("/api/auth/setup", json=_VALID_SETUP, headers=_CSRF)
    assert resp.status_code == 200, resp.text
    return resp.cookies.get(SESSION_COOKIE)


@pytest.mark.asyncio
async def test_delete_fact_without_csrf_header_is_403():
    app = _make_auth_app(FakeDB())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cookie = await _authed_cookie(c)
        resp = await c.delete(
            "/api/auth/facts/some-id",
            cookies={SESSION_COOKIE: cookie},
        )
    assert resp.status_code == 403
    assert "csrf" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_profile_without_csrf_header_is_403():
    app = _make_auth_app(FakeDB())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cookie = await _authed_cookie(c)
        resp = await c.put(
            "/api/auth/profile",
            json={"summary": "x"},
            cookies={SESSION_COOKIE: cookie},
        )
    assert resp.status_code == 403
    assert "csrf" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_fact_with_csrf_header_not_403():
    app = _make_auth_app(FakeDB())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cookie = await _authed_cookie(c)
        resp = await c.delete(
            "/api/auth/facts/some-id",
            cookies={SESSION_COOKIE: cookie},
            headers=_CSRF,
        )
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_update_profile_with_csrf_header_not_403():
    app = _make_auth_app(FakeDB())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cookie = await _authed_cookie(c)
        resp = await c.put(
            "/api/auth/profile",
            json={"summary": "x"},
            cookies={SESSION_COOKIE: cookie},
            headers=_CSRF,
        )
    assert resp.status_code != 403
