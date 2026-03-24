"""Remote embedding provider -- calls a shared embedding service via HTTP.

Used in multi-agent deployments where a single embedding model serves
many agents, dramatically reducing per-agent memory usage (~500MB → ~0).
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_DIMENSIONS = 768


class RemoteEmbeddingProvider:
    """Embedding provider that delegates to a shared HTTP service."""

    def __init__(
        self,
        remote_url: str = "http://localhost:9000",
        dimensions: int = DEFAULT_DIMENSIONS,
        timeout: float = 30.0,
    ) -> None:
        self.dimensions = dimensions
        self._url = remote_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)
        logger.info("Remote embedding provider: %s (%d-d)", self._url, dimensions)

    async def embed(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.post(
            f"{self._url}/embed",
            json={"texts": texts, "type": "document"},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]

    async def embed_query(self, query: str) -> list[float]:
        resp = await self._client.post(
            f"{self._url}/embed",
            json={"texts": [query], "type": "query"},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]

    async def close(self) -> None:
        await self._client.aclose()
