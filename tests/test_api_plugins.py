"""Tests for plugins list API endpoint."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.plugins import router


def _make_app(plugin_manager, settings=None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.plugin_manager = plugin_manager
    if settings is None:
        settings = type("S", (), {"api_key": "test-key"})()
    app.state.settings = settings
    app.state.config_path = "config.yaml"
    app.state.env_path = ".env"
    return app


class TestMergePlugins:
    def test_list_plugins_merges_metadata_and_status(self):
        from odigos.api.plugins import _merge_plugins

        metadata = [
            {
                "id": "searxng",
                "name": "SearXNG Web Search",
                "description": "Adds web search",
                "category": "tools",
                "requires": [],
                "config_keys": [
                    {"key": "searxng_url", "required": True, "description": "URL", "type": "url"},
                ],
            },
        ]
        loaded = [
            {"name": "searxng", "file": "plugins/searxng/__init__.py", "pattern": "register", "status": "active"},
        ]
        settings = MagicMock()
        settings.searxng_url = "http://localhost:8080"

        result = _merge_plugins(metadata, loaded, settings)
        assert len(result) == 1
        p = result[0]
        assert p["id"] == "searxng"
        assert p["status"] == "active"
        assert p["config_keys"][0]["configured"] is True

    def test_unconfigured_plugin_shows_available(self):
        from odigos.api.plugins import _merge_plugins

        metadata = [
            {
                "id": "searxng",
                "name": "SearXNG",
                "description": "",
                "category": "tools",
                "requires": [],
                "config_keys": [
                    {"key": "searxng_url", "required": True, "description": "URL", "type": "url"},
                ],
            },
        ]
        loaded = []
        settings = MagicMock()
        settings.searxng_url = ""

        result = _merge_plugins(metadata, loaded, settings)
        assert result[0]["status"] == "available"
        assert result[0]["config_keys"][0]["configured"] is False

    def test_dotted_config_key_resolution(self):
        from odigos.api.plugins import _resolve_setting

        settings = MagicMock()
        settings.gws = MagicMock()
        settings.gws.enabled = True

        assert _resolve_setting(settings, "gws.enabled") is True

    def test_dotted_config_key_missing(self):
        from odigos.api.plugins import _resolve_setting

        settings = MagicMock(spec=[])

        assert _resolve_setting(settings, "nonexistent.key") is None

    def test_merge_preserves_metadata_fields(self):
        from odigos.api.plugins import _merge_plugins

        metadata = [
            {
                "id": "test_plugin",
                "name": "Test Plugin",
                "description": "A test",
                "category": "providers",
                "requires": ["numpy"],
                "config_keys": [],
            },
        ]
        loaded = [
            {"name": "test_plugin", "file": "plugins/test_plugin/__init__.py", "pattern": "register", "status": "active"},
        ]
        settings = MagicMock()

        result = _merge_plugins(metadata, loaded, settings)
        p = result[0]
        assert p["name"] == "Test Plugin"
        assert p["description"] == "A test"
        assert p["category"] == "providers"
        assert p["requires"] == ["numpy"]

    def test_error_status_from_loaded(self):
        from odigos.api.plugins import _merge_plugins

        metadata = [
            {
                "id": "broken",
                "name": "Broken",
                "description": "",
                "category": "tools",
                "requires": [],
                "config_keys": [],
            },
        ]
        loaded = [
            {"name": "broken", "file": "plugins/broken/__init__.py", "pattern": "register", "status": "error", "error_message": "ImportError"},
        ]
        settings = MagicMock()

        result = _merge_plugins(metadata, loaded, settings)
        assert result[0]["status"] == "error"


@pytest.mark.asyncio
async def test_list_plugins_endpoint():
    pm = MagicMock()
    pm.loaded_plugins = [
        {"name": "searxng", "file": "plugins/searxng/__init__.py", "pattern": "register", "status": "active"},
    ]
    pm.scan_metadata.return_value = [
        {
            "id": "searxng",
            "name": "SearXNG Web Search",
            "description": "Adds web search",
            "category": "tools",
            "requires": [],
            "config_keys": [
                {"key": "searxng_url", "required": True, "description": "URL", "type": "url"},
            ],
        },
    ]

    settings = MagicMock()
    settings.api_key = "test-key"
    settings.searxng_url = "http://localhost:8080"

    app = _make_app(pm, settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as client:
        resp = await client.get("/api/plugins")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["plugins"]) == 1
    assert data["plugins"][0]["id"] == "searxng"
    assert data["plugins"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_list_plugins_empty():
    pm = MagicMock()
    pm.loaded_plugins = []
    pm.scan_metadata.return_value = []

    settings = MagicMock()
    settings.api_key = "test-key"

    app = _make_app(pm, settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as client:
        resp = await client.get("/api/plugins")

    assert resp.status_code == 200
    assert resp.json()["plugins"] == []
