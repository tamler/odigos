"""Tests for the WebSocket connection manager."""

import asyncio

import pytest

from odigos.config import PeerConfig
from odigos.core.ws_connector import WSConnector, MAX_BACKOFF


class FakeAgentClient:
    """Minimal stub for testing WSConnector without real connections."""
    def __init__(self):
        self.agent_name = "TestAgent"
        self._ws_connections = {}

    def build_announce(self):
        from odigos.core.agent_client import PeerEnvelope
        return PeerEnvelope(
            from_agent="TestAgent", to_agent="*",
            type="registry_announce", payload={},
        )

    async def handle_incoming(self, msg, peer_ip=""):
        pass

    async def flush_outbox(self):
        return 0


class TestWSConnectorLifecycle:
    async def test_start_stop_no_crash(self):
        """WSConnector starts and stops cleanly with no peers."""
        client = FakeAgentClient()
        connector = WSConnector(agent_client=client, agent_name="Test", peers=[])
        await connector.start()
        assert connector._running is True
        assert len(connector._tasks) == 0
        await connector.stop()
        assert connector._running is False

    async def test_start_creates_tasks_for_peers_with_ip(self):
        """Tasks are created only for peers that have netbird_ip."""
        client = FakeAgentClient()
        peers = [
            PeerConfig(name="WithIP", netbird_ip="10.0.0.1", ws_port=8001),
            PeerConfig(name="NoIP", netbird_ip="", ws_port=8001),
        ]
        connector = WSConnector(agent_client=client, agent_name="Test", peers=peers)
        await connector.start()
        assert "WithIP" in connector._tasks
        assert "NoIP" not in connector._tasks
        await connector.stop()

    async def test_stop_cancels_tasks(self):
        """Stop cancels all running connection tasks."""
        client = FakeAgentClient()
        peers = [PeerConfig(name="Peer1", netbird_ip="10.0.0.1", ws_port=8001)]
        connector = WSConnector(agent_client=client, agent_name="Test", peers=peers)
        await connector.start()
        assert len(connector._tasks) == 1
        await connector.stop()
        assert len(connector._tasks) == 0


class TestWSConnectorBackoff:
    def test_max_backoff_constant(self):
        assert MAX_BACKOFF == 60


class TestMeshAPI:
    """Test the mesh API endpoints."""

    @pytest.fixture
    async def db(self, tmp_db_path):
        from odigos.db import Database
        database = Database(tmp_db_path, migrations_dir="migrations")
        await database.initialize()
        yield database
        await database.close()

    @pytest.fixture
    def app(self, db):
        from fastapi import FastAPI
        from odigos.api.mesh import router
        from odigos.config import Settings

        app = FastAPI()
        app.state.settings = Settings(api_key="test-key")
        app.state.db = db
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient
        client = TestClient(app)
        client.headers["Authorization"] = "Bearer test-key"
        return client

    def test_list_peers_empty(self, client):
        resp = client.get("/api/mesh/peers")
        assert resp.status_code == 200
        assert resp.json()["peers"] == []

    def test_list_messages_empty(self, client):
        resp = client.get("/api/mesh/messages")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_ping_unknown_peer(self, client):
        resp = client.post("/api/mesh/peers/unknown/ping")
        assert resp.status_code == 200
        assert resp.json()["reachable"] is False
