"""Tests for API key authentication dependency."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from odigos.api.deps import require_api_key


def _make_app(api_key_value: str) -> FastAPI:
    """Create a minimal FastAPI app with the auth dependency for testing."""
    app = FastAPI()

    class _FakeSettings:
        pass

    settings = _FakeSettings()
    settings.api_key = api_key_value
    app.state.settings = settings

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
async def test_empty_api_key_allows_all():
    """Dev mode: when api_key is empty, all requests pass without auth."""
    app = _make_app("")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/protected")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
