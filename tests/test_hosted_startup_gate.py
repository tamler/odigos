import pytest
from odigos.bootstrap import _enforce_hosted_security
from tests.conftest import make_test_settings


def test_hosted_rejects_insecure_override(monkeypatch):
    monkeypatch.setenv("ODIGOS_SANDBOX_ALLOW_INSECURE", "1")
    s = make_test_settings(deployment={"mode": "hosted"})
    with pytest.raises(RuntimeError, match="ODIGOS_SANDBOX_ALLOW_INSECURE"):
        _enforce_hosted_security(s, bwrap_present=True)


def test_hosted_requires_bwrap(monkeypatch):
    monkeypatch.delenv("ODIGOS_SANDBOX_ALLOW_INSECURE", raising=False)
    s = make_test_settings(deployment={"mode": "hosted"})
    with pytest.raises(RuntimeError, match="bubblewrap"):
        _enforce_hosted_security(s, bwrap_present=False)


def test_dev_mode_permits_everything(monkeypatch):
    monkeypatch.setenv("ODIGOS_SANDBOX_ALLOW_INSECURE", "1")
    s = make_test_settings(deployment={"mode": "dev"})
    _enforce_hosted_security(s, bwrap_present=False)  # must not raise


def test_hosted_passes_when_secure(monkeypatch):
    monkeypatch.delenv("ODIGOS_SANDBOX_ALLOW_INSECURE", raising=False)
    s = make_test_settings(deployment={"mode": "hosted"})
    _enforce_hosted_security(s, bwrap_present=True)  # must not raise


def test_hosted_gate_rejects_present_but_broken_bwrap(monkeypatch):
    """`which bwrap` succeeding is not enough — the tier must resolve to bwrap.

    Regression: a hosted install booted with isolation="ulimit" (no filesystem
    isolation) because the gate only checked that the binary was on PATH.
    """
    from odigos.providers.sandbox import SandboxProvider

    monkeypatch.delenv("ODIGOS_SANDBOX_ALLOW_INSECURE", raising=False)
    monkeypatch.setattr(SandboxProvider, "_isolation", "ulimit")
    s = make_test_settings(deployment={"mode": "hosted"})
    with pytest.raises(RuntimeError, match="bubblewrap"):
        _enforce_hosted_security(s)


def test_bwrap_probe_matches_exec_paths():
    """The probe must not be stricter than the sandbox it is probing for.

    Regression: the probe omitted `--symlink /usr/lib64 /lib64`, so on x86_64
    the ELF loader was missing inside the namespace, every binary failed with
    ENOENT, and bwrap isolation silently degraded to ulimit-only everywhere.
    """
    import inspect
    from odigos.providers.sandbox import SandboxProvider

    src = inspect.getsource(SandboxProvider._detect_isolation)
    probe = src[src.index("probe_cmd"):]
    for mount in ('"--symlink", "/usr/lib", "/lib"', '"--symlink", "/usr/lib64", "/lib64"'):
        assert mount in probe, f"probe is missing {mount}"
