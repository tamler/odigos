"""Entity graph and semantic memory search API endpoints."""

from fastapi import APIRouter, Depends, Query

from odigos.api.deps import get_db, get_vector_memory, require_api_key
from odigos.db import Database
from odigos.memory.vectors import VectorMemory

router = APIRouter(
    prefix="/api/memory",
    dependencies=[Depends(require_api_key)],
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
    vector_memory: VectorMemory = Depends(get_vector_memory),
):
    """Semantic search over vector memory."""
    results = await vector_memory.search(q, limit=limit)
    return {
        "results": [
            {
                "content_preview": r.content_preview,
                "source_type": r.source_type,
                "source_id": r.source_id,
                "distance": r.distance,
            }
            for r in results
        ]
    }
