import pytest
from odigos.tools.text_analysis import TextAnalysisTool


def test_tool_metadata():
    tool = TextAnalysisTool()
    assert tool.name == "analyze_text"
    assert "text" in tool.parameters_schema["properties"]
    assert "action" in tool.parameters_schema["properties"]
    assert "text" in tool.parameters_schema["required"]


@pytest.mark.asyncio
async def test_empty_text():
    tool = TextAnalysisTool()
    result = await tool.execute({"text": ""})
    assert not result.success
    assert "No text" in result.error


@pytest.mark.asyncio
async def test_spellcheck():
    tool = TextAnalysisTool()
    result = await tool.execute({
        "text": "ths is a tset",
        "action": "spellcheck",
    })
    assert result.success
    assert "[Spell Check]" in result.data
    # Should attempt corrections
    assert "Corrected:" in result.data or "No spelling" in result.data


@pytest.mark.asyncio
async def test_sentiment_positive():
    tool = TextAnalysisTool()
    result = await tool.execute({
        "text": "I love this amazing product",
        "action": "sentiment",
    })
    assert result.success
    assert "[Sentiment]" in result.data
    assert "positive" in result.data.lower()


@pytest.mark.asyncio
async def test_sentiment_negative():
    tool = TextAnalysisTool()
    result = await tool.execute({
        "text": "This is terrible and awful",
        "action": "sentiment",
    })
    assert result.success
    assert "[Sentiment]" in result.data
    assert "negative" in result.data.lower()


@pytest.mark.asyncio
async def test_noun_phrases():
    tool = TextAnalysisTool()
    result = await tool.execute({
        "text": "The quick brown fox jumps over the lazy dog",
        "action": "noun_phrases",
    })
    assert result.success
    assert "[Noun Phrases]" in result.data


@pytest.mark.asyncio
async def test_all_action():
    tool = TextAnalysisTool()
    result = await tool.execute({
        "text": "The weather is beautiful today",
        "action": "all",
    })
    assert result.success
    assert "[Spell Check]" in result.data
    assert "[Sentiment]" in result.data
    assert "[Language]" in result.data
    assert "[Noun Phrases]" in result.data


@pytest.mark.asyncio
async def test_invalid_action():
    tool = TextAnalysisTool()
    result = await tool.execute({
        "text": "hello",
        "action": "invalid",
    })
    assert not result.success
    assert "Invalid action" in result.error
