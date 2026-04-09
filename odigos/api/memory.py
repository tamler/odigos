"""Entity graph and semantic memory search API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from odigos.api.deps import get_db, get_container, require_auth
from odigos.db import Database

router = APIRouter(
    prefix="/api/memory",
    dependencies=[Depends(require_auth)],
)


@router.get("/entities")
async def get_entities(db: Database = Depends(get_db)):
    """Return all active entities and all edges."""
    entities = await db.fetch_all(
        "SELECT * FROM entities WHERE status = 'active'"
    )
    edges = await db.fetch_all("SELECT * FROM edges")
    return {"entities": entities, "edges": edges}


@router.get("/search")
async def search_memory(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    container=Depends(get_container),
):
    """Search over memory using MemoryRecall (hybrid vector + FTS)."""
    memory_manager = container.memory_manager
    if memory_manager is None:
        return {"results": []}

    results = await memory_manager.memory_recall.search(q, limit=limit)

    return {
        "results": [
            {
                "content": r.content,
                "memory_type": r.memory_type,
                "context_description": r.context_description,
                "confidence": r.confidence,
                "distance": r.distance,
                "source": r.source,
            }
            for r in results
        ]
    }
