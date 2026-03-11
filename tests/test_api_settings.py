"""Tests for settings GET/POST API endpoints."""

import os
import tempfile

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.settings import router
from odigos.config import Settings


def _make_app(settings, config_path: str, env_path: str) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.settings = settings
    app.state.config_path = config_path
    app.state.env_path = env_path
    return app


def _make_settings(**overrides) -> Settings:
    defaults = {
        "llm_api_key": "sk-secret-key-12345",
        "api_key": "test-key",
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.mark.asyncio
async def test_get_settings():
    """GET /api/settings returns settings with masked API key."""
    settings = _make_settings()
    app = _make_app(settings, "config.yaml", ".env")

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as client:
        resp = await client.get("/api/settings")

    assert resp.status_code == 200
    data = resp.json()

    # API key must be masked
    assert data["llm_api_key"] == "****"

    # Sections must be present with expected keys
    assert "base_url" in data["llm"]
    assert "default_model" in data["llm"]
    assert "name" in data["agent"]
    assert "daily_limit_usd" in data["budget"]
    assert "interval_seconds" in data["heartbeat"]
    assert "timeout_seconds" in data["sandbox"]


@pytest.mark.asyncio
async def test_post_settings_updates_config():
    """POST /api/settings writes to config.yaml and .env and updates in-memory."""
    settings = _make_settings()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as cfg_file:
        yaml.dump({"llm": {"temperature": 0.7}}, cfg_file)
        config_path = cfg_file.name

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".env", delete=False
    ) as env_file:
        env_file.write("LLM_API_KEY=old-key\n")
        env_path = env_file.name

    try:
        app = _make_app(settings, config_path, env_path)
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": "Bearer test-key"},
        ) as client:
            resp = await client.post(
                "/api/settings",
                json={
                    "llm_api_key": "sk-new-key",
                    "llm": {"temperature": 0.9, "max_tokens": 2048},
                    "agent": {"name": "NewAgent"},
                },
            )

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        # Verify config.yaml was updated
        with open(config_path) as f:
            saved = yaml.safe_load(f)
        assert saved["llm"]["temperature"] == 0.9
        assert saved["llm"]["max_tokens"] == 2048
        assert saved["agent"]["name"] == "NewAgent"

        # Verify .env was updated
        with open(env_path) as f:
            env_content = f.read()
        assert "LLM_API_KEY=sk-new-key" in env_content

        # Verify in-memory settings were updated
        assert settings.llm_api_key == "sk-new-key"
        assert settings.llm.temperature == 0.9
        assert settings.llm.max_tokens == 2048
        assert settings.agent.name == "NewAgent"
    finally:
        os.unlink(config_path)
        os.unlink(env_path)


@pytest.mark.asyncio
async def test_get_settings_no_auth():
    """GET /api/settings returns 401 without auth header."""
    settings = _make_settings()
    app = _make_app(settings, "config.yaml", ".env")

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/settings")

    assert resp.status_code == 401
