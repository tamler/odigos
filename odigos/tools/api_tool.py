"""Base class for tools that call external HTTP APIs."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import httpx

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ToolAPIError(Exception):
    """Raised when an external API returns an error."""

    def __init__(self, status_code: int, message: str, failure_category: str = "unknown"):
        self.status_code = status_code
        self.message = message
        self.failure_category = failure_category
        super().__init__(message)


class APITool(BaseTool):
    """Base class for tools that call external HTTP APIs."""

    API_DOCS: str = ""

    def __init__(self, http: httpx.AsyncClient, **kwargs):
        self._http = http

    @property
    def http(self) -> httpx.AsyncClient:
        return self._http

    async def api_post(self, url: str, payload: dict, api_key: str, **kwargs) -> dict:
        """POST JSON with Bearer auth. Raises ToolAPIError on HTTP 4xx/5xx."""
        resp = await self.http.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            **kwargs,
        )
        data = resp.json()
        if resp.status_code >= 400:
            msg = data.get("msg") or data.get("error", "Unknown error")
            raise ToolAPIError(resp.status_code, msg)
        return data

    async def api_get(self, url: str, api_key: str, params: dict | None = None, **kwargs) -> dict:
        """GET with Bearer auth. Raises ToolAPIError on HTTP 4xx/5xx."""
        resp = await self.http.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            params=params,
            **kwargs,
        )
        data = resp.json()
        if resp.status_code >= 400:
            msg = data.get("msg") or data.get("error", "Unknown error")
            raise ToolAPIError(resp.status_code, msg)
        return data

    async def poll_until(
        self,
        url: str,
        api_key: str,
        params: dict,
        success_check: Callable[[dict], bool],
        failure_check: Callable[[dict], bool],
        extract: Callable[[dict], Any],
        max_seconds: float = 180,
        initial_delay: float = 5.0,
        max_delay: float = 15.0,
    ) -> Any:
        """Poll an API endpoint with exponential backoff."""
        delay = initial_delay
        elapsed = 0.0
        while elapsed < max_seconds:
            await asyncio.sleep(delay)
            elapsed += delay
            data = await self.api_get(url, api_key, params)
            if success_check(data):
                return extract(data)
            if failure_check(data):
                raise ToolAPIError(0, f"Task failed: {data}")
            delay = min(delay * 1.5, max_delay)
        raise ToolAPIError(0, "Polling timed out")
