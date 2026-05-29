from odigos.providers.sandbox import SandboxProvider


def test_bwrap_profile_does_not_bind_sensitive_roots(monkeypatch):
    monkeypatch.setattr(SandboxProvider, "_isolation", "bwrap")
    sb = SandboxProvider(require_isolation=True)
    cmd = sb._wrap_isolation(["python3", "-c", "pass"], "/tmp/x")
    joined = " ".join(cmd)
    for forbidden in ("/opt", "/home", "/root", "/etc"):
        assert f" {forbidden} {forbidden}" not in joined, f"must not bind {forbidden}"


def test_bwrap_profile_uses_minimal_dev(monkeypatch):
    monkeypatch.setattr(SandboxProvider, "_isolation", "bwrap")
    sb = SandboxProvider(require_isolation=True)
    cmd = sb._wrap_isolation(["python3", "-c", "pass"], "/tmp/x")
    # Minimal /dev: explicit device binds, not a blanket --dev /dev
    assert "--dev-bind" in cmd or all(
        not (cmd[i] == "--dev" and cmd[i + 1] == "/dev") for i in range(len(cmd) - 1)
    )
