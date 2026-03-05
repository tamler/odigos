import pytest
from odigos.config import Settings


def test_heartbeat_config_defaults():
    s = Settings(telegram_bot_token="t", openrouter_api_key="k")
    assert s.heartbeat.interval_seconds == 30
    assert s.heartbeat.max_todos_per_tick == 3


def test_sandbox_config_defaults():
    s = Settings(telegram_bot_token="t", openrouter_api_key="k")
    assert s.sandbox.timeout_seconds == 5
    assert s.sandbox.max_memory_mb == 512
    assert s.sandbox.allow_network is False


def test_heartbeat_config_override():
    s = Settings(
        telegram_bot_token="t",
        openrouter_api_key="k",
        heartbeat={"interval_seconds": 60, "max_todos_per_tick": 10},
    )
    assert s.heartbeat.interval_seconds == 60
    assert s.heartbeat.max_todos_per_tick == 10


def test_sandbox_config_override():
    s = Settings(
        telegram_bot_token="t",
        openrouter_api_key="k",
        sandbox={"timeout_seconds": 10, "max_memory_mb": 1024, "allow_network": True},
    )
    assert s.sandbox.timeout_seconds == 10
    assert s.sandbox.max_memory_mb == 1024
    assert s.sandbox.allow_network is True


def test_agent_config_has_react_settings():
    from odigos.config import AgentConfig

    config = AgentConfig()
    assert config.max_tool_turns == 25
    assert config.run_timeout_seconds == 300
