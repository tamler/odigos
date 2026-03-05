import os
import tempfile

import yaml

from odigos.config import (
    BudgetConfig,
    ContextConfig,
    RouterConfig,
    Settings,
    SkillsConfig,
    load_settings,
)


def test_settings_from_env_and_yaml():
    """Settings load from .env vars + config.yaml."""
    config = {
        "agent": {"name": "TestBot"},
        "database": {"path": "data/test.db"},
        "openrouter": {
            "default_model": "test/model",
            "fallback_model": "test/fallback",
            "max_tokens": 512,
            "temperature": 0.5,
        },
        "telegram": {"mode": "polling", "webhook_url": ""},
        "server": {"host": "127.0.0.1", "port": 9000},
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        config_path = f.name

    try:
        os.environ["TELEGRAM_BOT_TOKEN"] = "test-token-123"
        os.environ["OPENROUTER_API_KEY"] = "test-key-456"

        settings = load_settings(config_path)

        assert settings.telegram_bot_token == "test-token-123"
        assert settings.openrouter_api_key == "test-key-456"
        assert settings.agent.name == "TestBot"
        assert settings.database.path == "data/test.db"
        assert settings.openrouter.default_model == "test/model"
        assert settings.openrouter.max_tokens == 512
        assert settings.telegram.mode == "polling"
        assert settings.server.port == 9000
    finally:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("OPENROUTER_API_KEY", None)
        os.unlink(config_path)


def test_settings_defaults():
    """Settings have sensible defaults from config.yaml.example."""
    settings = Settings(
        telegram_bot_token="tok",
        openrouter_api_key="key",
    )
    assert settings.agent.name == "Odigos"
    assert settings.database.path == "data/odigos.db"
    assert settings.openrouter.max_tokens == 4096
    assert settings.telegram.mode == "polling"
    assert settings.server.port == 8000


def test_searxng_config_from_env(monkeypatch):
    """SearXNG config reads URL, username, password from env vars."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("SEARXNG_URL", "https://search.example.com")
    monkeypatch.setenv("SEARXNG_USERNAME", "nimda")
    monkeypatch.setenv("SEARXNG_PASSWORD", "secret123")

    from odigos.config import Settings

    settings = Settings()
    assert settings.searxng_url == "https://search.example.com"
    assert settings.searxng_username == "nimda"
    assert settings.searxng_password == "secret123"


class TestNewConfigSections:
    def test_budget_config_defaults(self):
        cfg = BudgetConfig()
        assert cfg.daily_limit_usd == 1.00
        assert cfg.monthly_limit_usd == 20.00

    def test_router_config_defaults(self):
        cfg = RouterConfig()
        assert len(cfg.free_pool) > 0
        assert cfg.rate_limit_rpm == 20

    def test_context_config_defaults(self):
        cfg = ContextConfig()
        assert cfg.max_tokens == 12000

    def test_skills_config_defaults(self):
        cfg = SkillsConfig()
        assert cfg.path == "skills"

    def test_settings_includes_new_sections(self):
        settings = Settings(
            telegram_bot_token="test",
            openrouter_api_key="test",
        )
        assert settings.budget.daily_limit_usd == 1.00
        assert settings.router.free_pool is not None
        assert settings.context.max_tokens == 12000
        assert settings.skills.path == "skills"
