import pytest


class _MD:
    def __init__(self):
        self.fetched = False

    def convert_url(self, url):
        # If the guard is missing, the blocked URL reaches here and "succeeds",
        # making the test fail (red). The guard must short-circuit before this.
        self.fetched = True
        return "fetched"

    def convert_file(self, path):
        return "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.1/",
])
async def test_process_document_blocks_internal_urls(url):
    from odigos.tools.document import DocTool

    md = _MD()
    tool = DocTool(markitdown_provider=md)
    res = await tool.execute({"source": url})
    assert res.success is False
    assert md.fetched is False
