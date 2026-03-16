"""Brave Search plugin.

Registers the web_search tool when brave_api_key is configured.
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.brave_api_key:
        return {"status": "available", "error_message": "No brave_api_key configured"}

    from odigos.providers.brave import BraveSearchProvider
    from odigos.tools.search import SearchTool

    provider = BraveSearchProvider(api_key=settings.brave_api_key)
    search_tool = SearchTool(provider=provider)
    ctx.register_tool(search_tool)
    logger.info("Brave Search plugin loaded")
