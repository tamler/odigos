from __future__ import annotations

import logging

import httpx

from odigos.providers.search_base import SearchResult

logger = logging.getLogger(__name__)


class GoogleSearchProvider:
    """Google Custom Search API client."""

    def __init__(self, api_key: str, cx: str) -> None:
        self.api_key = api_key
        self.cx = cx
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    async def search(
        self,
        query: str,
        num_results: int = 5,
    ) -> list[SearchResult]:
        """Search Google Custom Search and return top results.

        Returns an empty list on any error (network, HTTP, parse).
        """
        try:
            response = await self._client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "q": query,
                    "key": self.api_key,
                    "cx": self.cx,
                    "num": num_results,
                },
            )

            if response.status_code != 200:
                logger.warning(
                    "Google Custom Search returned status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return []

            data = response.json()
            results = []
            for item in data.get("items", [])[:num_results]:
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("link", ""),
                        snippet=item.get("snippet", ""),
                    )
                )
            return results

        except Exception:
            logger.exception("Google Custom Search failed for query: %s", query)
            return []

    async def close(self) -> None:
        await self._client.aclose()
