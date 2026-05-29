import pytest
from odigos.tools.arg_guard import reject_dangerous_args, ArgGuardError


def test_blocks_path_traversal():
    with pytest.raises(ArgGuardError):
        reject_dangerous_args(["x", "../etc/passwd"])


def test_blocks_output_and_config_flags():
    with pytest.raises(ArgGuardError):
        reject_dangerous_args(["search", "--config", "/etc/passwd"])
    with pytest.raises(ArgGuardError):
        reject_dangerous_args(["x", "--output", "/app/main.py"])


def test_blocks_shell_metachars():
    with pytest.raises(ArgGuardError):
        reject_dangerous_args(["x", "$(whoami)"])


def test_allows_normal_args():
    reject_dangerous_args(["search", "foo"])
    reject_dangerous_args(["search", "--limit", "5"])


def test_option_args_rejected_only_when_requested():
    reject_dangerous_args(["search", "--limit", "5"])  # ok by default
    with pytest.raises(ArgGuardError):
        reject_dangerous_args(["--force"], reject_option_args=True)
    with pytest.raises(ArgGuardError):
        reject_dangerous_args(["/etc/passwd"], reject_option_args=True)
