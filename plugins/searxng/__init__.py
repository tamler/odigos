"""Web Search plugin.

Registers the web_search tool using SearXNG, Brave, or Google Custom Search.
Provider is chosen via settings.search_provider or auto-detected from
configured credentials.
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings:
        return {"status": "available", "error_message": "No settings configured"}

    provider_name = (settings.search_provider or "").strip().lower()

    # Auto-detect provider when search_provider is empty
    if not provider_name:
        if settings.searxng_url:
            provider_name = "searxng"
        elif settings.brave_api_key:
            provider_name = "brave"
        elif settings.google_search_api_key and settings.google_search_cx:
            provider_name = "google"
        else:
            return {"status": "available", "error_message": "No search provider configured"}

    from odigos.tools.search import SearchTool

    if provider_name == "searxng":
        if not settings.searxng_url:
            return {"status": "error", "error_message": "search_provider is 'searxng' but no searxng_url configured"}
        from odigos.providers.searxng import SearxngProvider
        provider = SearxngProvider(
            url=settings.searxng_url,
            username=settings.searxng_username,
            password=settings.searxng_password,
        )
        label = f"SearXNG ({settings.searxng_url})"

    elif provider_name == "brave":
        if not settings.brave_api_key:
            return {"status": "error", "error_message": "search_provider is 'brave' but no brave_api_key configured"}
        from odigos.providers.brave import BraveSearchProvider
        provider = BraveSearchProvider(api_key=settings.brave_api_key)
        label = "Brave Search"

    elif provider_name == "google":
        if not settings.google_search_api_key:
            return {"status": "error", "error_message": "search_provider is 'google' but no google_search_api_key configured"}
        if not settings.google_search_cx:
            return {"status": "error", "error_message": "search_provider is 'google' but no google_search_cx configured"}
        from odigos.providers.google_search import GoogleSearchProvider
        provider = GoogleSearchProvider(
            api_key=settings.google_search_api_key,
            cx=settings.google_search_cx,
        )
        label = "Google Custom Search"

    else:
        return {"status": "error", "error_message": f"Unknown search_provider: {provider_name}"}

    search_tool = SearchTool(provider=provider)
    ctx.register_tool(search_tool)
    logger.info("Web Search plugin loaded (%s)", label)
