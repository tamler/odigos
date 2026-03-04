import logging
from dataclasses import dataclass

from odigos.memory.graph import EntityGraph
from odigos.memory.vectors import VectorMemory

logger = logging.getLogger(__name__)

CONFIDENCE_HIGH = 0.8
CONFIDENCE_LOW = 0.3


@dataclass
class ResolutionResult:
    entity_id: str
    action: str  # "matched", "created", "created_low_confidence"
    confidence: float


class EntityResolver:
    """Multi-stage entity resolution pipeline.

    Stages: exact match -> fuzzy match -> alias match -> vector match -> create new.
    LLM tiebreaker is deferred until an LLM provider is available for cheap calls.
    """

    def __init__(
        self,
        graph: EntityGraph,
        vector_memory: VectorMemory,
        llm_provider=None,
    ) -> None:
        self.graph = graph
        self.vector_memory = vector_memory
        self.llm_provider = llm_provider

    async def resolve(
        self, name: str, entity_type: str, context: str
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

        # Stage 3: Alias match (already covered in find_entity, but check
        # across all types if exact_typed was empty)
        if exact and not exact_typed:
            # Found by name/alias but different type -- treat as no match
            pass

        # Stage 4: Vector match
        vector_results = await self.vector_memory.search(
            f"{entity_type}: {name}", limit=3
        )
        for vr in vector_results:
            if vr.source_type == "entity_name" and vr.distance < 0.3:
                entity = await self.graph.get_entity(vr.source_id)
                if entity and entity["type"] == entity_type:
                    return ResolutionResult(
                        entity_id=entity["id"],
                        action="matched",
                        confidence=0.7,
                    )

        # Stage 5: No match -- create new entity
        entity_id = await self.graph.create_entity(
            entity_type=entity_type, name=name, source="extraction"
        )

        # Embed the entity name for future vector matching
        await self.vector_memory.store(
            text=f"{entity_type}: {name}",
            source_type="entity_name",
            source_id=entity_id,
        )

        return ResolutionResult(
            entity_id=entity_id,
            action="created",
            confidence=1.0,
        )
