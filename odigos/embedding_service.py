"""Standalone embedding service -- one process serves all agents.

Run: python -m odigos.embedding_service
Listens on port 9000 by default. Agents connect via RemoteEmbeddingProvider.

Saves ~500MB RAM per agent by sharing one model instance.
"""
from __future__ import annotations

import logging
from functools import partial

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, CrossEncoder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Odigos Embedding Service")

# Load models once at startup
_embed_model: SentenceTransformer | None = None
_cross_encoder: CrossEncoder | None = None


class EmbedRequest(BaseModel):
    texts: list[str]
    type: str = "document"  # "document" or "query"


class RerankRequest(BaseModel):
    query: str
    passages: list[str]
    top_k: int = 5


@app.on_event("startup")
async def load_models():
    global _embed_model, _cross_encoder
    logger.info("Loading embedding model...")
    _embed_model = SentenceTransformer(
        "nomic-ai/nomic-embed-text-v1.5",
        truncate_dim=768,
        trust_remote_code=True,
    )
    logger.info("Embedding model loaded")

    logger.info("Loading cross-encoder...")
    _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    logger.info("Cross-encoder loaded")


@app.post("/embed")
async def embed(request: EmbedRequest):
    if not _embed_model:
        return {"error": "Model not loaded"}, 503

    prefix = "search_query: " if request.type == "query" else "search_document: "
    prefixed = [f"{prefix}{t}" for t in request.texts]

    import asyncio
    loop = asyncio.get_running_loop()
    embeddings = await loop.run_in_executor(
        None,
        partial(_embed_model.encode, prefixed, normalize_embeddings=True),
    )
    return {"embeddings": [e.tolist() for e in embeddings]}


@app.post("/rerank")
async def rerank(request: RerankRequest):
    if not _cross_encoder:
        return {"error": "Model not loaded"}, 503

    import asyncio
    loop = asyncio.get_running_loop()
    pairs = [[request.query, p] for p in request.passages]
    scores = await loop.run_in_executor(
        None,
        partial(_cross_encoder.predict, pairs),
    )
    scored = sorted(
        zip(range(len(request.passages)), scores.tolist()),
        key=lambda x: x[1],
        reverse=True,
    )[:request.top_k]
    return {"results": [{"index": i, "score": s} for i, s in scored]}


@app.get("/health")
async def health():
    return {"status": "ok", "models": {
        "embedding": _embed_model is not None,
        "cross_encoder": _cross_encoder is not None,
    }}


def main():
    import uvicorn
    uvicorn.run(
        "odigos.embedding_service:app",
        host="127.0.0.1",
        port=9000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
