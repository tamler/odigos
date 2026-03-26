"""Fact contradiction detection — check new facts against existing ones.

When storing a new fact, find semantically similar existing facts and
use LLM to determine if they contradict. If so, update the old fact
instead of keeping both.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.core.llm_prompt import run_prompt

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.base import LLMProvider
    from odigos.providers.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)

# Similarity threshold — facts closer than this are candidates for contradiction
_SIMILARITY_THRESHOLD = 0.75

_CONTRADICTION_PROMPT = """\
You are checking if a new fact contradicts an existing fact about a user.

Existing fact: "{existing}"
New fact: "{new}"

Respond with EXACTLY one of:
- CONTRADICTS — the new fact directly conflicts with the existing fact (e.g., "lives in NYC" vs "lives in London")
- UPDATES — the new fact is a more recent version of the same information (e.g., "works at Google" vs "works at Meta")
- SUPPLEMENTS — the new fact adds information without conflicting (e.g., "likes coffee" and "prefers dark roast")
- UNRELATED — the facts are about different topics despite surface similarity

Respond with just the single word."""


async def find_similar_facts(
    db: Database,
    embedder: EmbeddingProvider | None,
    new_fact: str,
    limit: int = 5,
) -> list[dict]:
    """Find existing facts semantically similar to the new one."""
    if not embedder:
        # Fallback: simple keyword overlap
        words = set(new_fact.lower().split())
        all_facts = await db.fetch_all(
            "SELECT id, fact, category, confidence FROM user_facts ORDER BY updated_at DESC LIMIT 100"
        )
        results = []
        for f in all_facts:
            existing_words = set(f["fact"].lower().split())
            overlap = len(words & existing_words) / max(len(words | existing_words), 1)
            if overlap > 0.3:
                results.append({**dict(f), "similarity": overlap})
        return sorted(results, key=lambda x: x["similarity"], reverse=True)[:limit]

    # Use embeddings for semantic similarity
    try:
        new_vec = await embedder.embed(new_fact)

        # Query sqlite-vec for similar facts
        # We need to check if facts have been indexed in the vector store
        # For now, use the simpler approach: embed and compare against all facts
        all_facts = await db.fetch_all(
            "SELECT id, fact, category, confidence FROM user_facts ORDER BY updated_at DESC LIMIT 100"
        )
        if not all_facts:
            return []

        results = []
        for f in all_facts:
            try:
                fact_vec = await embedder.embed(f["fact"])
                # Cosine similarity
                dot = sum(a * b for a, b in zip(new_vec, fact_vec))
                norm_a = sum(a * a for a in new_vec) ** 0.5
                norm_b = sum(b * b for b in fact_vec) ** 0.5
                similarity = dot / (norm_a * norm_b) if norm_a and norm_b else 0
                if similarity > _SIMILARITY_THRESHOLD:
                    results.append({**dict(f), "similarity": similarity})
            except Exception:
                continue

        return sorted(results, key=lambda x: x["similarity"], reverse=True)[:limit]
    except Exception:
        logger.debug("Embedding-based fact search failed, using fallback", exc_info=True)
        return []


async def check_and_store_fact(
    db: Database,
    fact: str,
    category: str = "general",
    source: str = "user_stated",
    confidence: float = 1.0,
    provider: LLMProvider | None = None,
    embedder: EmbeddingProvider | None = None,
    model: str = "",
) -> dict:
    """Store a fact, checking for contradictions with existing facts.

    Returns:
        dict with keys:
        - action: "stored" | "updated" | "duplicate"
        - fact_id: the ID of the stored/updated fact
        - replaced: the old fact text if one was replaced (or None)
        - message: human-readable description of what happened
    """
    now = datetime.now(timezone.utc).isoformat()
    fact_id = uuid.uuid4().hex

    # 1. Check exact duplicate
    existing = await db.fetch_one("SELECT id FROM user_facts WHERE fact = ?", (fact,))
    if existing:
        await db.execute(
            "UPDATE user_facts SET updated_at = ?, confidence = ? WHERE id = ?",
            (now, confidence, existing["id"]),
        )
        return {
            "action": "duplicate",
            "fact_id": existing["id"],
            "replaced": None,
            "message": f"Updated existing fact: {fact}",
        }

    # 2. Find similar facts
    similar = await find_similar_facts(db, embedder, fact, limit=3)

    # 3. If we have similar facts and an LLM, check for contradictions
    if similar and provider:
        for s in similar:
            try:
                prompt = _CONTRADICTION_PROMPT.format(existing=s["fact"], new=fact)
                response = await run_prompt(provider, prompt, model=model)
                verdict = response.content.strip().upper() if hasattr(response, 'content') else str(response).strip().upper()

                if verdict in ("CONTRADICTS", "UPDATES"):
                    old_fact = s["fact"]
                    # Replace the old fact with the new one
                    await db.execute(
                        "UPDATE user_facts SET fact = ?, category = ?, source = ?, "
                        "confidence = ?, updated_at = ? WHERE id = ?",
                        (fact, category, source, confidence, now, s["id"]),
                    )
                    logger.info(
                        "Fact %s: replaced '%s' with '%s'",
                        verdict.lower(), old_fact[:50], fact[:50],
                    )
                    return {
                        "action": "updated",
                        "fact_id": s["id"],
                        "replaced": old_fact,
                        "message": f"Updated fact (was: {old_fact})",
                    }
            except Exception:
                logger.debug("Contradiction check failed for fact %s", s["id"], exc_info=True)
                continue

    # 4. No contradiction found — store as new
    await db.execute(
        "INSERT INTO user_facts (id, fact, category, source, confidence, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fact_id, fact, category, source, confidence, now, now),
    )
    return {
        "action": "stored",
        "fact_id": fact_id,
        "replaced": None,
        "message": f"Remembered: {fact} [{category}]",
    }
