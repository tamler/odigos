"""Auto-generate conversation titles after the first exchange."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)


async def generate_title(provider: LLMProvider, user_message: str, assistant_response: str) -> str:
    """Generate a short conversation title from the first exchange."""
    try:
        response = await provider.complete(
            [{"role": "user", "content": (
                "Generate a short title (3-6 words, no quotes) for a conversation "
                "that starts with this exchange:\n\n"
                f"User: {user_message[:200]}\n"
                f"Assistant: {assistant_response[:200]}\n\n"
                "Title:"
            )}],
            model=getattr(provider, "fallback_model", None),
            max_tokens=20,
            temperature=0.3,
        )
        title = response.content.strip().strip('"').strip("'")
    except Exception:
        logger.warning("LLM title generation failed, using heuristic")
        title = _heuristic_title(user_message)
    if len(title) > 60:
        title = title[:57] + "..."
    return title


def _heuristic_title(user_message: str) -> str:
    """Extract a short title from the first user message without LLM."""
    text = user_message.strip().split("\n")[0]
    # Remove common prefixes
    for prefix in ("hey ", "hi ", "hello ", "please ", "can you ", "could you "):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    # Capitalize and truncate to first ~6 words
    words = text.split()[:6]
    title = " ".join(words)
    if not title:
        title = "New conversation"
    return title[0].upper() + title[1:] if title else "New conversation"


async def maybe_auto_title(
    db: Database,
    provider: LLMProvider,
    conversation_id: str,
    user_message: str,
    assistant_response: str,
) -> None:
    """Auto-title a conversation if it's the first exchange and has no title."""
    try:
        conv = await db.fetch_one(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        )
        if not conv:
            return
        if conv["title"]:
            return

        msg_count = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        if msg_count and msg_count["cnt"] > 2:
            return

        title = await generate_title(provider, user_message, assistant_response)
        await db.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title, conversation_id),
        )
        logger.debug("Auto-titled conversation %s: %s", conversation_id[:8], title)
    except Exception:
        logger.warning("Auto-title failed for %s", conversation_id, exc_info=True)
