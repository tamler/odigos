"""Query classifier with heuristic (Tier 1) and LLM-based (Tier 2) classification."""
from __future__ import annotations

import json
import logging
import re
import struct
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

try:
    from textblob import TextBlob
except ImportError:  # pragma: no cover
    TextBlob = None  # type: ignore[assignment,misc]

from odigos.core.json_utils import parse_json_response
from odigos.core.prompt_loader import load_prompt

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.memory.vectors import VectorMemory
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = (
    'Classify this user message. Respond ONLY with valid JSON.\n\n'
    'Message: "{message}"\n\n'
    '{{"classification": "simple|standard|document_query|complex|planning", "confidence": 0.85}}\n\n'
    '- simple: greetings, acknowledgments, very short messages\n'
    '- standard: normal questions and requests\n'
    '- document_query: questions about uploaded documents or files\n'
    '- complex: multi-part questions, comparisons, analysis\n'
    '- planning: goal-setting, scheduling, strategy'
)

_VALID_CLASSIFICATIONS = {"simple", "standard", "document_query", "complex", "planning"}

# Hardcoded fallback rules used when classification_rules.md is missing or unparseable
_FALLBACK_RULES: dict[str, list[str]] = {
    "document_query": [
        "in the document", "in the file", "in the pdf",
        "across all", "in all documents", "search for", "search the",
    ],
    "complex": [
        "compare", "difference between", "step by step",
        "walk me through", "analyze", "and also", "additionally",
    ],
    "planning": [
        "plan for", "schedule", "how should i",
        "help me figure out", "what steps", "create a plan",
    ],
    "simple": ["hi", "hello", "hey", "thanks", "bye", "ok", "yes", "no"],
}

# Order matters: most specific first
_RULE_ORDER = ["document_query", "complex", "planning", "simple"]

# mtime-keyed cache for parsed classification rules
_rules_cache: tuple[float, dict[str, list[str]]] | None = None


