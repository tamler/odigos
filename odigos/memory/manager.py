from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sentence_transformers import CrossEncoder

if TYPE_CHECKING:
    from odigos.db import Database

from odigos.core.content_filter import ContentFilter
from odigos.memory.chunking import ChunkingService
from odigos.memory.graph import EntityGraph
from odigos.memory.resolver import EntityResolver
from odigos.memory.summarizer import ConversationSummarizer
from odigos.memory.vectors import VectorMemory

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

_reranker: CrossEncoder | None = None


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    return _reranker


class MemoryManager:
    """Unified recall/store interface for the agent core."""

    def __init__(
        self,
        vector_memory: VectorMemory,
        graph: EntityGraph,
        resolver: EntityResolver,
        summarizer: ConversationSummarizer,
        chunking_service: ChunkingService | None = None,
        cite_sources: bool = True,
        db: Database | None = None,
    ) -> None:
        self.vector_memory = vector_memory
        self.graph = graph
        self.resolver = resolver
        self.summarizer = summarizer
        self._cite_sources = cite_sources
        self.chunking = chunking_service or ChunkingService()
        self.db = db

    async def _hybrid_search(
        self, query: str, limit: int = 5, k: int = 60,
        source_type: str | None = None, strategy: str = "rrf",
    ) -> list:
        """Run vector + FTS5 search and merge via Reciprocal Rank Fusion."""
        from odigos.memory.vectors import MemoryResult

        fetch_limit = limit * 4
        vector_results = await self.vector_memory.search(
            query, limit=fetch_limit, source_type=source_type,
        )
        fts_results = await self.vector_memory.search_fts(
            query, limit=fetch_limit, source_type=source_type,
        )

        if strategy == "union":
            # Set union: combine both lists, deduplicate by key
            all_results: dict[str, MemoryResult] = {}
            for r in vector_results:
                key = f"{r.source_type}:{r.source_id}:{r.content_preview[:100]}"
                all_results[key] = r
            for r in fts_results:
                key = f"{r.source_type}:{r.source_id}:{r.content_preview[:100]}"
                if key not in all_results:
                    all_results[key] = r
            ranked_results = list(all_results.values())[:limit]
        else:
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

            # After RRF ranking, rerank top candidates with cross-encoder
            if len(ranked) > limit:
                try:
                    reranker = _get_reranker()
                    candidates = [
                        (query, result_map[key].content_preview)
                        for key, _ in ranked[:limit * 3]
                    ]
                    scores_ce = reranker.predict(candidates)
                    sorted_pairs = sorted(
                        zip(scores_ce, [result_map[key] for key, _ in ranked[:limit * 3]]),
                        key=lambda x: x[0],
                        reverse=True,
                    )
                    # Store cross-encoder scores on results
                    for score, result in sorted_pairs:
                        result.cross_encoder_score = score
                    ranked_results = [result for _, result in sorted_pairs[:limit]]
                except Exception:
                    # Fall back to RRF ranking if reranker fails
                    ranked_results = [result_map[key] for key, _score in ranked[:limit]]
            else:
                ranked_results = [result_map[key] for key, _score in ranked[:limit]]

        return ranked_results

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

    def _format_result_line(self, result, is_doc: bool = False) -> str:
        """Format a single result, using expanded_content if available."""
        content = getattr(result, 'expanded_content', None) or result.content_preview
        if is_doc:
            source_hint = ""
            if result.when_to_use and "from '" in result.when_to_use:
                source_hint = result.when_to_use.split("from '")[1].split("'")[0]
            citation = f"[{source_hint}]" if source_hint else f"[doc:{result.source_id[:8]}]"
            return f"- {citation} {content}"
        return f"- {content}"

    async def recall(self, query: str, limit: int = 5, token_budget: int = 2000) -> str:
        """Recall relevant memories for the given query.

        Searches documents and conversations separately to prevent chat
        messages from drowning out document knowledge.
        Returns a formatted context string for injection into the prompt.

        High-relevance results (cross-encoder score > threshold) get full
        content loaded from DB within the token budget; low-relevance results
        stay as 500-char summaries.
        """
        EXPANSION_THRESHOLD = 0.4
        MAX_EXPANSIONS = 3

        sections = []

        # 1. Document knowledge (from uploaded/ingested files)
        doc_results = await self._hybrid_search(
            query, limit=max(limit, 10), source_type="document_chunk",
        )

        # Split document results into tiers
        doc_tier2 = []
        doc_tier1 = []
        for r in doc_results:
            score = getattr(r, 'cross_encoder_score', 0)
            if score > EXPANSION_THRESHOLD and len(doc_tier2) < MAX_EXPANSIONS:
                doc_tier2.append(r)
            else:
                doc_tier1.append(r)

        # 2. Conversation memory (from past user messages)
        conv_results = await self._hybrid_search(
            query, limit=limit, source_type="user_message",
        )

        # Split conversation results into tiers
        conv_tier2 = []
        conv_tier1 = []
        for r in conv_results:
            score = getattr(r, 'cross_encoder_score', 0)
            if score > EXPANSION_THRESHOLD and len(conv_tier2) < MAX_EXPANSIONS:
                conv_tier2.append(r)
            else:
                conv_tier1.append(r)

        # Load full content for all Tier 2 results
        all_tier2 = doc_tier2 + conv_tier2
        if all_tier2:
            tier2_budget = token_budget // 2
            source_ids = [r.source_id for r in all_tier2]
            full_texts = await self._bulk_fetch_full_text(source_ids)
            per_item_budget = tier2_budget // max(len(all_tier2), 1)
            for r in all_tier2:
                full = full_texts.get(r.source_id)
                if full:
                    r.expanded_content = _clean_truncate(full, per_item_budget)

        # Format document results
        doc_lines = []
        for result in doc_tier2 + doc_tier1:
            doc_lines.append(self._format_result_line(result, is_doc=True))

        if doc_lines:
            header = (
                "## Document knowledge (cite sources in your response)"
                if self._cite_sources
                else "## Document knowledge"
            )
            sections.append(header + "\n" + "\n".join(doc_lines))

        # Format conversation results
        conv_lines = []
        for result in conv_tier2 + conv_tier1:
            conv_lines.append(self._format_result_line(result, is_doc=False))

        if conv_lines:
            sections.append("## Conversation history\n" + "\n".join(conv_lines))

        # 3. Entity lookup with 2-hop graph traversal
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
                entity_data["_stored_id"] = entity_id.entity_id if hasattr(entity_id, 'entity_id') else str(entity_id)
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

        # 3. Store facts with SHA-256 dedup
        import hashlib
        for fact_data in extracted["facts"]:
            try:
                fact_text = fact_data["text"]
                fact_hash = hashlib.sha256(
                    fact_text.strip().lower().encode(),
                ).hexdigest()[:16]
                if self.db:
                    existing = await self.db.fetch_one(
                        "SELECT id FROM user_facts WHERE content_hash = ?",
                        (fact_hash,),
                    )
                    if existing:
                        continue  # Exact duplicate, skip
                    import uuid
                    fact_id = uuid.uuid4().hex
                    await self.db.execute(
                        "INSERT INTO user_facts (id, fact, category, source, source_type,"
                        " source_id, content_hash, confidence, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                        (
                            fact_id, fact_text, fact_data.get("category", "general"),
                            "extracted", "conversation", conversation_id, fact_hash, 0.8,
                        ),
                    )
                    fact_data["_stored_id"] = fact_id
            except Exception:
                logger.debug("Fact storage failed: %s", fact_data.get("text", "")[:50])

        # 4. Chunk and embed the user message (with dedup)
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
