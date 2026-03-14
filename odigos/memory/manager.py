from __future__ import annotations

import logging

from odigos.memory.chunking import ChunkingService
from odigos.memory.graph import EntityGraph
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.vectors import VectorMemory

logger = logging.getLogger(__name__)


class MemoryManager:
    """Unified recall/store interface for the agent core."""

    def __init__(
        self,
        vector_memory: VectorMemory,
        graph: EntityGraph,
        resolver: EntityResolver,
        summarizer: ConversationSummarizer,
        chunking_service: ChunkingService | None = None,
    ) -> None:
        self.vector_memory = vector_memory
        self.graph = graph
        self.resolver = resolver
        self.summarizer = summarizer
        self.chunking = chunking_service or ChunkingService()

    async def _hybrid_search(
        self, query: str, limit: int = 5, k: int = 60
    ) -> list:
        """Run vector + FTS5 search and merge via Reciprocal Rank Fusion."""
        from odigos.memory.vectors import MemoryResult

        fetch_limit = limit * 4
        vector_results = await self.vector_memory.search(query, limit=fetch_limit)
        fts_results = await self.vector_memory.search_fts(query, limit=fetch_limit)

        # RRF: score = sum(1 / (k + rank)) across both result lists
        scores: dict[str, float] = {}
        result_map: dict[str, MemoryResult] = {}

        for rank, r in enumerate(vector_results):
            key = f"{r.source_type}:{r.source_id}:{r.content_preview[:100]}"
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
            result_map[key] = r

        for rank, r in enumerate(fts_results):
            key = f"{r.source_type}:{r.source_id}:{r.content_preview[:100]}"
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
            if key not in result_map:
                result_map[key] = r

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [result_map[key] for key, _score in ranked[:limit]]

    async def recall(self, query: str, limit: int = 5) -> str:
        """Recall relevant memories for the given query.

        Returns a formatted context string for injection into the prompt.
        """
        sections = []

        # 1. Hybrid search (vector + FTS5 with RRF)
        hybrid_results = await self._hybrid_search(query, limit=limit)
        memory_lines = []
        for result in hybrid_results:
            if result.source_type == "document_chunk" and result.when_to_use:
                source_hint = ""
                if "from '" in result.when_to_use:
                    source_hint = result.when_to_use.split("from '")[1].split("'")[0]
                if source_hint:
                    memory_lines.append(f"- [Source: {source_hint}] {result.content_preview}")
                else:
                    memory_lines.append(f"- {result.content_preview}")
            elif result.source_type != "entity_name":
                memory_lines.append(f"- {result.content_preview}")

        if memory_lines:
            sections.append("## Relevant memories\n" + "\n".join(memory_lines))

        # 2. Entity lookup
        entity_lines = []
        words = [w for w in query.split() if len(w) > 2]
        seen_entities = set()
        for word in words:
            entities = await self.graph.find_entity(word)
            for entity in entities:
                if entity["id"] not in seen_entities:
                    seen_entities.add(entity["id"])
                    related = await self.graph.get_related(entity["id"])
                    related_names = [r["name"] for r in related[:3]]
                    line = f"- {entity['name']}: {entity['type']}"
                    if entity.get("summary"):
                        line += f", {entity['summary']}"
                    if related_names:
                        line += f" (related: {', '.join(related_names)})"
                    entity_lines.append(line)

        if entity_lines:
            sections.append("## Known entities\n" + "\n".join(entity_lines))

        return "\n\n".join(sections)

    async def store(
        self,
        conversation_id: str,
        user_message: str,
        assistant_response: str,
        extracted_entities: list[dict],
    ) -> None:
        """Process and store memories from a conversation turn.

        Best-effort: failures are logged but don't crash the agent.
        """
        try:
            await self._store_impl(conversation_id, user_message, assistant_response, extracted_entities)
        except Exception:
            logger.warning("Memory storage failed, skipping this turn", exc_info=True)

    @staticmethod
    def _generate_when_to_use(text: str, source_type: str) -> str:
        """Generate a when_to_use description from content heuristics."""
        text_lower = text.lower()
        if source_type == "user_message":
            if any(w in text_lower for w in ("prefer", "like", "want", "always", "never")):
                return f"when recalling user preferences about: {text[:100]}"
            if any(w in text_lower for w in ("is a", "works at", "lives in", "born")):
                return f"when recalling facts about people or places mentioned in: {text[:100]}"
            return f"when the user previously discussed: {text[:100]}"
        if source_type == "document_chunk":
            return f"when referencing ingested documents about: {text[:100]}"
        return ""

    async def _is_duplicate(self, text: str, threshold: float = 0.15, search_text: str | None = None) -> bool:
        """Check if a near-duplicate memory already exists."""
        query = search_text if search_text else text
        results = await self.vector_memory.search(query, limit=1)
        if results and results[0].distance < threshold:
            return True
        return False

    async def _store_impl(
        self,
        conversation_id: str,
        user_message: str,
        assistant_response: str,
        extracted_entities: list[dict],
    ) -> None:
        # 1. Resolve and store entities
        for entity_data in extracted_entities:
            result = await self.resolver.resolve(
                name=entity_data["name"],
                entity_type=entity_data.get("type", "concept"),
                context=user_message,
            )

            # If entity has a relationship, create an edge
            if entity_data.get("relationship") and entity_data.get("detail"):
                detail = entity_data["detail"]
                target_result = await self.resolver.resolve(
                    name=detail,
                    entity_type="concept",
                    context=user_message,
                )
                await self.graph.create_edge(
                    source_id=result.entity_id,
                    relationship=entity_data["relationship"],
                    target_id=target_result.entity_id,
                )

        # 2. Chunk and embed the user message (with dedup)
        chunks = self.chunking.chunk(user_message, content_type="message")
        for chunk in chunks:
            when_to_use = self._generate_when_to_use(chunk, "user_message")
            if not await self._is_duplicate(chunk, search_text=when_to_use or None):
                await self.vector_memory.store(
                    text=chunk,
                    source_type="user_message",
                    source_id=conversation_id,
                    memory_type="personal",
                    when_to_use=when_to_use,
                )

        # 3. Check if summarization is needed
        await self.summarizer.summarize_if_needed(conversation_id)
