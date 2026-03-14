"""Test agent identity config fields."""
from odigos.config import AgentConfig, PeerConfig, Settings


def test_agent_config_has_identity_fields():
    cfg = AgentConfig(name="TestBot", role="specialist", description="A test bot", parent="Odigos")
    assert cfg.role == "specialist"
    assert cfg.description == "A test bot"
    assert cfg.parent == "Odigos"
    assert cfg.allow_external_evaluation is False


def test_agent_config_defaults():
    cfg = AgentConfig()
    assert cfg.role == "personal_assistant"
    assert cfg.description == ""
    assert cfg.parent is None
    assert cfg.allow_external_evaluation is False


def test_peer_config_has_netbird_fields():
    peer = PeerConfig(name="Archie", netbird_ip="100.64.0.2", ws_port=8001, api_key="secret")
    assert peer.netbird_ip == "100.64.0.2"
    assert peer.ws_port == 8001
