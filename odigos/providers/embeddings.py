import logging

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
DEFAULT_MODEL = "openai/text-embedding-3-small"


class EmbeddingProvider:
    """OpenRouter embedding API wrapper (1536-d vectors)."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns a 1536-d vector."""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts. Returns a list of 1536-d vectors."""
        payload = {
            "model": self.model,
            "input": texts,
        }

        response = await self._client.post(OPENROUTER_EMBEDDINGS_URL, json=payload)

        if response.status_code != 200:
            raise RuntimeError(
                f"Embedding API error {response.status_code}: {response.text}"
            )

        data = response.json()
        return [item["embedding"] for item in data["data"]]

    async def close(self) -> None:
        await self._client.aclose()
