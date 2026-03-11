"""Tests for plugins list API endpoint."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.plugins import router


def _make_app(plugin_manager) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.plugin_manager = plugin_manager
    app.state.settings = type("S", (), {"api_key": "test-key"})()
    return app


@pytest.mark.asyncio
async def test_list_plugins():
    pm = MagicMock()
    pm.loaded_plugins = [
        {"name": "docling", "file": "/plugins/docling.py", "pattern": "register"},
        {"name": "custom", "file": "/plugins/custom.py", "pattern": "hooks"},
    ]

    app = _make_app(pm)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as client:
        resp = await client.get("/api/plugins")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["plugins"]) == 2
    names = {p["name"] for p in data["plugins"]}
    assert names == {"docling", "custom"}
    for p in data["plugins"]:
        assert p["status"] == "loaded"
        assert p["capabilities"] == []


@pytest.mark.asyncio
async def test_plugins_with_capabilities():
    pm = MagicMock()
    pm.loaded_plugins = [
        {"name": "moonshine-stt", "capabilities": ["stt"]},
        {"name": "pocket-tts", "capabilities": ["tts"]},
        {"name": "log-tools", "capabilities": []},
    ]

    app = _make_app(pm)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as client:
        resp = await client.get("/api/plugins")

    assert resp.status_code == 200
    data = resp.json()["plugins"]
    assert data[0]["capabilities"] == ["stt"]
    assert data[1]["capabilities"] == ["tts"]
    assert data[2]["capabilities"] == []


@pytest.mark.asyncio
async def test_plugins_without_capabilities():
    """Legacy plugins without capabilities field return empty list."""
    pm = MagicMock()
    pm.loaded_plugins = [{"name": "legacy-plugin"}]

    app = _make_app(pm)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as client:
        resp = await client.get("/api/plugins")

    data = resp.json()["plugins"]
    assert data[0]["capabilities"] == []
