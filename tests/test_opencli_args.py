import pytest

import odigos.tools.opencli as opencli
from odigos.tools.opencli import WebPlatformTool


@pytest.mark.asyncio
async def test_opencli_blocks_config_flag(monkeypatch):
    # Ensure the OPENCLI_BIN check passes so we reach the arg guard.
    monkeypatch.setattr(opencli, "OPENCLI_BIN", "/bin/true")
    tool = WebPlatformTool()
    res = await tool.execute(
        {"platform": "twitter", "command": "search --config /etc/passwd"}
    )
    assert res.success is False
