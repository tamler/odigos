from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from odigos.db import Database
from odigos.providers.base import LLMResponse

if TYPE_CHECKING:
    from odigos.core.message_bus import MessageBus
    from odigos.core.trace import Tracer
    from odigos.memory.corrections import CorrectionsManager
    from odigos.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

CORRECTION_PATTERN = re.compile(r"<!--correction\s*\n?(.*?)\n?-->\s*\Z", re.DOTALL)
CORRECTION_FALLBACK = re.compile(r"<!--correction\s*(\{.*?\})\s*\Z", re.DOTALL)


class Reflector:
    """Evaluates results and stores learnings.

    Parses entity extraction blocks from LLM responses and passes them
    to the memory manager for storage and resolution.
    """

    def __init__(
        self,
        db: Database,
        memory_manager: MemoryManager | None = None,
        cost_fetcher: Callable | None = None,
        corrections_manager: CorrectionsManager | None = None,
        tracer: Tracer | None = None,
        message_bus: MessageBus | None = None,
    ) -> None:
        self.db = db
        self.memory_manager = memory_manager
        self._cost_fetcher = cost_fetcher
        self.corrections_manager = corrections_manager
        self.tracer = tracer
        self.message_bus: MessageBus | None = message_bus
        self._extraction_provider = None  # Set by bootstrap
        self._extraction_model = ""       # Set by bootstrap

    async def reflect(
        self,
        conversation_id: str,
        response: LLMResponse,
        user_message: str | None = None,
        scrape_metadata: dict | None = None,
        message_id: str | None = None,
        channel: str = "web",
    ) -> str:
        content = response.content

        # Parse and strip correction block
        correction_match = CORRECTION_PATTERN.search(content) or CORRECTION_FALLBACK.search(content)
        if correction_match:
            try:
                correction_data = json.loads(correction_match.group(1))
                if self.corrections_manager:
                    await self.corrections_manager.store(
                        conversation_id=conversation_id,
                        original_response=correction_data["original"],
                        correction=correction_data["correction"],
                        context=correction_data.get("context", ""),
                        category=correction_data.get("category", "behavior"),
                    )
                    if self.tracer:
                        await self.tracer.emit("correction_detected", conversation_id, {
                            "category": correction_data.get("category", "behavior"),
                        })
            except (json.JSONDecodeError, KeyError):
                logger.warning("Failed to parse correction block from response")
            content = content[:correction_match.start()].rstrip()

        # Store the clean assistant message
        msg_id = message_id or uuid.uuid4().hex
        await self.message_bus.publish(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            channel=channel,
            model_used=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
            message_id=msg_id,
        )

        # Spawn async cost backfill if applicable
        if response.generation_id and self._cost_fetcher:
            asyncio.create_task(self._backfill_cost(msg_id, response.generation_id))

        # Extract entities/facts via dedicated LLM call
        extracted = {"entities": [], "facts": [], "relationships": []}
        if user_message and self._extraction_provider:
            try:
                from odigos.memory.extractor import extract_knowledge
                extracted = await extract_knowledge(
                    provider=self._extraction_provider,
                    user_message=user_message,
                    assistant_response=content,
                    model=self._extraction_model,
                )
            except Exception:
                logger.warning("Knowledge extraction failed", exc_info=True)

        # Pass to memory manager if available (best-effort)
        if self.memory_manager and user_message is not None:
            try:
                await self.memory_manager.store(
                    conversation_id=conversation_id,
                    user_message=user_message,
                    assistant_response=content,
                    extracted=extracted,
                )
            except Exception:
                logger.warning("Memory storage failed during reflection", exc_info=True)

        # Queue wiki writes for the heartbeat to process
        if self.db and any(extracted.values()):
            import uuid as _uuid
            for entity in extracted.get("entities", []):
                stored_id = entity.get("_stored_id")
                if stored_id:
                    await self.db.execute(
                        "INSERT INTO pending_wiki_writes (id, entity_id, operation) VALUES (?, ?, ?)",
                        (_uuid.uuid4().hex, stored_id, "entity_created"),
                    )
            for fact in extracted.get("facts", []):
                stored_id = fact.get("_stored_id")
                if stored_id:
                    await self.db.execute(
                        "INSERT INTO pending_wiki_writes (id, fact_id, operation) VALUES (?, ?, ?)",
                        (_uuid.uuid4().hex, stored_id, "fact_created"),
                    )

        # Log scrape if metadata provided (best-effort)
        if scrape_metadata:
            try:
                url = scrape_metadata.get("url", "")
                title = scrape_metadata.get("title", "")
                content_text = scrape_metadata.get("content", "")
                summary = content_text[:200] if content_text else ""
                await self.db.execute(
                    "INSERT INTO scraped_pages (id, url, title, summary) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), url, title, summary),
                )
            except Exception:
                logger.warning("Failed to log scrape metadata", exc_info=True)

        if self.tracer:
            await self.tracer.emit("reflection", conversation_id, {})

        return content

    async def _backfill_cost(self, message_id: str, generation_id: str) -> None:
        try:
            cost = await self._cost_fetcher(generation_id)
            if cost is not None:
                await self.db.execute(
                    "UPDATE messages SET cost_usd = ? WHERE id = ?",
                    (cost, message_id),
                )
                logger.debug("Updated cost for message %s: $%.6f", message_id, cost)
        except Exception:
            logger.debug("Cost backfill failed for %s", generation_id, exc_info=True)
