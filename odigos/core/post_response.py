"""Background tasks that run AFTER the response is saved.

Entity extraction and correction detection happen here, not inline
in the agent's response. These are fire-and-forget background calls
using the background model (cheap, fast).
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from odigos.core.json_utils import parse_json_response
from odigos.core.llm_prompt import call_llm

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.memory.graph import EntityGraph
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_ENTITY_PROMPT = """Extract named entities from this conversation exchange.
Return a JSON array of objects, each with: name, type (person|project|preference|concept), relationship, detail.
Only include specific, meaningful entities. Return [] if none.

User: {user_message}
Assistant: {assistant_response}

Return ONLY the JSON array, no other text."""

_CORRECTION_PROMPT = """Is the user correcting or disagreeing with the assistant's previous response?
If YES, return a JSON object: {{"original": "what was wrong", "correction": "what user wants", "category": "tone|accuracy|preference|behavior|tool_choice", "context": "brief situation"}}
If NO, return null.

Previous assistant response: {previous_response}
User's message: {user_message}

Return ONLY the JSON (or null), no other text."""


async def extract_entities_background(
    provider: LLMProvider,
    db: Database,
    entity_graph: "EntityGraph | None",
    conversation_id: str,
    user_message: str,
    assistant_response: str,
) -> None:
    """Extract entities from the exchange in the background."""
    try:
        response = await call_llm(
            provider,
            [{"role": "user", "content": _ENTITY_PROMPT.format(
                user_message=user_message[:500],
                assistant_response=assistant_response[:500],
            )}],
            max_tokens=300,
            temperature=0.0,
            log_name="bg_entity_extract",
        )
        if not response:
            return

        entities = parse_json_response(response.content)
        if not entities or not isinstance(entities, list):
            return

        # Store entities in the entity graph
        if entity_graph:
            for ent in entities:
                if not isinstance(ent, dict) or not ent.get("name"):
                    continue
                try:
                    existing = await entity_graph.find_entity(ent["name"])
                    if not existing:
                        await entity_graph.create_entity(
                            entity_type=ent.get("type", "concept"),
                            name=ent["name"],
                            properties={"detail": ent.get("detail", ""), "source": conversation_id},
                            confidence=0.7,
                            source="post_response",
                        )
                except Exception:
                    pass

        logger.debug("Background entity extraction: %d entities", len(entities))
    except Exception:
        logger.debug("Background entity extraction failed", exc_info=True)


async def detect_correction_background(
    provider: LLMProvider,
    db: Database,
    conversation_id: str,
    user_message: str,
    previous_response: str,
) -> None:
    """Detect if the user is correcting the agent, in the background."""
    try:
        response = await call_llm(
            provider,
            [{"role": "user", "content": _CORRECTION_PROMPT.format(
                previous_response=previous_response[:500],
                user_message=user_message[:500],
            )}],
            max_tokens=200,
            temperature=0.0,
            log_name="bg_correction_detect",
        )
        if not response:
            return

        result = parse_json_response(response.content)
        if not result or not isinstance(result, dict):
            return

        # Store correction
        from datetime import datetime, timezone
        import uuid
        await db.execute(
            "INSERT INTO corrections (id, conversation_id, original, correction, category, context, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), conversation_id,
             result.get("original", ""), result.get("correction", ""),
             result.get("category", ""), result.get("context", ""),
             datetime.now(timezone.utc).isoformat()),
        )
        logger.debug("Background correction detected: %s", result.get("category"))
    except Exception:
        logger.debug("Background correction detection failed", exc_info=True)
