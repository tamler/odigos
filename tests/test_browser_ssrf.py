import pytest
from odigos.tools.browser import BrowserTool


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", [
    "navigate --url http://localhost:2019/config",
    "navigate --url http://127.0.0.1:8002/",
    "navigate --url file:///etc/passwd",
])
async def test_browser_blocks_internal_urls(cmd):
    res = await BrowserTool().execute({"command": cmd})
    assert res.success is False
    err = (res.error or "").lower()
    assert "url" in err or "private" in err or "internal" in err


@pytest.mark.asyncio
async def test_browser_blocks_malformed_command():
    res = await BrowserTool().execute({"command": 'navigate --url "unterminated'})
    assert res.success is False


@pytest.mark.asyncio
async def test_browser_allows_public_url_passes_guard(monkeypatch):
    # A public URL must pass the guard and reach super().execute (which will then
    # fail because agent-browser isn't installed — that's fine, it's past the guard).
    res = await BrowserTool().execute({"command": "navigate --url https://example.com"})
    # Not blocked by the URL guard: error should be about the binary, not the URL.
    assert "private" not in (res.error or "").lower()
    assert "internal" not in (res.error or "").lower()
