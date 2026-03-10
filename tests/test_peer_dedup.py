import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from odigos.core.peers import PeerClient
from odigos.config import PeerConfig
from odigos.db import Database


@pytest.fixture
async def db(tmp_db_path):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def peers():
    return [PeerConfig(name="sarah", url="http://sarah.local:8000", api_key="key")]


@pytest.fixture
def client(peers, db):
    return PeerClient(peers=peers, agent_name="odigos", db=db)


class TestOutboundTracking:
    @pytest.mark.asyncio
    async def test_send_records_message(self, client, db):
        """Sending a message records it in peer_messages."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"status": "ok"}
        mock_http = AsyncMock()
        mock_http.post.return_value = mock_resp
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("odigos.core.peers.httpx.AsyncClient", return_value=mock_http):
            result = await client.send("sarah", "hello")

        assert result["status"] == "ok"
        row = await db.fetch_one(
            "SELECT * FROM peer_messages WHERE direction = 'outbound' AND peer_name = 'sarah'"
        )
        assert row is not None
        assert row["content"] == "hello"
        assert row["status"] == "delivered"

    @pytest.mark.asyncio
    async def test_send_failure_records_failed_status(self, client, db):
        """Failed send records status as 'failed'."""
        mock_resp = MagicMock(status_code=500)
        mock_resp.json.return_value = {}
        mock_http = AsyncMock()
        mock_http.post.return_value = mock_resp
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("odigos.core.peers.httpx.AsyncClient", return_value=mock_http):
            result = await client.send("sarah", "hello")

        row = await db.fetch_one(
            "SELECT * FROM peer_messages WHERE direction = 'outbound' AND peer_name = 'sarah'"
        )
        assert row["status"] == "failed"

    @pytest.mark.asyncio
    async def test_send_without_db_still_works(self):
        """PeerClient without db parameter still sends (backward compat)."""
        client = PeerClient(
            peers=[PeerConfig(name="sarah", url="http://sarah.local:8000", api_key="key")],
            agent_name="odigos",
        )
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"status": "ok"}
        mock_http = AsyncMock()
        mock_http.post.return_value = mock_resp
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("odigos.core.peers.httpx.AsyncClient", return_value=mock_http):
            result = await client.send("sarah", "hello")
        assert result["status"] == "ok"
