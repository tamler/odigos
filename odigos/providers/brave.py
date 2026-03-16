from __future__ import annotations

import logging

import httpx

from odigos.providers.search_base import SearchResult

logger = logging.getLogger(__name__)


class BraveSearchProvider:
    """Brave Search API client."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
        )

    async def search(
        self,
        query: str,
        num_results: int = 5,
    ) -> list[SearchResult]:
        """Search Brave and return top results.

        Returns an empty list on any error (network, HTTP, parse).
        """
        try:
            response = await self._client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": num_results},
            )

            if response.status_code != 200:
                logger.warning(
                    "Brave Search returned status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return []

            data = response.json()
            web = data.get("web", {})
            results = []
            for item in web.get("results", [])[:num_results]:
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("description", ""),
                    )
                )
            return results

        except Exception:
            logger.exception("Brave search failed for query: %s", query)
            return []

    async def close(self) -> None:
        await self._client.aclose()
