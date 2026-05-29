import pytest
from odigos.providers.sandbox import SandboxProvider


@pytest.mark.asyncio
async def test_execute_disabled_when_isolation_required_but_absent(monkeypatch):
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
    sb = SandboxProvider(require_isolation=False)
    monkeypatch.setattr(SandboxProvider, "_isolation", "ulimit")
    res = await sb.execute("print('hi')", language="python")
    assert "isolation (bubblewrap) is required" not in res.stderr
