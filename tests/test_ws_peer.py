import pytest

from odigos.channels.web import WebChannel


class FakeWebSocket:
    """Minimal WebSocket mock for testing."""

    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_json(self, data):
        self.sent.append(data)

    async def accept(self):
        pass

    async def close(self, code=1000, reason=""):
        self.closed = True


class TestWebChannelPeerSupport:
    def test_register_peer_connection(self):
        """Can register a peer agent connection."""
        wc = WebChannel()
        ws = FakeWebSocket()
        wc.register_connection("peer:sarah", ws)
        assert ws in wc._connections["peer:sarah"]

    @pytest.mark.asyncio
    async def test_send_to_peer(self):
        """Can send a message to a connected peer."""
        wc = WebChannel()
        ws = FakeWebSocket()
        wc.register_connection("peer:sarah", ws)
        await wc.send_message("peer:sarah", "Hello Sarah")
        assert len(ws.sent) == 1
        assert ws.sent[0]["content"] == "Hello Sarah"

    def test_list_connected_peers(self):
        """Can list all connected peer conversation_ids."""
        wc = WebChannel()
        wc.register_connection("peer:sarah", FakeWebSocket())
        wc.register_connection("peer:bob", FakeWebSocket())
        wc.register_connection("web:abc123", FakeWebSocket())
        peers = wc.connected_peers()
        assert sorted(peers) == ["peer:bob", "peer:sarah"]

    def test_is_peer_connected(self):
        """Can check if a specific peer is connected."""
        wc = WebChannel()
        wc.register_connection("peer:sarah", FakeWebSocket())
        assert wc.is_peer_connected("sarah") is True
        assert wc.is_peer_connected("bob") is False

    def test_no_peers_connected(self):
        """Returns empty list when no peers connected."""
        wc = WebChannel()
        wc.register_connection("web:abc", FakeWebSocket())
        assert wc.connected_peers() == []
        assert wc.is_peer_connected("anyone") is False
