from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database

from odigos.core.content_filter import ContentFilter
from odigos.memory.chunking import ChunkingService
from odigos.memory.graph import EntityGraph
from odigos.memory.recall import MemoryRecall
from odigos.memory.resolver import EntityResolver
from odigos.memory.store import MemoryStore
from odigos.memory.summarizer import ConversationSummarizer

logger = logging.getLogger(__name__)

_recall_filter = ContentFilter()


def _clean_truncate(text: str, max_tokens: int) -> str:
    """Truncate at sentence boundary within token budget."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    for sep in ['. ', '.\n', '! ', '!\n', '? ', '?\n']:
        idx = truncated.rfind(sep)
        if idx > max_chars // 2:
            return truncated[:idx + 1].rstrip() + " [... truncated ...]"
    return truncated.rstrip() + " [... truncated ...]"


class MemoryManager:
    """Unified recall/store interface for the agent core."""

    def __init__(
        self,
        memory_store: MemoryStore,
        memory_recall: MemoryRecall,
        graph: EntityGraph,
        resolver: EntityResolver,
        summarizer: ConversationSummarizer,
        chunking_service: ChunkingService | None = None,
        cite_sources: bool = True,
        db: Database | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.memory_recall = memory_recall
        self.graph = graph
        self.resolver = resolver
        self.summarizer = summarizer
        self._cite_sources = cite_sources
        self.chunking = chunking_service or ChunkingService()
        self.db = db

    async def _bulk_fetch_full_text(self, source_ids: list[str]) -> dict[str, str]:
        """Fetch full text for multiple source IDs in one query."""
        if not source_ids or not self.db:
            return {}
        placeholders = ",".join("?" * len(source_ids))
        result: dict[str, str] = {}
        # Try document_text table first
        try:
            rows = await self.db.fetch_all(
                f"SELECT document_id, full_text FROM document_text "
                f"WHERE document_id IN ({placeholders})",
                tuple(source_ids),
            )
            for r in rows:
                result[r["document_id"]] = r["full_text"]
        except Exception:
            pass
        # Try messages table for conversation memories
        missing = [sid for sid in source_ids if sid not in result]
        if missing:
            try:
                placeholders2 = ",".join("?" * len(missing))
                rows = await self.db.fetch_all(
                    f"SELECT conversation_id, group_concat(content, '\n') as full "
                    f"FROM messages WHERE conversation_id IN ({placeholders2}) "
                    f"GROUP BY conversation_id",
                    tuple(missing),
                )
                for r in rows:
                    result[r["conversation_id"]] = r["full"]
            except Exception:
                pass
        return result

    async def recall(self, query: str, classification_type: str | None = None) -> str:
        """Recall relevant memories for the given query.

        Delegates search to MemoryRecall, then augments with entity graph traversal.
        Returns a formatted context string for injection into the prompt.
        """
        sections = []

        # 1. Structured memory search via MemoryRecall
        results = await self.memory_recall.search(
            query, classification_type=classification_type,
        )

        if results:
            formatted = self.memory_recall.format_grouped(results)
            if formatted:
                if self._cite_sources:
                    formatted = formatted.replace(
                        "## Recalled knowledge",
                        "## Recalled knowledge (cite sources where relevant)",
                        1,
                    )
                sections.append(formatted)

        # 2. Entity lookup with 2-hop graph traversal
        entity_lines = []
        words = [w for w in query.split() if len(w) > 2]
        seen_entities: set[str] = set()
        max_related = 8  # Cap total related entities to control token cost

        for word in words:
            entities = await self.graph.find_entity(word)
            for entity in entities:
                if entity["id"] in seen_entities:
                    continue
                seen_entities.add(entity["id"])

                line = f"- {entity['name']}: {entity['type']}"
                if entity.get("summary"):
                    line += f", {entity['summary']}"
                entity_lines.append(line)

                # 2-hop traversal with relationship paths
                related = await self.graph.traverse_with_paths(
                    entity["id"], depth=2,
                )
                related_count = 0
                for r in related:
                    if related_count >= max_related:
                        break
                    if r["id"] in seen_entities:
                        continue
                    seen_entities.add(r["id"])
                    related_count += 1
                    hop_prefix = "  " * r["hop"]
                    entity_lines.append(
                        f"{hop_prefix}-> {r['relationship']} -> "
                        f"{r['name']} ({r['type']})"
                    )

        if entity_lines:
            sections.append("## Known entities\n" + "\n".join(entity_lines))

        combined = "\n\n".join(sections)
        if combined:
            scan = _recall_filter.scan(combined)
            if scan.is_suspicious:
                logger.warning(
                    "Content filter flagged RAG recall: %s", scan.matched_patterns,
                )
            return scan.sanitized_text
        return combined

    async def store(
        self,
        conversation_id: str,
        user_message: str,
        assistant_response: str,
        extracted: dict | None = None,
    ) -> None:
        """Process and store memories from a conversation turn.

        Best-effort: failures are logged but don't crash the agent.
        """
        try:
            await self._store_impl(conversation_id, user_message, assistant_response, extracted)
        except Exception:
            logger.warning("Memory storage failed, skipping this turn", exc_info=True)

    async def _store_impl(
        self,
        conversation_id: str,
        user_message: str,
        assistant_response: str,
        extracted: dict | None = None,
    ) -> None:
        extracted = extracted or {"entities": [], "facts": [], "relationships": []}

        # 1. Store entities with provenance
        for entity_data in extracted["entities"]:
            try:
                entity_id = await self.resolver.resolve(
                    entity_data["name"],
                    entity_data.get("type", "concept"),
                    context=user_message,
                    source_type="conversation",
                    source_id=conversation_id,
                )
                entity_data["_stored_id"] = (
                    entity_id.entity_id if hasattr(entity_id, 'entity_id') else str(entity_id)
                )
            except Exception:
                logger.debug("Entity storage failed for %s", entity_data.get("name"))

        # 2. Store relationships
        for rel in extracted["relationships"]:
            try:
                from_entities = await self.graph.find_entity(rel["from"])
                to_entities = await self.graph.find_entity(rel["to"])
                if from_entities and to_entities:
                    await self.graph.create_edge(
                        from_entities[0]["id"], rel["relationship"], to_entities[0]["id"],
                        source_type="conversation", edge_source_id=conversation_id,
                    )
            except Exception:
                logger.debug(
                    "Relationship storage failed: %s -> %s",
                    rel.get("from"), rel.get("to"),
                )

        # 3. Store facts via MemoryStore (classifier determines fact/preference type)
        for fact_data in extracted["facts"]:
            try:
                fact_text = fact_data["text"]
                record = await self.memory_store.store(
                    content=fact_text,
                    source_type="extraction",
                    source_id=conversation_id,
                    conversation_id=conversation_id,
                )
                if record:
                    fact_data["_stored_id"] = record.id
            except Exception:
                logger.debug("Fact storage failed: %s", fact_data.get("text", "")[:50])

        # 4. Chunk and embed the user message via MemoryStore
        chunks = self.chunking.chunk(user_message, content_type="message")
        for chunk in chunks:
            try:
                await self.memory_store.store(
                    content=chunk,
                    source_type="user_message",
                    source_id=conversation_id,
                    conversation_id=conversation_id,
                )
            except Exception:
                logger.debug("Chunk store failed for conversation %s", conversation_id)

        # 5. Check if summarization is needed
        await self.summarizer.summarize_if_needed(conversation_id)
