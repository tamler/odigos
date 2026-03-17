"""Query classifier with heuristic (Tier 1) and LLM-based (Tier 2) classification."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from odigos.core.prompt_loader import load_prompt

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = (
    'Classify this user message and extract metadata. Respond ONLY with valid JSON, no other text.\n\n'
    'Message: "{message}"\n\n'
    'Respond with:\n'
    '{{"classification": "simple|standard|document_query|complex|planning", '
    '"entities": ["entity1"], "confidence": 0.85, '
    '"search_queries": ["optimized query"], "sub_questions": ["sub-question 1"]}}\n\n'
    'Classification guide:\n'
    '- simple: greetings, acknowledgments, very short messages\n'
    '- standard: normal questions and requests\n'
    '- document_query: questions about uploaded documents or files\n'
    '- complex: multi-part questions, comparisons, analysis requests\n'
    '- planning: goal-setting, scheduling, strategy requests\n\n'
    'Only include sub_questions for complex and planning classifications.\n'
    'Only include search_queries when the message could benefit from document/memory search.'
)

_VALID_CLASSIFICATIONS = {"simple", "standard", "document_query", "complex", "planning"}

_DOCUMENT_PATTERNS = [
    "in the document", "in the file", "in the pdf",
    "across all", "in all documents", "search for", "search the",
]

_COMPLEX_PATTERNS = [
    "compare", "difference between", "step by step",
    "walk me through", "analyze", "and also", "additionally",
]

_PLANNING_PATTERNS = [
    "plan for", "schedule", "how should i",
    "help me figure out", "what steps", "create a plan",
]

_GREETING_WORDS = {"hi", "hello", "hey", "thanks", "bye", "ok", "yes", "no"}


@dataclass
class QueryAnalysis:
    classification: str
    confidence: float
    entities: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    sub_questions: list[str] = field(default_factory=list)
    tier: int = 1


class QueryClassifier:
    """Classifies user queries using heuristics first, then an LLM fallback."""

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        db: Optional[Database] = None,
    ) -> None:
        self.provider = provider
        self.db = db

    async def classify(self, message: str) -> QueryAnalysis:
        heuristic = self._classify_heuristic(message)
        if heuristic is not None:
            return QueryAnalysis(classification=heuristic, confidence=1.0, tier=1)

        if self.provider is None:
            return QueryAnalysis(classification="standard", confidence=0.5, tier=2)

        return await self._classify_llm(message)

    def _classify_heuristic(self, message: str) -> str | None:
        lower = message.lower().strip()

        # Check in specificity order: document > complex > planning > simple
        for pattern in _DOCUMENT_PATTERNS:
            if pattern in lower:
                return "document_query"

        for pattern in _COMPLEX_PATTERNS:
            if pattern in lower:
                return "complex"

        for pattern in _PLANNING_PATTERNS:
            if pattern in lower:
                return "planning"

        words = re.findall(r"\w+", lower)
        if len(words) <= 3 and "?" not in message:
            if any(w in _GREETING_WORDS for w in words):
                return "simple"

        return None

    async def _classify_llm(self, message: str) -> QueryAnalysis:
        try:
            prompt_template = load_prompt("classifier.md", fallback=_FALLBACK_PROMPT)
            prompt = prompt_template.replace("{message}", message)

            response = await self.provider.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=512,
            )

            data = json.loads(response.content)
            classification = data.get("classification", "standard")
            if classification not in _VALID_CLASSIFICATIONS:
                classification = "standard"

            return QueryAnalysis(
                classification=classification,
                confidence=float(data.get("confidence", 0.7)),
                entities=data.get("entities", []),
                search_queries=data.get("search_queries", []),
                sub_questions=data.get("sub_questions", []),
                tier=2,
            )
        except Exception:
            logger.warning("Tier 2 classification failed, falling back to standard", exc_info=True)
            return QueryAnalysis(classification="standard", confidence=0.5, tier=2)
