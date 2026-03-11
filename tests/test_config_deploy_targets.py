"""Test deploy target config fields."""
from odigos.config import DeployTargetConfig, Settings


def test_deploy_target_config():
    target = DeployTargetConfig(
        name="vps-1", host="100.64.0.1", method="docker",
        ssh_user="deployer", ssh_key_path="/home/deployer/.ssh/id_ed25519"
    )
    assert target.name == "vps-1"
    assert target.host == "100.64.0.1"
    assert target.method == "docker"
    assert target.ssh_user == "deployer"


def test_deploy_target_defaults():
    target = DeployTargetConfig(name="test", host="10.0.0.1")
    assert target.method == "docker"
    assert target.ssh_user == "root"
    assert target.ssh_key_path is None


def test_settings_has_deploy_targets():
    s = Settings(llm_api_key="test")
    assert s.deploy_targets == []
