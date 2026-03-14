from odigos.config import PeerConfig, Settings


def test_peer_config_fields():
    peer = PeerConfig(name="helper", netbird_ip="100.64.0.1")
    assert peer.name == "helper"
    assert peer.netbird_ip == "100.64.0.1"
    assert peer.api_key == ""


def test_peer_config_with_api_key():
    peer = PeerConfig(name="helper", netbird_ip="100.64.0.1", api_key="secret")
    assert peer.api_key == "secret"


def test_settings_defaults_to_empty_peers():
    s = Settings(telegram_bot_token="fake", llm_api_key="fake")
    assert s.peers == []


def test_settings_with_peers():
    s = Settings(
        telegram_bot_token="fake",
        llm_api_key="fake",
        peers=[
            {"name": "agent-a", "netbird_ip": "100.64.0.2", "api_key": "key-a"},
            {"name": "agent-b", "netbird_ip": "100.64.0.3"},
        ],
    )
    assert len(s.peers) == 2
    assert s.peers[0].name == "agent-a"
    assert s.peers[0].api_key == "key-a"
    assert s.peers[1].api_key == ""
