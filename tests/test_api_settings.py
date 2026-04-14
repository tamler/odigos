"""Tests for settings GET/POST API endpoints."""

import os
import tempfile

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.settings import router
from odigos.config import Settings
from odigos.container import Container


def _make_app(settings, config_path: str, env_path: str) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.container = Container(
        settings=settings,
        config_path=config_path,
        env_path=env_path,
    )
    return app


def _make_settings(**overrides) -> Settings:
    defaults = {
        "api_key": "test-key",
        "providers": {
            "openrouter": {
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "sk-secret-key-12345",
            },
        },
        "models": {
            "scout": {"provider": "openrouter", "id": "meta-llama/llama-4-scout"},
            "gpt-5-nano": {"provider": "openrouter", "id": "openai/gpt-5-nano"},
        },
        "llm": {"fast": "scout", "fallback": "gpt-5-nano", "temperature": 0.7},
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.mark.asyncio
async def test_get_settings():
    """GET /api/settings returns providers (keys masked), models, and llm routing."""
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

    # Provider api_key is masked; base_url is visible.
    assert data["providers"]["openrouter"]["api_key"] == "****"
    assert data["providers"]["openrouter"]["base_url"] == "https://openrouter.ai/api/v1"

    # Models visible with their metadata.
    assert "scout" in data["models"]
    assert data["models"]["scout"]["id"] == "meta-llama/llama-4-scout"

    # Routing keys present.
    assert data["llm"]["fast"] == "scout"
    assert data["llm"]["fallback"] == "gpt-5-nano"

    # Other sections still there.
    assert "name" in data["agent"]
    assert "daily_limit_usd" in data["budget"]
    assert "interval_seconds" in data["heartbeat"]


@pytest.mark.asyncio
async def test_post_settings_updates_routing_and_provider_key():
    """POST updates the routing tier, a provider api_key, and plain llm fields."""
    settings = _make_settings()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as cfg_file:
        yaml.dump(
            {
                "providers": {
                    "openrouter": {
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-secret-key-12345",
                    },
                },
                "models": {
                    "scout": {"provider": "openrouter", "id": "meta-llama/llama-4-scout"},
                    "gpt-5-nano": {"provider": "openrouter", "id": "openai/gpt-5-nano"},
                },
                "llm": {"fast": "scout", "fallback": "gpt-5-nano", "temperature": 0.7},
            },
            cfg_file,
        )
        config_path = cfg_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as env_file:
        env_path = env_file.name

    try:
        app = _make_app(settings, config_path, env_path)
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": "Bearer test-key"},
        ) as client:
            # Dashboard always submits the full provider state (replace semantics).
            resp = await client.post(
                "/api/settings",
                json={
                    "providers": {
                        "openrouter": {
                            "base_url": "https://openrouter.ai/api/v1",
                            "api_key": "sk-new-key",
                        },
                    },
                    "llm": {"fast": "gpt-5-nano", "temperature": 0.9},
                    "agent": {"name": "NewAgent"},
                },
            )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok"}

        # Persisted to config.yaml
        with open(config_path) as f:
            saved = yaml.safe_load(f)
        assert saved["providers"]["openrouter"]["api_key"] == "sk-new-key"
        assert saved["llm"]["fast"] == "gpt-5-nano"
        assert saved["llm"]["temperature"] == 0.9
        assert saved["agent"]["name"] == "NewAgent"

        # Hot-reloaded into in-memory Settings
        assert settings.providers["openrouter"].api_key == "sk-new-key"
        assert settings.llm.fast == "gpt-5-nano"
        assert settings.llm.temperature == 0.9
        assert settings.agent.name == "NewAgent"
    finally:
        os.unlink(config_path)
        os.unlink(env_path)


@pytest.mark.asyncio
async def test_post_settings_masked_api_key_preserves_value():
    """Submitting api_key='****' must NOT clobber the stored provider key."""
    settings = _make_settings()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as cfg_file:
        yaml.dump(
            {
                "providers": {
                    "openrouter": {
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-secret-key-12345",
                    },
                },
                "models": {
                    "scout": {"provider": "openrouter", "id": "meta-llama/llama-4-scout"},
                },
                "llm": {"fast": "scout"},
            },
            cfg_file,
        )
        config_path = cfg_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as env_file:
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
                    "providers": {
                        "openrouter": {
                            "base_url": "https://openrouter.ai/api/v1",
                            "api_key": "****",
                        },
                    },
                },
            )

        assert resp.status_code == 200, resp.text
        with open(config_path) as f:
            saved = yaml.safe_load(f)
        assert saved["providers"]["openrouter"]["api_key"] == "sk-secret-key-12345"
    finally:
        os.unlink(config_path)
        os.unlink(env_path)


@pytest.mark.asyncio
async def test_post_settings_deletes_missing_provider():
    """Providers/models use REPLACE semantics — dropping an entry deletes it."""
    settings = _make_settings()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as cfg_file:
        yaml.dump(
            {
                "providers": {
                    "openrouter": {
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-secret-key-12345",
                    },
                    "openai": {
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-openai-old",
                    },
                },
                "models": {
                    "scout": {"provider": "openrouter", "id": "meta-llama/llama-4-scout"},
                    "gpt-5-nano": {"provider": "openrouter", "id": "openai/gpt-5-nano"},
                    "gpt-4o": {"provider": "openai", "id": "gpt-4o"},
                },
                "llm": {"fast": "scout"},
            },
            cfg_file,
        )
        config_path = cfg_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as env_file:
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
                    # Only openrouter — openai should be DELETED from disk
                    "providers": {
                        "openrouter": {
                            "base_url": "https://openrouter.ai/api/v1",
                            "api_key": "****",  # masked → preserve stored key
                        },
                    },
                    # Only scout — the others should be DELETED
                    "models": {
                        "scout": {"provider": "openrouter", "id": "meta-llama/llama-4-scout"},
                    },
                },
            )

        assert resp.status_code == 200, resp.text

        with open(config_path) as f:
            saved = yaml.safe_load(f)

        # openai provider + gpt-4o + gpt-5-nano should be gone
        assert set(saved["providers"].keys()) == {"openrouter"}
        assert set(saved["models"].keys()) == {"scout"}
        # Masked api_key preserved the original stored secret
        assert saved["providers"]["openrouter"]["api_key"] == "sk-secret-key-12345"

        # In-memory reflects the same deletions
        assert set(settings.providers.keys()) == {"openrouter"}
        assert set(settings.models.keys()) == {"scout"}
        assert settings.providers["openrouter"].api_key == "sk-secret-key-12345"
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
