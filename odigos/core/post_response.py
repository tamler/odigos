"""Background tasks that run AFTER the response is saved.

Correction detection happens here, not inline in the agent's response. It is a
fire-and-forget background call using the background model (cheap, fast).

Entity extraction lived here too until 2026-08-12. It duplicated the reflector's
per-turn extraction and bypassed EntityResolver -- see the note at
core/agent.py's background block.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.core.json_utils import parse_json_response
from odigos.core.llm_prompt import call_llm

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_CORRECTION_PROMPT = """Is the user correcting or disagreeing with the assistant's previous response?
If YES, return a JSON object: {{"original": "what was wrong", "correction": "what user wants", "category": "tone|accuracy|preference|behavior|tool_choice", "context": "brief situation"}}
If NO, return null.

Previous assistant response: {previous_response}
User's message: {user_message}

Return ONLY the JSON (or null), no other text."""


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