def _serialize_f32(vec: list[float]) -> bytes:
    """Serialize a list of floats to a compact binary format for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


@dataclass
class QueryAnalysis:
    classification: str
    confidence: float
    entities: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    sub_questions: list[str] = field(default_factory=list)
    tier: int = 1
    similarity_hint: str | None = None


class QueryClassifier:
    """Classifies user queries using heuristics first, then an LLM fallback."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        db: Database | None = None,
        vector_memory: VectorMemory | None = None,
    ) -> None:
        self.provider = provider
        self.db = db
        self.vector_memory = vector_memory

    @staticmethod
    def _load_rules() -> dict[str, list[str]]:
        """Load classification rules from data/agent/classification_rules.md.

        Returns a dict mapping category names to lists of signal phrases.
        Falls back to hardcoded rules if the file is missing or unparseable.
        Uses mtime-keyed cache so _parse_rules() only runs when the file changes.
        """
        global _rules_cache
        from pathlib import Path
        rules_path = Path("data/agent/classification_rules.md")
        if rules_path.exists():
            mtime = rules_path.stat().st_mtime
            if _rules_cache is not None and _rules_cache[0] == mtime:
                return _rules_cache[1]

        raw = load_prompt("classification_rules.md", fallback="", base_dir="data/agent")
        if not raw:
            return _FALLBACK_RULES

        try:
            parsed = _parse_rules(raw)
            if rules_path.exists():
                _rules_cache = (rules_path.stat().st_mtime, parsed)
            return parsed
        except Exception:
            logger.warning("Failed to parse classification_rules.md, using fallback rules", exc_info=True)
            return _FALLBACK_RULES

    async def classify(self, message: str) -> QueryAnalysis:
        # Check for similar past queries before heuristic classification
        hint = await self._find_similar(message)

        heuristic = self._classify_heuristic(message)
        if heuristic is not None:
            return QueryAnalysis(classification=heuristic, confidence=1.0, tier=1, similarity_hint=hint)

        if self.provider is None:
            return QueryAnalysis(classification="standard", confidence=0.5, tier=2, similarity_hint=hint)

        result = await self._classify_llm(message)
        result.similarity_hint = hint
        return result

    def _classify_heuristic(self, message: str) -> str | None:
        lower = message.lower().strip()
        rules = self._load_rules()

        # Check in specificity order: document > complex > planning > simple
        for category in _RULE_ORDER:
            phrases = rules.get(category, [])
            if category == "simple":
                # Simple uses word-level matching with length check
                if TextBlob is not None:
                    blob = TextBlob(lower)
                    words = list(blob.words)
                else:
                    words = re.findall(r"\w+", lower)
                if len(words) <= 3 and "?" not in message:
                    simple_words = set(phrases)
                    if any(w in simple_words for w in words):
                        return "simple"
            else:
                for pattern in phrases:
                    if pattern in lower:
                        return category

        return None

    async def _classify_llm(self, message: str) -> QueryAnalysis:
        try:
            prompt_template = load_prompt("classifier.md", fallback=_FALLBACK_PROMPT)
            prompt = prompt_template.replace("{message}", message)

            from odigos.core.llm_prompt import call_llm
            response = await call_llm(
                self.provider,
                [{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=512, log_name="classifier",
            )
            if not response:
                return QueryAnalysis(classification="standard", confidence=0.5, tier=2)

            data = parse_json_response(response.content)
            if data is None:
                return QueryAnalysis(classification="standard", confidence=0.5, tier=2)
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

    async def store_query_embedding(self, message: str, rowid: int) -> None:
        """Store an embedding for a query_log row. Called by the executor after logging."""
        if self.vector_memory is None:
            return
        if self.db is None:
            return
        try:
            vector = await self.vector_memory.embedder.embed(message)
            await self.db.execute(
                "INSERT INTO query_log_vec (query_log_rowid, embedding) VALUES (?, ?)",
                (rowid, _serialize_f32(vector)),
            )
        except Exception:
            logger.debug("Failed to store query embedding for rowid=%s", rowid, exc_info=True)

    async def _find_similar(self, message: str) -> str | None:
        """Find similar past queries and return a routing hint if a strong match exists."""
        if self.vector_memory is None or self.db is None:
            return None

        try:
            # Check that the vec table has rows before querying
            count_row = await self.db.fetch_one("SELECT COUNT(*) as cnt FROM query_log_vec")
            if not count_row or count_row["cnt"] == 0:
                return None

            vector = await self.vector_memory.embedder.embed(message)

            rows = await self.db.fetch_all(
                """
                SELECT ql.classification, ql.evaluation_score, v.distance
                FROM (
                    SELECT query_log_rowid, distance
                    FROM query_log_vec
                    WHERE embedding MATCH ?
                    ORDER BY distance
                    LIMIT 3
                ) v
                JOIN query_log ql ON ql.rowid = v.query_log_rowid
                WHERE ql.evaluation_score > 0.7
                """,
                (_serialize_f32(vector), ),
            )

            if rows and rows[0]["distance"] < 0.15:
                best = rows[0]
                return (
                    f"Similar past query classified as '{best['classification']}' "
                    f"with good results"
                )
            return None
        except Exception:
            logger.debug("Similarity search failed", exc_info=True)
            return None


def _parse_rules(raw: str) -> dict[str, list[str]]:
    """Parse classification_rules.md format into {category: [phrases]}.

    Expected format after frontmatter:
        [category_name]
        phrase1, phrase2, phrase3
    """
    rules: dict[str, list[str]] = {}

    # Strip YAML frontmatter if present
    body = raw
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]

    current_category: str | None = None
    for line in body.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # Match [category] headers
        header_match = re.match(r"^\[(\w+)\]$", line)
        if header_match:
            current_category = header_match.group(1)
            rules[current_category] = []
            continue

        if current_category is not None:
            phrases = [p.strip() for p in line.split(",") if p.strip()]
            rules[current_category].extend(phrases)

    if not rules:
        raise ValueError("No rules parsed from classification_rules.md")

    return rules
