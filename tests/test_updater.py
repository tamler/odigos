"""Tests for odigos.core.updater."""
from __future__ import annotations

from odigos.config import AutoUpdateConfig
from odigos.core.updater import (
    _run_git,
    apply_update,
    check_for_updates,
    is_git_repo,
)


def test_is_git_repo():
    """Should return True when run inside the project directory."""
    assert is_git_repo() is True


def test_run_git_returns_tuple():
    """_run_git returns (int, str) tuple."""
    code, output = _run_git("rev-parse", "--is-inside-work-tree")
    assert isinstance(code, int)
    assert isinstance(output, str)


def test_check_for_updates_no_repo(monkeypatch):
    """When not in a git repo, returns None."""
    monkeypatch.setattr(
        "odigos.core.updater._run_git",
        lambda *args, **kw: (128, "not a git repo"),
    )
    result = check_for_updates("main")
    assert result is None


def test_check_for_updates_up_to_date(monkeypatch):
    """When local and remote hashes match, returns None."""
    fake_hash = "abc1234567890def"
    call_count = 0

    def fake_run_git(*args, **kw):
        nonlocal call_count
        call_count += 1
        cmd = args[0] if args else ""
        if cmd == "rev-parse":
            if "--is-inside-work-tree" in args:
                return (0, "true")
            # Both HEAD and origin/main return same hash
            return (0, fake_hash)
        if cmd == "fetch":
            return (0, "")
        return (0, "")

    monkeypatch.setattr(
        "odigos.core.updater._run_git", fake_run_git,
    )
    result = check_for_updates("main")
    assert result is None


def test_check_for_updates_has_updates(monkeypatch):
    """When remote has new commits, returns info dict."""
    def fake_run_git(*args, **kw):
        cmd = args[0] if args else ""
        if cmd == "rev-parse":
            if "--is-inside-work-tree" in args:
                return (0, "true")
            if "origin/" in args[-1]:
                return (0, "bbbb2222bbbb2222")
            return (0, "aaaa1111aaaa1111")
        if cmd == "fetch":
            return (0, "")
        if cmd == "log":
            return (0, "bbbb222 feat: new stuff\nbbbb111 fix: old stuff")
        return (0, "")

    monkeypatch.setattr(
        "odigos.core.updater._run_git", fake_run_git,
    )
    result = check_for_updates("main")
    assert result is not None
    assert result["local"] == "aaaa1111"
    assert result["remote"] == "bbbb2222"
    assert result["commits"] == 2
    assert "new stuff" in result["log"]


def test_apply_update_success(monkeypatch):
    """Successful git pull returns (True, output)."""
    def fake_run_git(*args, **kw):
        cmd = args[0] if args else ""
        if cmd == "pull":
            return (0, "Already up to date.")
        if cmd == "diff":
            return (0, "odigos/core/updater.py")
        return (0, "")

    monkeypatch.setattr(
        "odigos.core.updater._run_git", fake_run_git,
    )
    success, msg = apply_update("main")
    assert success is True
    assert "Already up to date" in msg


def test_apply_update_failure(monkeypatch):
    """Failed git pull returns (False, error message)."""
    def fake_run_git(*args, **kw):
        cmd = args[0] if args else ""
        if cmd == "pull":
            return (1, "merge conflict")
        return (0, "")

    monkeypatch.setattr(
        "odigos.core.updater._run_git", fake_run_git,
    )
    success, msg = apply_update("main")
    assert success is False
    assert "git pull failed" in msg


def test_config_defaults():
    """AutoUpdateConfig has expected defaults."""
    cfg = AutoUpdateConfig()
    assert cfg.enabled is False
    assert cfg.check_interval_ticks == 60
    assert cfg.auto_apply is False
    assert cfg.branch == "main"


def test_config_custom_values():
    """AutoUpdateConfig accepts custom values."""
    cfg = AutoUpdateConfig(
        enabled=True,
        check_interval_ticks=30,
        auto_apply=True,
        branch="develop",
    )
    assert cfg.enabled is True
    assert cfg.check_interval_ticks == 30
    assert cfg.auto_apply is True
    assert cfg.branch == "develop"
