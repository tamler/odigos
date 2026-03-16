from odigos.utils.cli_installer import is_installed


def test_is_installed_finds_python():
    assert is_installed("python3")


def test_is_installed_returns_false_for_missing():
    assert not is_installed("nonexistent-command-12345")
