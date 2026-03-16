import pytest

from odigos.config import Settings
from odigos.tools.settings_tool import ManageSettingsTool


@pytest.fixture
def tool(tmp_path):
    settings = Settings(api_key="test", llm_api_key="test")
    config_path = str(tmp_path / "config.yaml")
    return ManageSettingsTool(settings=settings, config_path=config_path)


@pytest.mark.asyncio
async def test_read_setting(tool):
    result = await tool.execute({"action": "read", "key": "browser.enabled"})
    assert result.success
    assert "False" in result.data


@pytest.mark.asyncio
async def test_list_settings(tool):
    result = await tool.execute({"action": "list"})
    assert result.success
    assert "browser.enabled" in result.data
    assert "stt.enabled" in result.data
    assert "tts.voice" in result.data


@pytest.mark.asyncio
async def test_write_blocked_key(tool):
    result = await tool.execute({"action": "write", "key": "api_key", "value": "hack"})
    assert not result.success
    assert "protected" in result.error.lower() or "denied" in result.error.lower()


@pytest.mark.asyncio
async def test_write_allowed_key(tool):
    result = await tool.execute({"action": "write", "key": "browser.enabled", "value": True})
    assert result.success
    assert tool.settings.browser.enabled is True
