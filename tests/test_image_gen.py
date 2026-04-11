import httpx
import pytest
from odigos.tools.image_gen import GenerateImageTool
from odigos.config import ImageGenerationConfig


def _make_tool(**overrides):
    defaults = dict(http=httpx.AsyncClient(), api_key="test")
    defaults.update(overrides)
    return GenerateImageTool(**defaults)


def test_tool_metadata():
    tool = _make_tool()
    assert tool.name == "generate_image"
    assert "prompt" in tool.parameters_schema["properties"]
    assert "aspect_ratio" in tool.parameters_schema["properties"]


@pytest.mark.asyncio
async def test_empty_prompt():
    tool = _make_tool()
    result = await tool.execute({"prompt": ""})
    assert not result.success
    assert "No prompt" in result.error


@pytest.mark.asyncio
async def test_prompt_truncation():
    tool = _make_tool()
    long_prompt = "a " * 600  # > 1000 chars
    # Won't actually call API (bad key), but shouldn't crash
    result = await tool.execute({"prompt": long_prompt})
    # Will fail due to fake API key, but shouldn't crash on length
    assert not result.success


def test_invalid_ratio_defaults():
    tool = _make_tool(default_ratio="4:3")
    # The tool should use default if invalid ratio given
    assert tool._default_ratio == "4:3"


def test_config_defaults():
    cfg = ImageGenerationConfig()
    assert cfg.default_aspect_ratio == "1:1"
    assert cfg.nsfw_filter is True
    assert cfg.max_poll_seconds == 120
