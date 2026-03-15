import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app():
    from odigos.api.agent_message import router

    app = FastAPI()

    settings = MagicMock()
    settings.api_key = "test-key"

    db = AsyncMock()
    db.fetch_one = AsyncMock(return_value=None)
    db.execute = AsyncMock()

    agent_client = MagicMock()
    agent_client.list_peer_names = MagicMock(return_value=["Archie"])
    agent_client.add_discovered_peer = MagicMock()

    app.state.settings = settings
    app.state.db = db
    app.state.agent_client = agent_client

    app.include_router(router)
    return app, agent_client


class TestPeerAnnounce:
    def test_announce_registers_peer(self):
        app, agent_client = _make_app()
        client = TestClient(app)

        resp = client.post(
            "/api/agent/peer/announce",
            json={
                "agent_name": "Archie",
                "ws_host": "100.64.0.2",
                "ws_port": 8001,
                "role": "backend_dev",
                "description": "Backend specialist",
            },
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_announce_requires_auth(self):
        app, _ = _make_app()
        client = TestClient(app)

        resp = client.post(
            "/api/agent/peer/announce",
            json={"agent_name": "Archie", "ws_host": "100.64.0.2"},
        )
        assert resp.status_code in (401, 403)

    def test_old_message_endpoint_removed(self):
        app, _ = _make_app()
        client = TestClient(app)

        resp = client.post(
            "/api/agent/message",
            json={"from_agent": "Archie", "content": "hello"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code in (404, 405, 422)
