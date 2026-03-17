"""Entity graph and semantic memory search API endpoints."""

from fastapi import APIRouter, Depends, Query

from odigos.api.deps import get_db, get_vector_memory, require_auth
from odigos.db import Database
from odigos.memory.vectors import VectorMemory

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
    mode: str = Query(default="hybrid", pattern="^(hybrid|vector|fts)$"),
    vector_memory: VectorMemory = Depends(get_vector_memory),
):
    """Search over memory. Modes: hybrid (default), vector, fts."""
    if mode == "fts":
        results = await vector_memory.search_fts(q, limit=limit)
    elif mode == "vector":
        results = await vector_memory.search(q, limit=limit)
    else:
        # Hybrid: vector + FTS5 merged via RRF
        vector_results = await vector_memory.search(q, limit=limit * 3)
        fts_results = await vector_memory.search_fts(q, limit=limit * 3)

        scores: dict[str, float] = {}
        result_map = {}
        k = 60
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
        results = [result_map[key] for key, _ in ranked[:limit]]

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
