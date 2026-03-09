from __future__ import annotations

import asyncio
import logging
from functools import partial

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_DIMENSIONS = 768


class EmbeddingProvider:
    """Local embedding model via sentence-transformers (ONNX backend)."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
    ) -> None:
        self.dimensions = dimensions
        logger.info("Loading embedding model: %s (%d-d)", model_name, dimensions)
        self._model = SentenceTransformer(
            model_name,
            backend="onnx",
            model_kwargs={"file_name": "onnx/model_quantized.onnx"},
            truncate_dim=dimensions,
        )
        logger.info("Embedding model loaded")

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns a vector."""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts. Returns a list of vectors."""
        # nomic-embed-text-v1.5 requires task-prefixed input
        prefixed = [f"search_document: {t}" for t in texts]
        loop = asyncio.get_running_loop()
        embeddings = await loop.run_in_executor(
            None,
            partial(self._model.encode, prefixed, normalize_embeddings=True),
        )
        return [e.tolist() for e in embeddings]

    async def embed_query(self, query: str) -> list[float]:
        """Embed a search query (uses search_query prefix)."""
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(
            None,
            partial(
                self._model.encode,
                [f"search_query: {query}"],
                normalize_embeddings=True,
            ),
        )
        return embedding[0].tolist()

    async def close(self) -> None:
        pass
