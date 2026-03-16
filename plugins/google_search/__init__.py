"""Google Custom Search plugin.

Registers the web_search tool when google_search_api_key and google_search_cx
are configured.
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.google_search_api_key:
        return {"status": "available", "error_message": "No google_search_api_key configured"}
    if not settings.google_search_cx:
        return {"status": "available", "error_message": "No google_search_cx configured"}

    from odigos.providers.google_search import GoogleSearchProvider
    from odigos.tools.search import SearchTool

    provider = GoogleSearchProvider(
        api_key=settings.google_search_api_key,
        cx=settings.google_search_cx,
    )
    search_tool = SearchTool(provider=provider)
    ctx.register_tool(search_tool)
    logger.info("Google Custom Search plugin loaded")
