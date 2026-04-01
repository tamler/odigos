import pytest
pytest.importorskip("deep_translator")
from odigos.tools.translate import TranslateTool


def test_tool_metadata():
    tool = TranslateTool()
    assert tool.name == "translate_text"
    assert "text" in tool.parameters_schema["properties"]
    assert "target" in tool.parameters_schema["properties"]


@pytest.mark.asyncio
async def test_empty_text():
    tool = TranslateTool()
    result = await tool.execute({"text": ""})
    assert not result.success
    assert "No text" in result.error


@pytest.mark.asyncio
async def test_translate_basic():
    """Test basic translation (requires network)."""
    tool = TranslateTool()
    result = await tool.execute({
        "text": "Hola mundo",
        "target": "en",
    })
    assert result.success
    assert "hello" in result.data.lower() or "world" in result.data.lower()


@pytest.mark.asyncio
async def test_translate_with_source():
    tool = TranslateTool()
    result = await tool.execute({
        "text": "Bonjour",
        "target": "en",
        "source": "fr",
    })
    assert result.success
    assert "hello" in result.data.lower() or "good" in result.data.lower()
