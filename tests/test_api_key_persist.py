"""The auto-generated dashboard api_key must persist to .env (gitignored),
not config.yaml (operator-edited, may be committed to VCS).

Mirrors how SESSION_SECRET is already persisted to .env.
"""

import pytest

from odigos.bootstrap import _persist_generated_api_key


@pytest.mark.asyncio
async def test_api_key_written_to_env_not_config(tmp_path):
    env_path = tmp_path / ".env"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("agent:\n  name: Test\n")

    key = "test-generated-key-abc123"
    await _persist_generated_api_key(str(config_path), key, env_path=str(env_path))

    # The key is in .env as an env var line the settings layer reads.
    assert env_path.exists()
    env_text = env_path.read_text()
    assert key in env_text
    assert "ODIGOS_API_KEY=" in env_text

    # The key is NOT written into config.yaml.
    config_text = config_path.read_text()
    assert key not in config_text
    # Pre-existing config content is untouched.
    assert "name: Test" in config_text


@pytest.mark.asyncio
async def test_api_key_appends_to_existing_env(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("SESSION_SECRET=existing\n")
    config_path = tmp_path / "config.yaml"

    key = "second-key-xyz789"
    await _persist_generated_api_key(str(config_path), key, env_path=str(env_path))

    env_text = env_path.read_text()
    assert "SESSION_SECRET=existing" in env_text
    assert f"ODIGOS_API_KEY={key}" in env_text


@pytest.mark.asyncio
async def test_persisted_key_loads_into_settings(tmp_path, monkeypatch):
    """The env var name written must be the one the settings layer reads."""
    env_path = tmp_path / ".env"
    config_path = tmp_path / "config.yaml"

    key = "loadable-key-456"
    await _persist_generated_api_key(str(config_path), key, env_path=str(env_path))

    # Simulate the .env being loaded into the process environment, as
    # load_settings does via load_dotenv, then construct Settings.
    line = env_path.read_text().strip()
    name, _, value = line.partition("=")
    monkeypatch.setenv(name, value)

    from odigos.config import Settings

    assert Settings().api_key == key
