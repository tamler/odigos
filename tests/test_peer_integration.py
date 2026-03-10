import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient


class TestPeerEndpointMounted:
    @pytest.mark.asyncio
    async def test_agent_message_endpoint_exists(self):
        from odigos.main import app

        app.state.agent = MagicMock()
        app.state.agent.handle_message = AsyncMock(return_value="ok")
        app.state.settings = type("S", (), {"api_key": ""})()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/agent/message", json={
                "from_agent": "test-peer",
                "message_type": "message",
                "content": "ping",
            })
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
