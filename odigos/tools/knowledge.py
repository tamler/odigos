"""Knowledge lookup tool using Grokipedia and Wikipedia."""
from __future__ import annotations

import asyncio
import logging

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def _search_grokipedia(query: str) -> dict | None:
    """Search Grokipedia and return page info or None."""
    try:
        from grokipedia_api import GrokipediaClient
        from grokipedia_api.exceptions import (
            GrokipediaError,
            GrokipediaNotFoundError,
        )
    except ImportError:
        logger.debug("grokipedia-api not installed")
        return None

    try:
        client = GrokipediaClient()
        results = client.search_pages(query, limit=3)
        if not results:
            return None

        top = results[0]
        title = top.get("title", query)
        snippet = top.get("snippet", "")
        slug = top.get("slug", "")

        # Try to get full page content for richer data
        content = snippet
        if slug:
            try:
                page = client.get_page(slug)
                if page and page.content:
                    content = page.content[:1000]
            except (GrokipediaNotFoundError, GrokipediaError):
                pass
            except Exception:
                pass

        return {
            "title": title,
            "content": content,
            "source": "Grokipedia",
        }
    except Exception as exc:
        logger.debug("Grokipedia search failed: %s", exc)
        return None


def _search_wikipedia(query: str) -> dict | None:
    """Search Wikipedia and return page info or None."""
    try:
        import wikipedia
    except ImportError:
        logger.debug("wikipedia not installed")
        return None

    try:
        results = wikipedia.search(query, results=3)
        if not results:
            return None

        try:
            page = wikipedia.page(results[0], auto_suggest=False)
        except wikipedia.exceptions.DisambiguationError as e:
            if e.options:
                page = wikipedia.page(
                    e.options[0], auto_suggest=False
                )
            else:
                return None
        except wikipedia.exceptions.PageError:
            return None

        content = page.summary or ""
        return {
            "title": page.title,
            "content": content[:1000],
            "source": "Wikipedia",
        }
    except Exception as exc:
        logger.debug("Wikipedia search failed: %s", exc)
        return None


class LookupTool(BaseTool):
    name = "lookup"
    description = (
        "Look up factual information about a topic. Searches "
        "Grokipedia first (comprehensive knowledge base), falls "
        "back to Wikipedia. Use this before answering factual "
        "questions to get accurate, sourced information."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The topic to look up",
            },
            "source": {
                "type": "string",
                "description": (
                    "Knowledge source: 'auto' (try Grokipedia "
                    "then Wikipedia), 'grokipedia', or "
                    "'wikipedia'. Default: 'auto'"
                ),
                "enum": ["auto", "grokipedia", "wikipedia"],
            },
        },
        "required": ["query"],
    }

    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query", "").strip()
        if not query:
            return ToolResult(
                success=False,
                data="",
                error="No query provided",
            )

        source = params.get("source", "auto").strip() or "auto"

        result = None

        if source in ("auto", "grokipedia"):
            result = await asyncio.to_thread(
                _search_grokipedia, query
            )

        if result is None and source in ("auto", "wikipedia"):
            result = await asyncio.to_thread(
                _search_wikipedia, query
            )

        if result is None:
            return ToolResult(
                success=False,
                data="",
                error=f"No results found for: {query}",
            )

        output = (
            f"Source: {result['source']}\n"
            f"Title: {result['title']}\n\n"
            f"{result['content']}"
        )
        return ToolResult(success=True, data=output)
