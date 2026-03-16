"""Tests for search provider classes and shared SearchResult."""
from __future__ import annotations

import asyncio
import inspect

from odigos.providers.search_base import SearchResult
from odigos.providers.brave import BraveSearchProvider
from odigos.providers.google_search import GoogleSearchProvider
from odigos.providers.searxng import SearxngProvider


def test_search_result_dataclass():
    r = SearchResult(title="T", url="https://x.com", snippet="S")
    assert r.title == "T"
    assert r.url == "https://x.com"
    assert r.snippet == "S"


def test_searxng_reexports_search_result():
    """SearxngProvider module still exposes SearchResult for backward compat."""
    from odigos.providers.searxng import SearchResult as SR
    assert SR is SearchResult


def test_brave_provider_instantiates():
    provider = BraveSearchProvider(api_key="test-key")
    assert provider.api_key == "test-key"
    assert hasattr(provider, "search")
    assert inspect.iscoroutinefunction(provider.search)


def test_google_provider_instantiates():
    provider = GoogleSearchProvider(api_key="test-key", cx="test-cx")
    assert provider.api_key == "test-key"
    assert provider.cx == "test-cx"
    assert hasattr(provider, "search")
    assert inspect.iscoroutinefunction(provider.search)


def test_searxng_provider_instantiates():
    provider = SearxngProvider(url="http://localhost:8080", username="", password="")
    assert hasattr(provider, "search")
    assert inspect.iscoroutinefunction(provider.search)


def test_brave_search_signature():
    sig = inspect.signature(BraveSearchProvider.search)
    params = list(sig.parameters.keys())
    assert "query" in params
    assert "num_results" in params


def test_google_search_signature():
    sig = inspect.signature(GoogleSearchProvider.search)
    params = list(sig.parameters.keys())
    assert "query" in params
    assert "num_results" in params


def test_search_tool_accepts_brave_provider():
    from odigos.tools.search import SearchTool
    provider = BraveSearchProvider(api_key="test")
    tool = SearchTool(provider=provider)
    assert tool._provider is provider


def test_search_tool_accepts_google_provider():
    from odigos.tools.search import SearchTool
    provider = GoogleSearchProvider(api_key="test", cx="cx")
    tool = SearchTool(provider=provider)
    assert tool._provider is provider


def test_search_tool_legacy_searxng_kwarg():
    from odigos.tools.search import SearchTool
    provider = SearxngProvider(url="http://localhost:8080", username="", password="")
    tool = SearchTool(searxng=provider)
    assert tool._provider is provider
    assert tool.searxng is provider


def test_config_has_new_fields():
    from odigos.config import Settings
    s = Settings()
    assert s.brave_api_key == ""
    assert s.google_search_api_key == ""
    assert s.google_search_cx == ""
