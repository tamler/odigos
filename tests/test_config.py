import os
import tempfile

import yaml

from odigos.config import (
    BudgetConfig,
    MCPConfig,
    MCPServerConfig,
    Settings,
    SkillsConfig,
    load_settings,
)


def test_settings_from_env_and_yaml():
    """Settings load a yaml config and expand ${ENV_VAR} in string values."""
    config = {
        "agent": {"name": "TestBot"},
        "database": {"path": "data/test.db"},
        "providers": {
            "test": {"base_url": "https://api.example.com/v1", "api_key": "${TEST_KEY}"},
        },
        "models": {
            "mini": {"provider": "test", "id": "test/model"},
            "backup": {"provider": "test", "id": "test/fallback"},
        },
        "llm": {
            "fast": "mini",
            "fallback": "backup",
            "max_tokens": 512,
            "temperature": 0.5,
        },
        "services": {"telegram": "test-token-123"},
        "telegram": {"mode": "polling", "webhook_url": ""},
        "server": {"host": "127.0.0.1", "port": 9000},
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        config_path = f.name

    try:
        os.environ["TEST_KEY"] = "resolved-secret-abc"
        settings = load_settings(config_path)

        assert settings.telegram_bot_token == "test-token-123"
        assert settings.service_key("telegram") == "test-token-123"
        assert settings.providers["test"].api_key == "resolved-secret-abc"
        assert settings.providers["test"].base_url == "https://api.example.com/v1"
        assert settings.models["mini"].id == "test/model"
        assert settings.llm.fast == "mini"
        assert settings.llm.fallback == "backup"
        assert settings.agent.name == "TestBot"
        assert settings.database.path == "data/test.db"
        assert settings.llm.max_tokens == 512
        assert settings.telegram.mode == "polling"
        assert settings.server.port == 9000
    finally:
        os.environ.pop("TEST_KEY", None)
        os.unlink(config_path)


def test_settings_defaults():
    """Settings with only routing aliases still validate and expose defaults."""
    settings = Settings(
        services={"telegram": "tok"},
        providers={"x": {"base_url": "https://a.example/v1", "api_key": "k"}},
        models={"m": {"provider": "x", "id": "id/x"}},
        llm={"fast": "m"},
    )
    assert settings.agent.name == "Odigos"
    assert settings.database.path == "data/odigos.db"
    assert settings.llm.max_tokens == 4096
    assert settings.llm.fast == "m"
    assert settings.telegram.mode == "polling"
    assert settings.server.port == 8000


def test_searxng_config_from_env(monkeypatch):
    """SearXNG config reads URL, username, password from env vars."""
    monkeypatch.setenv("SEARXNG_URL", "https://search.example.com")
    monkeypatch.setenv("SEARXNG_USERNAME", "nimda")
    monkeypatch.setenv("SEARXNG_PASSWORD", "secret123")

    settings = Settings(services={"telegram": "test-token"})
    assert settings.searxng_url == "https://search.example.com"
    assert settings.searxng_username == "nimda"
    assert settings.searxng_password == "secret123"


class TestNewConfigSections:
    def test_budget_config_defaults(self):
        cfg = BudgetConfig()
        assert cfg.daily_limit_usd == 1.00
        assert cfg.monthly_limit_usd == 20.00

    def test_skills_config_defaults(self):
        cfg = SkillsConfig()
        assert cfg.path == "skills"

    def test_settings_includes_new_sections(self):
        settings = Settings(services={"telegram": "test"})
        assert settings.budget.daily_limit_usd == 1.00
        assert settings.skills.path == "skills"


class TestMCPConfig:
    def test_mcp_config_defaults(self):
        """MCPConfig defaults to empty servers dict."""
        cfg = MCPConfig()
        assert cfg.servers == {}

    def test_mcp_server_config_parsing(self):
        """MCPServerConfig parses command, args, env."""
        cfg = MCPServerConfig(command="npx", args=["-y", "server"], env={"TOKEN": "abc"})
        assert cfg.command == "npx"
        assert cfg.args == ["-y", "server"]
        assert cfg.env == {"TOKEN": "abc"}

    def test_mcp_server_config_defaults(self):
        """MCPServerConfig has sensible defaults for args and env."""
        cfg = MCPServerConfig(command="python")
        assert cfg.args == []
        assert cfg.env == {}

    def test_settings_includes_mcp(self):
        """Settings has mcp field with MCPConfig default."""
        fields = Settings.model_fields
        assert "mcp" in fields
