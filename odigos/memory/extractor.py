"""Structured entity/fact/relationship extraction from conversations.

Replaces the fragile <!--entities--> HTML comment pattern. Runs a single
cheap LLM call to extract structured knowledge from each conversation turn.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_EMPTY = {"entities": [], "facts": [], "relationships": []}

_SMALL_TALK = re.compile(
    r"^(ok|okay|yes|no|yeah|nah|sure|thanks|thank you|cool|got it|"
    r"nice|great|awesome|perfect|good|fine|right|yep|nope|hm+|ah+|oh+)[\.\!\?]?$",
    re.IGNORECASE,
)

_MIN_MESSAGE_LENGTH = 20

_EXTRACTION_PROMPT = """\
Extract entities, facts, and relationships from this conversation turn.
Return JSON only, no explanation.

User: {user_message}
Assistant: {assistant_response}

Return this exact JSON structure (empty arrays if nothing to extract):
{{"entities": [{{"name": "...", "type": "person|tool|project|place|organization|concept", "summary": "..."}}],
 "facts": [{{"text": "...", "category": "preference|knowledge|goal|habit|general", "about": "entity name"}}],
 "relationships": [{{"from": "entity name", "relationship": "verb phrase", "to": "entity name"}}]}}"""


def content_hash(text: str) -> str:
    """SHA-256 hash of text for dedup."""
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16]


async def extract_knowledge(
    provider: LLMProvider,
    user_message: str,
    assistant_response: str,
    model: str = "",
) -> dict:
    """Extract entities, facts, and relationships from a conversation turn.

    Returns {"entities": [...], "facts": [...], "relationships": [...]}.
    Returns empty lists on small talk, short messages, or extraction failure.
    """
    # Relevance gate
    if len(user_message.strip()) < _MIN_MESSAGE_LENGTH:
        return _EMPTY
    if _SMALL_TALK.match(user_message.strip()):
        return _EMPTY

    prompt = _EXTRACTION_PROMPT.format(
        user_message=user_message[:500],
        assistant_response=assistant_response[:500],
    )

    try:
        response = await provider.complete(
            [{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.1,
            model=model or None,
            response_format={"type": "json_object"},
        )
        raw = response.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw)
        parsed = json.loads(raw)
        return {
            "entities": parsed.get("entities", []),
            "facts": parsed.get("facts", []),
            "relationships": parsed.get("relationships", []),
        }
    except json.JSONDecodeError as e:
        logger.warning("Knowledge extraction JSON parse failed: %s — raw[:200]: %s", e, raw[:200])
        return _EMPTY
    except Exception as e:
        logger.warning("Knowledge extraction failed: %s", e)
        return _EMPTY
