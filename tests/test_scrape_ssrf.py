import pytest


class _Scraper:
    async def scrape(self, url, tier="standard"):
        raise AssertionError("must not scrape a blocked URL")


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8002/", "http://169.254.169.254/", "http://localhost:2019/config",
])
async def test_read_page_blocks_internal(url):
    from odigos.tools.scrape import ScrapeTool
    res = await ScrapeTool(scraper=_Scraper()).execute({"url": url})
    assert res.success is False
    err = (res.error or "").lower()
    assert "private" in err or "internal" in err
