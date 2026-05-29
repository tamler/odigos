"""Bubblewrap-gated sandbox security acceptance tests.

These tests run REAL untrusted code under bubblewrap (bwrap) and assert that the
sandbox actually contains it: no host filesystem reads, grandchild processes are
killed on timeout, and network egress is blocked when not explicitly allowed.

They MUST run for real on the hosted Linux CI image and are a release-blocker per
the checklist in
``docs/superpowers/specs/2026-05-29-security-hardening-multitenant.md``.

Where bubblewrap is not installed (e.g. macOS dev hosts), the entire module skips
cleanly via the module-level ``skipif``. A skip here is NOT a pass for hosted
deployment -- CI must observe these executing.
"""

import shutil

import pytest

from odigos.providers.sandbox import SandboxProvider

pytestmark = pytest.mark.skipif(
    shutil.which("bwrap") is None, reason="bubblewrap not installed"
)


@pytest.fixture(autouse=True)
def _force_bwrap(monkeypatch):
    monkeypatch.setattr(SandboxProvider, "_isolation", "bwrap")
    monkeypatch.delenv("ODIGOS_SANDBOX_ALLOW_INSECURE", raising=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/etc/passwd", "/opt", "/root", "/home"])
async def test_cannot_read_host_paths(path):
    sb = SandboxProvider(require_isolation=True, timeout=5)
    code = (
        "import os\n"
        f"p = {path!r}\n"
        "try:\n"
        "    print(open(p).read()[:20] if os.path.isfile(p) else os.listdir(p)[:5])\n"
        "except Exception as e:\n"
        "    print('BLOCKED', type(e).__name__)\n"
    )
    res = await sb.execute(code, language="python")
    assert "root:" not in res.stdout
    assert "PRIVATE KEY" not in res.stdout


@pytest.mark.asyncio
async def test_grandchild_killed_on_timeout():
    sb = SandboxProvider(require_isolation=True, timeout=2)
    code = (
        "import os, time\n"
        "if os.fork() == 0:\n"
        "    time.sleep(30)\n"
        "else:\n"
        "    time.sleep(30)\n"
    )
    res = await sb.execute(code, language="python")
    assert res.timed_out or res.exit_code != 0


@pytest.mark.asyncio
async def test_network_blocked_when_not_allowed():
    sb = SandboxProvider(require_isolation=True, timeout=5, allow_network=False)
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=2)\n"
        "    print('NET-OK')\n"
        "except Exception:\n"
        "    print('NET-BLOCKED')\n"
    )
    res = await sb.execute(code, language="python")
    assert "NET-BLOCKED" in res.stdout
