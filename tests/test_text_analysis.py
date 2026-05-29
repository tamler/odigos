import pytest

pytest.importorskip("textblob")

from odigos.tools.text_analysis import TextAnalysisTool


def _nltk_corpus_missing() -> bool:
    """True when the NLTK tokenizer corpus needed for noun-phrase extraction
    isn't downloaded. The production tool degrades gracefully in that case
    (returns a download hint), so tests that require *successful* analysis are
    skipped rather than failed when the corpus is absent."""
    try:
        import nltk
        nltk.data.find("tokenizers/punkt_tab/english/")
        return False
    except Exception:
        return True


requires_nltk_corpus = pytest.mark.skipif(
    _nltk_corpus_missing(),
    reason="NLTK punkt_tab corpus not downloaded (run: python -m textblob.download_corpora)",
)


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


@requires_nltk_corpus
@pytest.mark.asyncio
async def test_noun_phrases():
    tool = TextAnalysisTool()
    result = await tool.execute({
        "text": "The quick brown fox jumps over the lazy dog",
        "action": "noun_phrases",
    })
    assert result.success
    assert "[Noun Phrases]" in result.data


@requires_nltk_corpus
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
