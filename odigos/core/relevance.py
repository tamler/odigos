"""Score context sections for relevance to the current query."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def score_section_relevance(
    query: str,
    section_name: str,
    section_content: str,
    classification: str = "",
) -> float:
    """Score how relevant a context section is to the current query.

    Returns 0.0 to 1.0. Uses keyword overlap and classification rules.
    Fast -- no LLM call, just NLP.
    """
    if not section_content or not query:
        return 0.0

    try:
        from textblob import TextBlob

        query_blob = TextBlob(query.lower())
        section_blob = TextBlob(section_content.lower()[:500])

        query_words = set(
            str(w) for w in query_blob.words if len(str(w)) > 3
        )
        section_words = set(
            str(w) for w in section_blob.words if len(str(w)) > 3
        )

        if not query_words:
            return 0.5  # Can't score, include by default

        # Word overlap ratio
        overlap = len(query_words & section_words)
        overlap_score = min(
            overlap / max(len(query_words), 1), 1.0
        )

        # Noun phrase overlap (stronger signal)
        query_phrases = set(
            str(p).lower() for p in query_blob.noun_phrases
        )
        section_phrases = set(
            str(p).lower() for p in section_blob.noun_phrases
        )
        phrase_overlap = len(query_phrases & section_phrases)
        phrase_score = min(
            phrase_overlap / max(len(query_phrases), 1), 1.0
        )

        # Combined score (phrases weighted higher)
        base_score = (overlap_score * 0.4) + (phrase_score * 0.6)

    except ImportError:
        base_score = 0.5  # Fallback: include everything

    # Classification-based boosting
    boost = _classification_boost(section_name, classification)

    return min(base_score + boost, 1.0)


def _classification_boost(
    section_name: str, classification: str
) -> float:
    """Boost sections important for certain query types."""
    boosts = {
        "simple": {
            "user_profile": 0.2,
            "user_facts": 0.3,
        },
        "document_query": {
            "memory_context": 0.5,
            "doc_listing": 0.4,
            "experiences": 0.2,
        },
        "complex": {
            "skill_hints": 0.3,
            "experiences": 0.3,
            "corrections": 0.2,
            "recovery_briefing": 0.4,
        },
        "planning": {
            "recovery_briefing": 0.5,
            "skill_hints": 0.3,
            "experiences": 0.2,
        },
    }

    category_boosts = boosts.get(classification, {})
    return category_boosts.get(section_name, 0.0)


# Sections that should ALWAYS be included regardless of score
ALWAYS_INCLUDE = {
    "personality",
    "user_profile",
    "user_facts",
    "active_plan",
    "page_context",
    "memory_context",     # Already relevance-filtered by memory manager
    "recovery_briefing",  # Critical for plan continuity
    "skill_catalog",      # Agent needs to know available skills
}

# Minimum score threshold to include a section
MIN_RELEVANCE = 0.15


def prune_sections(
    query: str,
    sections: dict[str, str],
    classification: str = "",
    token_budget: int = 0,
) -> dict[str, str]:
    """Prune low-relevance sections from context.

    Returns only sections that pass the relevance threshold.
    Always includes critical sections regardless of score.
    """
    if not sections:
        return sections

    scored = []
    for name, content in sections.items():
        if name in ALWAYS_INCLUDE:
            scored.append((name, content, 1.0))
            continue

        score = score_section_relevance(
            query, name, content, classification,
        )
        scored.append((name, content, score))

    # Sort by score descending
    scored.sort(key=lambda x: x[2], reverse=True)

    # Filter by threshold
    result = {}
    for name, content, score in scored:
        if score >= MIN_RELEVANCE or name in ALWAYS_INCLUDE:
            result[name] = content

    pruned = len(sections) - len(result)
    if pruned > 0:
        logger.info(
            "Context pruning: dropped %d/%d sections "
            "(query: '%s', classification: %s)",
            pruned, len(sections),
            query[:50], classification,
        )

    return result
