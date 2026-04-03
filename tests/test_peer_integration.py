import importlib

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient

from odigos.container import Container

pytestmark = pytest.mark.skipif(
    not importlib.util.find_spec("sentence_transformers"),
    reason="sentence_transformers not installed",
)


class TestPeerEndpointMounted:
    @pytest.mark.asyncio
    async def test_peer_announce_endpoint_exists(self):
        from odigos.main import app

        mock_db = MagicMock()
        mock_db.fetch_one = AsyncMock(return_value={"agent_name": "test-peer"})
        mock_db.execute = AsyncMock()
        app.state.container = Container(
            settings=type("S", (), {"api_key": "test-key"})(),
            db=mock_db,
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-key"},
        ) as c:
            resp = await c.post("/api/agent/peer/announce", json={
                "agent_name": "test-peer",
                "ws_host": "100.64.0.1",
                "ws_port": 8001,
                "role": "tester",
                "description": "Test peer",
            })
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
