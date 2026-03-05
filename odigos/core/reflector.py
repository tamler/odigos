from __future__ import annotations

import json
import logging
import re
import uuid
from typing import TYPE_CHECKING

from odigos.db import Database
from odigos.providers.base import LLMResponse

if TYPE_CHECKING:
    from odigos.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

ENTITY_PATTERN = re.compile(r"<!--entities\s*\n(.*?)\n-->", re.DOTALL)


class Reflector:
    """Evaluates results and stores learnings.

    Parses entity extraction blocks from LLM responses and passes them
    to the memory manager for storage and resolution.
    """

    def __init__(
        self,
        db: Database,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.db = db
        self.memory_manager = memory_manager

    async def reflect(
        self,
        conversation_id: str,
        response: LLMResponse,
        user_message: str | None = None,
        scrape_metadata: dict | None = None,
    ) -> None:
        # Parse and strip entity block
        content = response.content
        entities = []
        match = ENTITY_PATTERN.search(content)
        if match:
            try:
                entities = json.loads(match.group(1))
            except (json.JSONDecodeError, IndexError):
                logger.warning("Failed to parse entity block from response")
            content = ENTITY_PATTERN.sub("", content).rstrip()

        # Store the clean assistant message
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, model_used, "
            "tokens_in, tokens_out, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                conversation_id,
                "assistant",
                content,
                response.model,
                response.tokens_in,
                response.tokens_out,
                response.cost_usd,
            ),
        )

        # Pass to memory manager if available
        if self.memory_manager and user_message is not None:
            await self.memory_manager.store(
                conversation_id=conversation_id,
                user_message=user_message,
                assistant_response=content,
                extracted_entities=entities,
            )

        # Log scrape if metadata provided
        if scrape_metadata:
            url = scrape_metadata.get("url", "")
            title = scrape_metadata.get("title", "")
            content_text = scrape_metadata.get("content", "")
            summary = content_text[:200] if content_text else ""
            await self.db.execute(
                "INSERT INTO scraped_pages (id, url, title, summary) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), url, title, summary),
            )
