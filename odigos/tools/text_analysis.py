"""Text analysis tool using TextBlob for NLP tasks."""
from __future__ import annotations

import asyncio
import logging

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

VALID_ACTIONS = ("spellcheck", "sentiment", "language", "noun_phrases", "all")


class TextAnalysisTool(BaseTool):
    name = "analyze_text"
    category = "analysis"
    description = (
        "Analyze text for spelling, sentiment, language, and key "
        "phrases. Actions: 'spellcheck' (correct spelling errors), "
        "'sentiment' (positive/negative/neutral score), 'language' "
        "(detect language), 'noun_phrases' (extract key noun "
        "phrases), 'all' (run all analyses)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to analyze",
            },
            "action": {
                "type": "string",
                "description": (
                    "Analysis action: 'spellcheck', 'sentiment', "
                    "'language', 'noun_phrases', or 'all'. "
                    "Default: 'all'"
                ),
                "enum": list(VALID_ACTIONS),
            },
        },
        "required": ["text"],
    }

    async def execute(self, params: dict) -> ToolResult:
        text = params.get("text", "").strip()
        if not text:
            return ToolResult(
                success=False, data="", error="No text provided"
            )

        action = params.get("action", "all").strip().lower()
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                data="",
                error=(
                    f"Invalid action '{action}'. "
                    f"Must be one of: {', '.join(VALID_ACTIONS)}"
                ),
            )

        try:
            result = await asyncio.to_thread(
                self._analyze, text, action
            )
            return ToolResult(success=True, data=result)
        except LookupError as e:
            logger.warning("TextBlob corpora missing: %s", e)
            return ToolResult(
                success=False,
                data="",
                error=(
                    "TextBlob corpora not downloaded. Run: "
                    "python -m textblob.download_corpora lite"
                ),
            )
        except ImportError:
            return ToolResult(
                success=False,
                data="",
                error="textblob is not installed",
            )
        except Exception as e:
            logger.warning("Text analysis failed: %s", e)
            return ToolResult(
                success=False, data="", error=str(e)
            )

    def _analyze(self, text: str, action: str) -> str:
        from textblob import TextBlob

        blob = TextBlob(text)
        sections: list[str] = []

        if action in ("spellcheck", "all"):
            sections.append(self._spellcheck(blob, text))

        if action in ("sentiment", "all"):
            sections.append(self._sentiment(blob))

        if action in ("language", "all"):
            sections.append(self._language(blob))

        if action in ("noun_phrases", "all"):
            sections.append(self._noun_phrases(blob))

        return "\n\n".join(sections)

    def _spellcheck(self, blob, original: str) -> str:
        corrected = str(blob.correct())
        if corrected != original:
            changes: list[str] = []
            orig_words = original.split()
            corr_words = corrected.split()
            for o, c in zip(orig_words, corr_words):
                if o != c:
                    changes.append(f"  '{o}' -> '{c}'")
            diff = "\n".join(changes) if changes else "(structural)"
            return (
                f"[Spell Check]\n"
                f"Corrected: {corrected}\n\n"
                f"Changes:\n{diff}"
            )
        return "[Spell Check]\nNo spelling errors found."

    def _sentiment(self, blob) -> str:
        polarity = blob.sentiment.polarity
        subjectivity = blob.sentiment.subjectivity
        if polarity > 0.1:
            label = "positive"
        elif polarity < -0.1:
            label = "negative"
        else:
            label = "neutral"
        return (
            f"[Sentiment]\n"
            f"Label: {label}\n"
            f"Polarity: {polarity:.3f} (-1 to 1)\n"
            f"Subjectivity: {subjectivity:.3f} (0 to 1)"
        )

    def _language(self, blob) -> str:
        try:
            lang = blob.detect_language()
            return f"[Language]\nDetected: {lang}"
        except Exception as e:
            return f"[Language]\nDetection failed: {e}"

    def _noun_phrases(self, blob) -> str:
        phrases = list(blob.noun_phrases)
        if phrases:
            listed = "\n".join(f"  - {p}" for p in phrases)
            return (
                f"[Noun Phrases]\n"
                f"Found {len(phrases)} phrase(s):\n{listed}"
            )
        return "[Noun Phrases]\nNo noun phrases found."
