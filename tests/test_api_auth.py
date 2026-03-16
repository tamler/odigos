"""Tests for API key authentication dependency (require_auth / require_api_key alias)."""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.deps import require_api_key, require_auth


def _make_app(api_key_value: str) -> FastAPI:
    """Create a minimal FastAPI app with the auth dependency for testing."""
    app = FastAPI()

    class _FakeSettings:
        api_key = api_key_value
        session_secret = "test-secret-for-sessions"

    app.state.settings = _FakeSettings()

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected():
        return {"status": "ok"}

    return app


@pytest.mark.asyncio
async def test_valid_key_passes():
    app = _make_app("test-secret-key")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/protected", headers={"Authorization": "Bearer test-secret-key"}
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_missing_header_returns_401():
    app = _make_app("test-secret-key")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/protected")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_key_returns_403():
    app = _make_app("test-secret-key")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/protected", headers={"Authorization": "Bearer wrong-key"}
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_empty_api_key_no_header_returns_401():
    """When api_key is not configured and no cookie, requests get 401."""
    app = _make_app("")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/protected")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_require_auth_is_require_api_key():
    """require_api_key is an alias for require_auth."""
    assert require_api_key is require_auth
