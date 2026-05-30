import pytest

from odigos.tools.cli_tool import _validate_cli_arg, CLIToolError


def test_default_allows_option_flags():
    _validate_cli_arg("--output")   # must NOT raise in default mode
    _validate_cli_arg("json")
    _validate_cli_arg("-o")


def test_default_still_blocks_traversal_and_metachars():
    with pytest.raises(CLIToolError):
        _validate_cli_arg("../etc/passwd")
    with pytest.raises(CLIToolError):
        _validate_cli_arg("$(whoami)")


def test_reject_option_args_blocks_flags_and_abspaths():
    with pytest.raises(CLIToolError):
        _validate_cli_arg("--force", reject_option_args=True)
    with pytest.raises(CLIToolError):
        _validate_cli_arg("/etc/passwd", reject_option_args=True)


def test_reject_option_args_allows_plain_values():
    _validate_cli_arg("hello", reject_option_args=True)
    _validate_cli_arg("123", reject_option_args=True)
