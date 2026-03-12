"""SearXNG web search plugin.

Registers the web_search tool when searxng_url is configured.
Requires a running SearXNG instance.
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.searxng_url:
        return

    from odigos.providers.searxng import SearxngProvider
    from odigos.tools.search import SearchTool

    searxng = SearxngProvider(
        url=settings.searxng_url,
        username=settings.searxng_username,
        password=settings.searxng_password,
    )
    search_tool = SearchTool(searxng=searxng)
    ctx.register_tool(search_tool)
    logger.info("SearXNG search plugin loaded (%s)", settings.searxng_url)
