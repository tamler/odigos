from __future__ import annotations

import logging
from dataclasses import dataclass

from odigos.db import Database
from odigos.memory.graph import EntityGraph

logger = logging.getLogger(__name__)

@dataclass
class ResolutionResult:
    entity_id: str
    action: str  # "matched", "created", "created_low_confidence"
    confidence: float


class EntityResolver:
    """Multi-stage entity resolution pipeline.

    Stages: exact match -> fuzzy match -> memory LIKE match -> create new.
    LLM tiebreaker is deferred until an LLM provider is available for cheap calls.
    """

    def __init__(
        self,
        graph: EntityGraph,
        vector_memory=None,
        llm_provider=None,
        memory_store=None,
    ) -> None:
        self.graph = graph
        # vector_memory kept for backward compat but unused (references dropped table)
        self.llm_provider = llm_provider
        self._memory_store = memory_store

    async def resolve(
        self, name: str, entity_type: str, context: str,
        source_type: str | None = None, source_id: str | None = None,
    ) -> ResolutionResult:
        """Resolve a candidate entity against the existing graph."""

        # Stage 1: Exact match
        exact = await self.graph.find_entity(name)
        exact_typed = [e for e in exact if e["type"] == entity_type]
        if len(exact_typed) == 1:
            return ResolutionResult(
                entity_id=exact_typed[0]["id"],
                action="matched",
                confidence=1.0,
            )

        # Stage 2: Fuzzy match (LIKE with type filter)
        fuzzy = await self.graph.db.fetch_all(
            "SELECT * FROM entities WHERE name LIKE ? AND type = ? AND status = 'active'",
            (f"%{name}%", entity_type),
        )
        if len(fuzzy) == 1:
            return ResolutionResult(
                entity_id=fuzzy[0]["id"],
                action="matched",
                confidence=0.85,
            )

        # Stage 3: Memory LIKE match against the memories table
        rows = await self.graph.db.fetch_all(
            "SELECT m.source_id, m.content FROM memories m "
            "WHERE m.memory_type = 'entity' AND m.status = 'active' "
            "AND (m.content LIKE ? OR m.context_description LIKE ?) "
            "LIMIT 5",
            (f"%{name}%", f"%{name}%"),
        )
        for row in rows:
            entity = await self.graph.get_entity(row["source_id"])
            if entity and entity["type"] == entity_type:
                return ResolutionResult(
                    entity_id=entity["id"],
                    action="matched",
                    confidence=0.7,
                )

        # Stage 4: No match -- create new entity
        entity_id = await self.graph.create_entity(
            entity_type=entity_type, name=name, source="extraction",
            source_type=source_type, source_id=source_id,
        )

        # Store the entity name in MemoryStore for future matching
        if self._memory_store:
            from odigos.memory.classifier import ClassificationResult
            classification = ClassificationResult(
                memory_type="entity",
                keywords=[name, entity_type],
                tags=["entity"],
                context_description=f"{entity_type}: {name}",
            )
            try:
                await self._memory_store.store(
                    content=f"{entity_type}: {name}",
                    source_type="entity",
                    source_id=entity_id,
                    classification=classification,
                )
            except Exception:
                logger.debug("Failed to store entity memory for %s", name)

        return ResolutionResult(
            entity_id=entity_id,
            action="created",
            confidence=1.0,
        )
