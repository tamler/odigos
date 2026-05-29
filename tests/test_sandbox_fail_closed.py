import pytest
from odigos.providers.sandbox import SandboxProvider


@pytest.mark.asyncio
async def test_execute_disabled_when_isolation_required_but_absent(monkeypatch):
    monkeypatch.delenv("ODIGOS_SANDBOX_ALLOW_INSECURE", raising=False)
    sb = SandboxProvider(require_isolation=True)
    monkeypatch.setattr(SandboxProvider, "_isolation", "ulimit")
    spawned = {"called": False}

    async def _boom(*a, **k):
        spawned["called"] = True
        raise AssertionError("must not spawn a subprocess when isolation is required and absent")

    monkeypatch.setattr("asyncio.create_subprocess_exec", _boom)
    res = await sb.execute("print('hi')", language="python")
    assert res.exit_code == -1
    assert "isolation" in res.stderr.lower()
    assert spawned["called"] is False


@pytest.mark.asyncio
async def test_execute_allowed_when_isolation_not_required(monkeypatch):
    monkeypatch.delenv("ODIGOS_SANDBOX_ALLOW_INSECURE", raising=False)
    sb = SandboxProvider(require_isolation=False)
    monkeypatch.setattr(SandboxProvider, "_isolation", "ulimit")
    res = await sb.execute("print('hi')", language="python")
    assert "isolation (bubblewrap) is required" not in res.stderr


@pytest.mark.asyncio
async def test_insecure_env_var_bypasses_gate_in_dev(monkeypatch):
    monkeypatch.setenv("ODIGOS_SANDBOX_ALLOW_INSECURE", "1")
    sb = SandboxProvider(require_isolation=True)
    monkeypatch.setattr(SandboxProvider, "_isolation", "ulimit")
    res = await sb.execute("print('hi')", language="python")
    assert "isolation (bubblewrap) is required" not in res.stderr
