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
