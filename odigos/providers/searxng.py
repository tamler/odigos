from __future__ import annotations

import logging

import httpx

from odigos.providers.search_base import SearchResult

logger = logging.getLogger(__name__)

SEARXNG_DEFAULT_CATEGORIES = "general"


class SearxngProvider:
    """SearXNG search API client with basic auth."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
    ) -> None:
        self.url = url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            auth=httpx.BasicAuth(username, password),
        )

    async def search(
        self,
        query: str,
        num_results: int = 5,
        categories: str = SEARXNG_DEFAULT_CATEGORIES,
    ) -> list[SearchResult]:
        """Search SearXNG and return top results.

        Returns an empty list on any error (network, HTTP, parse).
        """
        try:
            response = await self._client.get(
                f"{self.url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": categories,
                },
            )

            if response.status_code != 200:
                logger.warning(
                    "SearXNG returned status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return []

            data = response.json()
            results = []
            for item in data.get("results", [])[:num_results]:
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content", ""),
                    )
                )
            return results

        except Exception:
            logger.exception("SearXNG search failed for query: %s", query)
            return []

    async def close(self) -> None:
        await self._client.aclose()
