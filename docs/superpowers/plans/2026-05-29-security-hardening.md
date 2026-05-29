# Security Hardening (Hosted Launch) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the in-repo findings from the whole-system security review — sandbox fail-closed, SSRF blocking, auth/CSRF hardening, and defense-in-depth — so the hosted agents (Bob, Jessica) launch without RCE, cross-install exfiltration, SSRF into local services, CSRF, or auth bypass.

**Architecture:** A single `deployment.mode` switch (`dev`|`hosted`) forces the secure posture in production. Two new shared modules — `odigos/tools/url_guard.py` (SSRF) and a subprocess arg-guard — remove duplication. The sandbox refuses to run code unless bubblewrap isolation is active. Each finding gets a test that fails before the fix and passes after.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, pytest/pytest-asyncio, bcrypt, PyJWT, itsdangerous, bubblewrap.

**Spec:** `docs/superpowers/specs/2026-05-29-security-hardening-multitenant.md`. OS/systemd hardening (C0) is tracked separately in `docs/deployment/2026-05-29-os-isolation-checklist.md` and is NOT part of this plan.

**Test command (canonical):** `.venv/bin/python -m pytest <path> -p no:cacheprovider -q`. Full suite gate: `.venv/bin/python -m pytest -m "not slow and not network" -p no:cacheprovider -q`.

**Conventions observed in this repo:** no mocks for integration paths where a real check is cheap; mock only the actual outbound network/subprocess sink. ruff line-length 100. No TODO/placeholder comments.

---

## File Structure

**New files:**
- `odigos/tools/url_guard.py` — single SSRF guard: `is_blocked_url(url, policy=None)`, `resolve_safe_host(url)`. Used by scrape/document/browser.
- `odigos/tools/arg_guard.py` — shared subprocess argument validation: `reject_dangerous_args(args, *, reject_option_args=False)`.
- `odigos/security/events.py` — structured, rate-limited, redacting security event logger.
- Test files mirror under `tests/`.

**Modified files (with verified anchors):**
- `odigos/config.py` — `deployment` + `sandbox` config blocks; `sso_auto_provision` default flip (line ~316).
- `odigos/providers/sandbox.py` — fail-closed gate, minimal `/dev`, profile pinning.
- `odigos/tools/code.py` — surface disabled error.
- `odigos/tools/scrape.py:18-30,57` — use `url_guard`.
- `odigos/tools/document.py:65-76` — guard URL branch.
- `odigos/tools/browser.py` — URL-bearing arg guard + hosted no-internet default.
- `odigos/tools/opencli.py:69` — `shlex.split` + arg-guard.
- `odigos/tools/cli_tool.py:104-109` — `reject_option_args` mode.
- `odigos/tools/audio_process.py:247-250` — time-arg validation.
- `odigos/api/auth.py` — cookie attrs (97-107), CSRF on facts/profile (453,475), session epoch, SSO token channel.
- `odigos/api/deps.py:26-65` — route classification / default-deny support.
- `odigos/api/platform_auth.py:55,67` — email normalization.
- `odigos/api/rate_limit.py:54-55` — WebSocket upgrade limiting.
- `odigos/api/callbacks.py` — HMAC signature.
- `odigos/api/webauthn.py:339` + migration — credential `user_id`.
- `odigos/bootstrap.py` — `api_key` to `.env`; hosted startup gate; `startup_security_report`.
- `config.yaml.example` — document new keys.

---

# PHASE 1 — Deployment mode + sandbox fail-closed (C1)

### Task 1: Add `deployment.mode` and `sandbox.require_isolation` config

**Files:**
- Modify: `odigos/config.py` (add config models + fields; flip `sso_auto_provision`)
- Test: `tests/test_security_config.py` (create)

- [ ] **Step 1: Read the current config models.** Open `odigos/config.py`. Find the existing pydantic settings models (e.g. `DatabaseConfig` near line 44, the top-level `Settings`, and `sso_auto_provision` at line 316). Match their style (pydantic `BaseModel`/`BaseSettings`, snake_case, defaults).

- [ ] **Step 2: Write the failing test.**

```python
# tests/test_security_config.py
from tests.conftest import make_test_settings


def test_deployment_mode_defaults_to_dev():
    s = make_test_settings()
    assert s.deployment.mode == "dev"


def test_sandbox_requires_isolation_by_default():
    s = make_test_settings()
    assert s.sandbox.require_isolation is True


def test_sso_auto_provision_defaults_false():
    s = make_test_settings()
    assert s.sso_auto_provision is False


def test_hosted_mode_is_accepted():
    s = make_test_settings(deployment={"mode": "hosted"})
    assert s.deployment.mode == "hosted"
```

- [ ] **Step 3: Run the test — expect failure.** `.venv/bin/python -m pytest tests/test_security_config.py -p no:cacheprovider -q` → FAIL (`deployment`/`sandbox` attrs missing or `sso_auto_provision` True).

- [ ] **Step 4: Implement.** In `odigos/config.py` add:

```python
class DeploymentConfig(BaseModel):
    mode: str = "dev"  # "dev" | "hosted"


class SandboxConfig(BaseModel):
    require_isolation: bool = True
    timeout: int = 5
    max_memory_mb: int = 512
    max_output_chars: int = 4000
```

Add fields to the top-level `Settings` model (match how other nested configs are declared):

```python
    deployment: DeploymentConfig = DeploymentConfig()
    sandbox: SandboxConfig = SandboxConfig()
```

If a `sandbox` config already exists, extend it with `require_isolation` rather than creating a duplicate. Change line ~316:

```python
    sso_auto_provision: bool = False  # SSO with unknown email must NOT auto-create users by default
```

- [ ] **Step 5: Run the test — expect pass.** Same command → PASS.

- [ ] **Step 6: Update `config.yaml.example`.** Add a documented block:

```yaml
deployment:
  mode: dev          # set to "hosted" in production: forces sandbox isolation, SSRF/CSRF on, rejects insecure overrides
sandbox:
  require_isolation: true   # only bubblewrap-isolated execution is allowed; code tools disabled otherwise
```

- [ ] **Step 7: Commit.** `git add odigos/config.py tests/test_security_config.py config.yaml.example && git commit -m "feat(security): deployment.mode + sandbox.require_isolation config; default sso_auto_provision off"`

---

### Task 2: SandboxProvider fails closed without bubblewrap

**Files:**
- Modify: `odigos/providers/sandbox.py` (constructor + `execute`)
- Test: `tests/test_sandbox_fail_closed.py` (create)

**Context:** `SandboxProvider.__init__` (lines 34-46) takes `timeout/max_memory_mb/allow_network/max_output_chars` and sets class-level `_isolation` via `_detect_isolation()` returning `"bwrap"|"unshare"|"ulimit"`. `execute()` (line 96) runs code. We add a `require_isolation` flag; when true and the effective tier is not `bwrap`, `execute()` returns a disabled result WITHOUT spawning a subprocess.

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_sandbox_fail_closed.py
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
    # With require_isolation False, the ulimit path runs (dev fallback). We only
    # assert it does NOT short-circuit to the disabled error.
    res = await sb.execute("print('hi')", language="python")
    assert "isolation (bubblewrap) is required" not in res.stderr
```

- [ ] **Step 2: Run — expect failure.** `.venv/bin/python -m pytest tests/test_sandbox_fail_closed.py -p no:cacheprovider -q` → FAIL (`require_isolation` kwarg unknown).

- [ ] **Step 3: Implement.** In `odigos/providers/sandbox.py`:

Add to `__init__` signature and body:

```python
    def __init__(
        self,
        timeout: int = 5,
        max_memory_mb: int = 512,
        allow_network: bool = False,
        max_output_chars: int = 4000,
        require_isolation: bool = True,
    ) -> None:
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.allow_network = allow_network
        self.max_output_chars = max_output_chars
        self.require_isolation = require_isolation
        if SandboxProvider._isolation is None:
            SandboxProvider._isolation = self._detect_isolation()
```

At the top of `execute()` (after the language check, before the `tempfile.TemporaryDirectory` block):

```python
        if self.require_isolation and SandboxProvider._isolation != "bwrap":
            return SandboxResult(
                stdout="",
                stderr=(
                    "Code execution disabled: filesystem isolation (bubblewrap) "
                    "is required but unavailable."
                ),
                exit_code=-1,
                timed_out=False,
            )
```

- [ ] **Step 4: Run — expect pass.** Same command → PASS.

- [ ] **Step 5: Wire config → provider.** Find where `SandboxProvider` is constructed (search: `SandboxProvider(`; likely `odigos/providers/__init__.py` or `bootstrap.py`/container). Pass `require_isolation=settings.sandbox.require_isolation`, and in hosted mode force True:

```python
require_isolation = settings.sandbox.require_isolation or settings.deployment.mode == "hosted"
```

- [ ] **Step 6: Run full sandbox tests.** `.venv/bin/python -m pytest tests/ -k sandbox -p no:cacheprovider -q` → PASS.

- [ ] **Step 7: Commit.** `git add odigos/providers/sandbox.py tests/test_sandbox_fail_closed.py && git commit -m "feat(sandbox): fail closed when bubblewrap isolation is unavailable"`

---

### Task 3: Pin the bubblewrap profile (deny-by-default, minimal /dev, /usr/local check)

**Files:**
- Modify: `odigos/providers/sandbox.py` `_wrap_isolation` (lines 172-219) and `_detect_isolation` probe (lines 56-65)
- Test: `tests/test_sandbox_profile.py` (create)

**Context:** Current `bwrap` branch uses `--dev /dev` (line 191) and ro-binds all of `/usr/local` (line 205). Tighten `/dev` to a minimal set and only bind `/usr/local` when it contains the Python prefix and no obvious secret files.

- [ ] **Step 1: Write the failing test** (asserts the constructed bwrap argv, no subprocess needed):

```python
# tests/test_sandbox_profile.py
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
```

- [ ] **Step 2: Run — expect failure.** `.venv/bin/python -m pytest tests/test_sandbox_profile.py -p no:cacheprovider -q` → second test FAILs (current code uses `--dev /dev`).

- [ ] **Step 3: Implement.** In `_wrap_isolation`, replace `"--dev", "/dev",` (line 191) with a minimal device set:

```python
                "--proc", "/proc",
                "--dev-bind", "/dev/null", "/dev/null",
                "--dev-bind", "/dev/zero", "/dev/zero",
                "--dev-bind", "/dev/urandom", "/dev/urandom",
                "--tmpfs", "/tmp",
```

Guard the `/usr/local` bind (lines 201-205) so it is skipped if it holds secrets:

```python
            if shutil.which("python3"):
                import sys
                prefix = sys.prefix
                if prefix.startswith("/usr/local") and not _usr_local_has_secrets():
                    bwrap.extend(["--ro-bind", "/usr/local", "/usr/local"])
```

Add module-level helper:

```python
def _usr_local_has_secrets() -> bool:
    """Best-effort guard: refuse to mount /usr/local if it holds obvious secrets."""
    import os
    suspicious = (".env", "config.yaml", "credentials", "id_rsa", ".pem")
    try:
        for root, _dirs, files in os.walk("/usr/local"):
            depth = root[len("/usr/local"):].count(os.sep)
            if depth > 3:
                continue
            for f in files:
                if any(s in f for s in suspicious):
                    return True
    except OSError:
        return True
    return False
```

Apply the same minimal `--dev` change to the `_detect_isolation` probe (line 62) so the probe matches the real profile.

- [ ] **Step 4: Run — expect pass.** Same command → PASS.

- [ ] **Step 5: Commit.** `git add odigos/providers/sandbox.py tests/test_sandbox_profile.py && git commit -m "harden(sandbox): minimal /dev, guard /usr/local bind, deny-by-default profile"`

---

### Task 4: Sandbox escape + resource tests (bwrap-gated)

**Files:**
- Test: `tests/test_sandbox_escape.py` (create)

**Context:** These run real code under bwrap; skip cleanly where bwrap is absent so the default suite stays green, but they MUST run on the hosted CI image.

- [ ] **Step 1: Write the tests.**

```python
# tests/test_sandbox_escape.py
import shutil
import pytest
from odigos.providers.sandbox import SandboxProvider

pytestmark = pytest.mark.skipif(
    shutil.which("bwrap") is None, reason="bubblewrap not installed"
)


@pytest.fixture(autouse=True)
def _force_bwrap(monkeypatch):
    monkeypatch.setattr(SandboxProvider, "_isolation", "bwrap")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/etc/passwd", "/opt", "/root", "/home",
])
async def test_cannot_read_host_paths(path):
    sb = SandboxProvider(require_isolation=True, timeout=5)
    code = f"import os; print(os.path.exists({path!r}) and open({path!r}).read()[:10])"
    res = await sb.execute(code, language="python")
    # The path must be invisible (FileNotFoundError) or unreadable.
    assert "root:" not in res.stdout
    assert "PRIVATE KEY" not in res.stdout


@pytest.mark.asyncio
async def test_grandchild_killed_on_timeout():
    sb = SandboxProvider(require_isolation=True, timeout=2)
    code = (
        "import os,time\n"
        "if os.fork()==0:\n"
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
        "    socket.create_connection(('1.1.1.1',53),timeout=2); print('NET-OK')\n"
        "except Exception as e: print('NET-BLOCKED')\n"
    )
    res = await sb.execute(code, language="python")
    assert "NET-BLOCKED" in res.stdout
```

- [ ] **Step 2: Run.** On a dev machine without bwrap: `.venv/bin/python -m pytest tests/test_sandbox_escape.py -p no:cacheprovider -q` → all SKIPPED (expected). On the bwrap CI image → PASS. Mark the file with `@pytest.mark.slow` if the suite policy requires; document in the test that hosted CI must run it.

- [ ] **Step 3: Commit.** `git add tests/test_sandbox_escape.py && git commit -m "test(sandbox): escape, grandchild-kill, network-block acceptance tests (bwrap-gated)"`

---

### Task 5: CodeTool surfaces the disabled error clearly

**Files:**
- Modify: `odigos/tools/code.py`
- Test: `tests/test_code_tool_disabled.py` (create)

- [ ] **Step 1: Read `odigos/tools/code.py`.** Find where it calls `sandbox.execute(...)` (the result has `exit_code`/`stderr`). Identify how it maps a `SandboxResult` to a `ToolResult`.

- [ ] **Step 2: Write the failing test.**

```python
# tests/test_code_tool_disabled.py
import pytest
from odigos.providers.sandbox import SandboxResult


class _DisabledSandbox:
    async def execute(self, code, language="python", pre_files=None):
        return SandboxResult(stdout="", stderr="Code execution disabled: filesystem isolation (bubblewrap) is required but unavailable.", exit_code=-1, timed_out=False)


@pytest.mark.asyncio
async def test_code_tool_reports_disabled_clearly():
    from odigos.tools.code import CodeTool
    tool = CodeTool(sandbox=_DisabledSandbox())
    res = await tool.execute({"code": "print(1)", "language": "python"})
    assert res.success is False
    assert "disabled" in (res.error or "").lower()
```

(Adjust `CodeTool(...)` construction to match the real constructor after reading the file.)

- [ ] **Step 3: Run — expect failure / adjust.** Run and fix the test to the real constructor signature; then it should FAIL on the assertion if the tool currently treats `exit_code=-1` as a generic error without surfacing "disabled".

- [ ] **Step 4: Implement.** In `code.py`, when `result.exit_code == -1` and "disabled" in `result.stderr`, return `ToolResult(success=False, data="", error=result.stderr)` (non-retryable message). Do not retry.

- [ ] **Step 5: Run — expect pass.**

- [ ] **Step 6: Commit.** `git add odigos/tools/code.py tests/test_code_tool_disabled.py && git commit -m "feat(code): surface sandbox-disabled as a clear non-retryable tool error"`

---

### Task 6: Hosted startup gate + `startup_security_report`

**Files:**
- Modify: `odigos/bootstrap.py`
- Test: `tests/test_hosted_startup_gate.py` (create)

**Context:** In hosted mode, startup must hard-fail if `ODIGOS_SANDBOX_ALLOW_INSECURE` is set or bubblewrap is absent, and log the resolved security posture.

- [ ] **Step 1: Read `odigos/bootstrap.py`** around `run()` / the init sequence and the existing `validate_skill_tools()` call site (added in a prior session). Pick the same call site stage for a new `_enforce_hosted_security(settings)` call.

- [ ] **Step 2: Write the failing test.**

```python
# tests/test_hosted_startup_gate.py
import pytest
from odigos.bootstrap import _enforce_hosted_security
from tests.conftest import make_test_settings


def test_hosted_rejects_insecure_override(monkeypatch):
    monkeypatch.setenv("ODIGOS_SANDBOX_ALLOW_INSECURE", "1")
    s = make_test_settings(deployment={"mode": "hosted"})
    with pytest.raises(RuntimeError, match="ODIGOS_SANDBOX_ALLOW_INSECURE"):
        _enforce_hosted_security(s, bwrap_present=True)


def test_hosted_requires_bwrap():
    s = make_test_settings(deployment={"mode": "hosted"})
    with pytest.raises(RuntimeError, match="bubblewrap"):
        _enforce_hosted_security(s, bwrap_present=False)


def test_dev_mode_permits_everything(monkeypatch):
    monkeypatch.setenv("ODIGOS_SANDBOX_ALLOW_INSECURE", "1")
    s = make_test_settings(deployment={"mode": "dev"})
    _enforce_hosted_security(s, bwrap_present=False)  # no raise
```

- [ ] **Step 3: Run — expect failure.** `.venv/bin/python -m pytest tests/test_hosted_startup_gate.py -p no:cacheprovider -q` → FAIL (function missing).

- [ ] **Step 4: Implement** in `odigos/bootstrap.py`:

```python
import os
import shutil
import logging as _logging

_log = _logging.getLogger(__name__)


def _enforce_hosted_security(settings, bwrap_present: bool | None = None) -> None:
    """In hosted mode, refuse insecure dev overrides and require bubblewrap."""
    if settings.deployment.mode != "hosted":
        return
    if os.environ.get("ODIGOS_SANDBOX_ALLOW_INSECURE"):
        raise RuntimeError(
            "ODIGOS_SANDBOX_ALLOW_INSECURE is set but deployment.mode=hosted; refusing to start."
        )
    present = shutil.which("bwrap") is not None if bwrap_present is None else bwrap_present
    if not present:
        raise RuntimeError(
            "deployment.mode=hosted requires bubblewrap (bwrap) for sandbox isolation; refusing to start."
        )


def startup_security_report(settings) -> None:
    from odigos.providers.sandbox import SandboxProvider
    SandboxProvider()  # ensure tier detected
    _log.info(
        "security posture: mode=%s isolation=%s require_isolation=%s sso_auto_provision=%s",
        settings.deployment.mode,
        SandboxProvider._isolation,
        settings.sandbox.require_isolation,
        settings.sso_auto_provision,
    )
```

Call `_enforce_hosted_security(self.settings)` and `startup_security_report(self.settings)` at the chosen init stage.

- [ ] **Step 5: Run — expect pass.**

- [ ] **Step 6: Commit.** `git add odigos/bootstrap.py tests/test_hosted_startup_gate.py && git commit -m "feat(bootstrap): hosted-mode security gate + startup security report"`

---

# PHASE 2 — SSRF

### Task 7: `url_guard` module

**Files:**
- Create: `odigos/tools/url_guard.py`
- Test: `tests/test_url_guard.py` (create)

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_url_guard.py
import pytest
from odigos.tools import url_guard


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost/", "http://10.0.0.1/",
    "http://172.16.0.1/", "http://192.168.1.1/", "http://169.254.169.254/",
    "http://0.0.0.0/", "http://[::1]/", "http://[fe80::1]/", "http://[fc00::1]/",
    "http://2130706433/",          # decimal 127.0.0.1
    "http://0x7f000001/",          # hex 127.0.0.1
    "http://0177.0.0.1/",          # octal
    "http://user@127.0.0.1/",      # userinfo
    "http://127.0.0.1.:8002/",     # trailing dot
    "HTTP://127.0.0.1/",           # mixed-case scheme
    "file:///etc/passwd", "gopher://127.0.0.1/", "data:text/plain,hi",
    "http://localhost:5432/", "http://localhost:2019/config",
    "http://127.0.0.1:8002/",
])
def test_blocks_internal_and_bad_schemes(url):
    assert url_guard.is_blocked_url(url) is True


@pytest.mark.parametrize("url", ["https://example.com/", "http://93.184.216.34/"])
def test_allows_public(url, monkeypatch):
    # 93.184.216.34 is a literal public IP; example.com may resolve at runtime.
    assert url_guard.is_blocked_url("http://93.184.216.34/") is False


def test_fails_closed_on_dns_error(monkeypatch):
    def _boom(*a, **k):
        import socket
        raise socket.gaierror("nope")
    monkeypatch.setattr("socket.getaddrinfo", _boom)
    assert url_guard.is_blocked_url("http://does-not-resolve.invalid/") is True
```

- [ ] **Step 2: Run — expect failure.** `.venv/bin/python -m pytest tests/test_url_guard.py -p no:cacheprovider -q` → FAIL (module missing).

- [ ] **Step 3: Implement `odigos/tools/url_guard.py`.**

```python
"""SSRF guard shared by all URL-fetching tools.

Blocks private/loopback/link-local/reserved/multicast targets, bad schemes,
numeric-IP-literal encodings, userinfo tricks, and fails CLOSED on resolution
errors. Redirect re-validation and connect-to-resolved-IP are applied by the
callers that control their fetcher.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = {"http", "https"}


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _normalize_host(host: str) -> str:
    host = host.strip().rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        pass
    return host


def is_blocked_url(url: str, policy: str | None = None) -> bool:
    """Return True if the URL must NOT be fetched. Fails closed on any error."""
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in _ALLOWED_SCHEMES:
            return True
        host = parts.hostname  # urlsplit strips userinfo; brackets removed for IPv6
        if not host:
            return True
        host = _normalize_host(host)
        # Numeric literal? Check before DNS (covers decimal/hex/octal/IPv6).
        try:
            ipaddress.ip_address(host)
            return _ip_is_blocked(host)
        except ValueError:
            pass
        # Hostname: resolve all records, block if ANY is internal.
        infos = socket.getaddrinfo(host, parts.port or 0, proto=socket.IPPROTO_TCP)
        if not infos:
            return True
        for info in infos:
            if _ip_is_blocked(info[4][0]):
                return True
        return False
    except (socket.gaierror, ValueError, UnicodeError, OSError):
        return True  # fail closed
```

Note: `urlsplit("http://0177.0.0.1/").hostname` returns `"0177.0.0.1"`; `ipaddress.ip_address` raises ValueError for octal-with-leading-zero, so it falls to DNS — on Linux `getaddrinfo("0177.0.0.1")` resolves to `127.0.0.1` and is blocked there. Verify the octal case passes; if a platform leaves it unresolved, the fail-closed `gaierror` branch blocks it anyway.

- [ ] **Step 4: Run — expect pass.** Same command → PASS. If the public-IP case is flaky offline, keep only the literal-IP assertion (already done).

- [ ] **Step 5: Commit.** `git add odigos/tools/url_guard.py tests/test_url_guard.py && git commit -m "feat(security): shared SSRF url_guard (fail-closed, all IP encodings)"`

---

### Task 8: `read_page` uses `url_guard` + redirect re-validation

**Files:**
- Modify: `odigos/tools/scrape.py` (remove local `_is_private_url`, lines 18-30; call `url_guard` at line 57)
- Test: `tests/test_scrape_ssrf.py` (create)

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_scrape_ssrf.py
import pytest


class _Scraper:
    async def scrape(self, url, tier="standard"):
        raise AssertionError("must not scrape a blocked URL")


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://127.0.0.1:8002/", "http://169.254.169.254/", "http://localhost:2019/config"])
async def test_read_page_blocks_internal(url):
    from odigos.tools.scrape import ScrapeTool
    res = await ScrapeTool(scraper=_Scraper()).execute({"url": url})
    assert res.success is False
    assert "private" in (res.error or "").lower() or "internal" in (res.error or "").lower()
```

- [ ] **Step 2: Run — expect pass-or-fail.** It already blocks loopback today via `_is_private_url`, but `127.0.0.1:8002` and `localhost:2019` should already pass; the new value to verify is consistency. Run: `.venv/bin/python -m pytest tests/test_scrape_ssrf.py -p no:cacheprovider -q`.

- [ ] **Step 3: Implement.** Delete `_is_private_url` (lines 18-30). Add `from odigos.tools.url_guard import is_blocked_url`. Replace line 57:

```python
        if is_blocked_url(url):
            return ToolResult(success=False, data="", error="Cannot scrape private or internal URLs")
```

If the scraper has an httpx path we control, set `follow_redirects=True` with a hook that calls `is_blocked_url` on each `response.url`/`Location` and aborts on block (in `odigos/providers/scraper.py`). If redirects aren't controllable (Playwright), add a code comment pointing to the host-firewall backstop (C0 checklist).

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: Commit.** `git add odigos/tools/scrape.py tests/test_scrape_ssrf.py && git commit -m "fix(ssrf): read_page uses shared url_guard"`

---

### Task 9: `process_document` guards the URL branch

**Files:**
- Modify: `odigos/tools/document.py:65-76`
- Test: `tests/test_document_ssrf.py` (create)

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_document_ssrf.py
import pytest


class _MD:
    def convert_url(self, url):
        raise AssertionError("must not fetch a blocked URL")
    def convert_file(self, path):
        return "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.1/"])
async def test_process_document_blocks_internal_urls(url):
    from odigos.tools.document import DocTool  # adjust class name after reading file
    tool = DocTool(markitdown=_MD())
    res = await tool.execute({"source": url})
    assert res.success is False
```

(After reading `document.py`, fix the class name and constructor.)

- [ ] **Step 2: Run — expect failure** (URL branch fetches today). 

- [ ] **Step 3: Implement.** In `_convert_with_markitdown` (line 70), before `convert_url`:

```python
            if source.startswith(("http://", "https://")):
                from odigos.tools.url_guard import is_blocked_url
                if is_blocked_url(source):
                    return ToolResult(success=False, data="", error="Cannot fetch private or internal URLs")
                content = await asyncio.to_thread(self.markitdown.convert_url, source)
```

Add a comment: MarkItDown follows redirects internally; host egress firewall (C0) is the backstop.

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: Commit.** `git add odigos/tools/document.py tests/test_document_ssrf.py && git commit -m "fix(ssrf): guard process_document URL branch"`

---

### Task 10: `run_browser` URL-arg guard + hosted no-internet default

**Files:**
- Modify: `odigos/tools/browser.py` (add `execute` override)
- Test: `tests/test_browser_ssrf.py` (create)

**Context:** `BrowserTool` extends `SubprocessTool` and does not override `execute`. Add an override that parses the command, validates URL-bearing tokens via `url_guard`, then delegates to `super().execute`.

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_browser_ssrf.py
import pytest
from odigos.tools.browser import BrowserTool


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", [
    "navigate --url http://localhost:2019/config",
    "navigate --url http://127.0.0.1:8002/",
    "navigate --url file:///etc/passwd",
])
async def test_browser_blocks_internal_urls(cmd):
    res = await BrowserTool().execute({"command": cmd})
    assert res.success is False
    assert "url" in (res.error or "").lower() or "private" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_browser_blocks_malformed_command():
    res = await BrowserTool().execute({"command": 'navigate --url "unterminated'})
    assert res.success is False
```

- [ ] **Step 2: Run — expect failure.**

- [ ] **Step 3: Implement** in `odigos/tools/browser.py`:

```python
import shlex
from odigos.tools.base import ToolResult
from odigos.tools.url_guard import is_blocked_url


class BrowserTool(SubprocessTool):
    # ... existing class body ...

    async def execute(self, params: dict) -> ToolResult:
        command = (params.get("command") or "").strip()
        try:
            args = shlex.split(command)
        except ValueError as exc:
            return ToolResult(success=False, data="", error=f"Invalid command syntax: {exc}")
        for i, tok in enumerate(args):
            candidate = None
            if tok in ("--url", "-u") and i + 1 < len(args):
                candidate = args[i + 1]
            elif tok.startswith("--url="):
                candidate = tok.split("=", 1)[1]
            elif "://" in tok:
                candidate = tok
            if candidate and is_blocked_url(candidate):
                return ToolResult(success=False, data="", error=f"Blocked URL (private/internal): {candidate}")
        return await super().execute(params)
```

(Hosted no-internet allowlist default is wired via config in Task 11's shared policy follow-up if desired; the block-internal guard above is the launch-critical part.)

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: Commit.** `git add odigos/tools/browser.py tests/test_browser_ssrf.py && git commit -m "fix(ssrf): validate URL-bearing browser args, fail closed on bad syntax"`

---

### Task 11: `arg_guard` + `web_platform` sanitization

**Files:**
- Create: `odigos/tools/arg_guard.py`
- Modify: `odigos/tools/opencli.py:69`; refactor `odigos/tools/subprocess_tool.py:11,72-77` to use it
- Test: `tests/test_arg_guard.py`, `tests/test_opencli_args.py` (create)

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_arg_guard.py
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


def test_option_args_rejected_only_when_requested():
    reject_dangerous_args(["search", "foo"])           # ok
    reject_dangerous_args(["search", "--limit", "5"])  # ok by default
    with pytest.raises(ArgGuardError):
        reject_dangerous_args(["--force"], reject_option_args=True)
```

```python
# tests/test_opencli_args.py
import pytest
from odigos.tools.opencli import WebPlatformTool  # adjust to real class name


@pytest.mark.asyncio
async def test_opencli_blocks_config_flag(monkeypatch):
    tool = WebPlatformTool()
    res = await tool.execute({"platform": "x", "command": "search --config /etc/passwd"})
    assert res.success is False
```

(After reading `opencli.py`, set the real class name and ensure `platform` `"x"` passes the `PLATFORMS` check or use a valid platform; if `PLATFORMS` gates first, use a valid platform name and rely on the arg-guard rejection.)

- [ ] **Step 2: Run — expect failure.**

- [ ] **Step 3: Implement `odigos/tools/arg_guard.py`.**

```python
"""Shared dangerous-argument guard for subprocess tools."""
from __future__ import annotations

_DANGEROUS_SUBSTR = ("../", "..\\", "\x00", "\r", "\n", "`", "$(")
_DANGEROUS_FLAGS = ("--output", "-o", "--config")


class ArgGuardError(ValueError):
    pass


def reject_dangerous_args(args: list[str], *, reject_option_args: bool = False) -> None:
    for a in args:
        if any(s in a for s in _DANGEROUS_SUBSTR):
            raise ArgGuardError(f"Blocked dangerous argument: {a!r}")
        if a in _DANGEROUS_FLAGS or a.startswith("--config="):
            raise ArgGuardError(f"Blocked option: {a!r}")
        if reject_option_args and (a.startswith("-") or a.startswith("/")):
            raise ArgGuardError(f"Blocked option-style/absolute arg: {a!r}")
```

In `opencli.py`, replace line 69:

```python
        import shlex
        from odigos.tools.arg_guard import reject_dangerous_args, ArgGuardError
        try:
            args = shlex.split(command)
        except ValueError as exc:
            return ToolResult(success=False, data="", error=f"Invalid command syntax: {exc}")
        try:
            reject_dangerous_args(args)
        except ArgGuardError as exc:
            return ToolResult(success=False, data="", error=str(exc))
```

Refactor `subprocess_tool.py` to import and call `reject_dangerous_args` instead of the inline `_DANGEROUS_PATTERNS` loop (keep behavior; this DRYs the two). Keep `_DANGEROUS_PATTERNS` removal minimal — confirm `--output` json usage in CLITool (Task 24) isn't broken; SubprocessTool passes raw subcommands so `--output` should remain blocked there.

- [ ] **Step 4: Run — expect pass** (both test files + `tests/ -k subprocess`).

- [ ] **Step 5: Commit.** `git add odigos/tools/arg_guard.py odigos/tools/opencli.py odigos/tools/subprocess_tool.py tests/test_arg_guard.py tests/test_opencli_args.py && git commit -m "fix(injection): shared arg_guard; sanitize web_platform args"`

---

# PHASE 3 — Auth / CSRF

### Task 12: SSO auto-provision off by default (verify wiring)

Already flipped the default in Task 1. This task adds the behavioral test.

**Files:** Test: `tests/test_sso_no_autoprovision.py` (create)

- [ ] **Step 1: Write the test.** Boot a minimal app or call `auth_sso` logic with `sso_auto_provision=False` and an unknown email → expect HTTP 403 and no `users` row inserted. Use the existing auth test harness pattern (search `tests/` for an existing auth/SSO test to copy DB+settings setup). Assert `db` has no new user.

- [ ] **Step 2: Run — expect pass** (default is now False). If a prior test assumed auto-provision True, update it to set `sso_auto_provision=True` explicitly.

- [ ] **Step 3: Commit.** `git add tests/test_sso_no_autoprovision.py && git commit -m "test(auth): SSO does not auto-provision unknown emails by default"`

---

### Task 13: CSRF on `delete_fact` + `update_profile`

**Files:**
- Modify: `odigos/api/auth.py:454, 476`
- Test: `tests/test_auth_csrf.py` (create or extend)

- [ ] **Step 1: Write the failing test.** Using the app/test client, call `DELETE /api/auth/facts/x` and `PUT /api/auth/profile` with a valid session cookie but WITHOUT `X-Requested-With` → expect 403. (Copy session-cookie setup from an existing auth test.)

- [ ] **Step 2: Run — expect failure** (currently 200/ok).

- [ ] **Step 3: Implement.** Add `_check_csrf(request)` as the first line of both `delete_fact` (after the docstring) and `update_profile`:

```python
async def delete_fact(fact_id: str, request: Request, db=Depends(get_db), settings=Depends(get_settings)):
    """Delete a user fact by ID (session required)."""
    _check_csrf(request)
    ...
```

```python
async def update_profile(body: ProfileUpdate, request: Request, db=Depends(get_db), settings=Depends(get_settings)):
    """Update the owner's learned profile fields (session required)."""
    _check_csrf(request)
    ...
```

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: Commit.** `git add odigos/api/auth.py tests/test_auth_csrf.py && git commit -m "fix(csrf): enforce CSRF on delete_fact and update_profile"`

---

### Task 14: Secure cookie via `X-Forwarded-Proto` + full attribute set

**Files:**
- Modify: `odigos/api/auth.py:97-107`; mirror in `odigos/api/platform_auth.py` set_cookie sites
- Test: `tests/test_cookie_attrs.py` (create)

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_cookie_attrs.py
from unittest.mock import MagicMock
from fastapi import Response
from odigos.api import auth


def _req(scheme="http", xfp=None):
    r = MagicMock()
    r.url.scheme = scheme
    r.headers = {"x-forwarded-proto": xfp} if xfp else {}
    return r


def test_secure_from_forwarded_proto():
    resp = Response()
    auth._set_session_cookie(resp, _req(scheme="http", xfp="https"), "tok")
    cookie = resp.headers.get("set-cookie", "")
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie or "samesite=lax" in cookie.lower()
```

- [ ] **Step 2: Run — expect failure** (no `Secure` when scheme is http).

- [ ] **Step 3: Implement.** Replace `_set_session_cookie` (lines 97-107):

```python
def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    """Set the session cookie. Honors X-Forwarded-Proto behind a TLS proxy."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    secure = proto == "https"
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=_SESSION_MAX_AGE,
    )
```

Check `platform_auth.py` set_cookie sites (line ~85) and apply the same forwarded-proto derivation.

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: Commit.** `git add odigos/api/auth.py odigos/api/platform_auth.py tests/test_cookie_attrs.py && git commit -m "fix(auth): derive Secure cookie from X-Forwarded-Proto; pin cookie attributes"`

---

### Task 15: Session revocation via per-user `session_epoch`

**Files:**
- Modify: `odigos/api/auth.py` (`_create_session`/`_validate_session` callers, logout, change-password, reset-password); migration for `users.session_epoch`
- Test: `tests/test_session_epoch.py` (create)

**Context:** `_create_session`/`_validate_session` are generic (payload in/out). Embed `epoch` in the payload and compare against the user's current `session_epoch` on validation in the endpoints that load the user. Bump epoch on logout, change-password, reset-password.

- [ ] **Step 1: Add migration.** Create `migrations/014_session_epoch.sql`:

```sql
ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0;
```

(Confirm the migration runner picks up numbered files; the repo uses `migrations/0NN_*.sql` and an auto-ALTER pattern — match `013_tool_costs.sql`.)

- [ ] **Step 2: Write the failing test.** Create a user, mint a session embedding `epoch=0`, bump `session_epoch` to 1 in the DB, then assert a request using the old cookie is rejected (401). Use the auth test harness.

- [ ] **Step 3: Run — expect failure.**

- [ ] **Step 4: Implement.** Add a helper that validates session AND epoch:

```python
async def _validate_session_with_epoch(secret, token, db) -> dict | None:
    session = _validate_session(secret, token)
    if not session:
        return None
    row = await db.fetch_one("SELECT session_epoch FROM users WHERE id = ?", (session["user_id"],))
    if not row or session.get("epoch", 0) != row["session_epoch"]:
        return None
    return session
```

Include `"epoch"` in every `_create_session(...)` payload (read the user's current `session_epoch` when minting at login/setup/sso/change-password). Replace the inline `_validate_session(...)` calls in `auth_me`, `get_facts`, `delete_fact`, `update_profile`, `change_password` with `_validate_session_with_epoch(...)`. On logout/change-password/reset-password, `UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?` (logout needs the user id — read it from the cookie session before bumping).

- [ ] **Step 5: Run — expect pass.** Then run full auth tests: `.venv/bin/python -m pytest tests/ -k "auth or session" -p no:cacheprovider -q`.

- [ ] **Step 6: Commit.** `git add migrations/014_session_epoch.sql odigos/api/auth.py tests/test_session_epoch.py && git commit -m "feat(auth): session revocation via per-user session_epoch"`

---

### Task 16: Normalize email in `platform_auth.py`

**Files:**
- Modify: `odigos/api/platform_auth.py:55, 67`
- Test: `tests/test_platform_auth_email.py` (create)

- [ ] **Step 1: Read `platform_auth.py`** lines 40-90 for exact context.

- [ ] **Step 2: Write the failing test.** Insert a user with `email='user@example.com'`; simulate the callback with `email='User@Example.com'`; assert it matches the existing row (no duplicate insert).

- [ ] **Step 3: Run — expect failure.**

- [ ] **Step 4: Implement.** Lowercase email before the lookup (line 55) and before insert (line 67); derive username from the local-part like `auth.py:254` does rather than using the raw email.

- [ ] **Step 5: Run — expect pass.**

- [ ] **Step 6: Commit.** `git add odigos/api/platform_auth.py tests/test_platform_auth_email.py && git commit -m "fix(auth): normalize email + derive username in platform callback"`

---

### Task 17: Route-inventory test (default-deny classification)

**Files:**
- Test: `tests/test_route_auth_inventory.py` (create)
- Possibly modify routers to add missing `require_auth`/classification.

**Context:** Walk the FastAPI app's routes; every mutating route (POST/PUT/PATCH/DELETE) must either be in an explicit PUBLIC allowlist or carry an auth dependency. Fail on any unclassified mutating route. This is a guard against future drift, so it may surface currently-unprotected routes — fix or explicitly allowlist each.

- [ ] **Step 1: Write the test.**

```python
# tests/test_route_auth_inventory.py
import pytest

# Routes intentionally public (no auth). Keep this list small + reviewed.
PUBLIC = {
    ("POST", "/api/auth/setup"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/auth/status"),
    ("GET", "/api/auth/sso"),
    # health/static added as needed
}


def _build_app():
    # Build the FastAPI app the same way main.py does; reuse a test fixture if present.
    from odigos.api import create_app  # adjust import to the real factory
    return create_app()


def test_all_mutating_routes_are_classified():
    app = _build_app()
    unclassified = []
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        path = getattr(route, "path", "")
        for m in methods & {"POST", "PUT", "PATCH", "DELETE"}:
            if (m, path) in PUBLIC:
                continue
            deps = getattr(getattr(route, "dependant", None), "dependencies", [])
            names = {getattr(d.call, "__name__", "") for d in deps}
            # auth enforced either via route dep or router-level dep
            has_auth = any("require" in n for n in names)
            if not has_auth:
                unclassified.append((m, path))
    assert not unclassified, f"unclassified mutating routes (add auth or PUBLIC): {sorted(unclassified)}"
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_route_auth_inventory.py -p no:cacheprovider -q`. It will list any unprotected mutating route.

- [ ] **Step 3: Triage each finding.** For each listed route: if it should be protected, add `Depends(require_auth)` (or router-level dependency); if genuinely public, add to `PUBLIC` with a comment. Do NOT blanket-allowlist. Re-run until green. (The detection of `require` in dependency names may need tuning to how this app declares deps — adjust the introspection to match, e.g. checking `route.dependant.dependencies` recursively or router `dependencies=`.)

- [ ] **Step 4: Commit.** `git add tests/test_route_auth_inventory.py <any routers touched> && git commit -m "test(auth): route-inventory default-deny gate; protect/classify all mutating routes"`

---

### Task 18: SSO token via POST/header (backward-compatible)

**Files:**
- Modify: `odigos/api/auth.py:215-282`
- Test: `tests/test_sso_token_channel.py` (create)

**Context:** The caller is the separate `tamler/odigos-platform` repo. Add a POST endpoint / header acceptance while keeping the legacy `GET ?token=` behind a deprecation flag for rollout. Coordinate the platform-side change separately; this task only makes the agent accept the new channel.

- [ ] **Step 1: Write the failing test.** POST `/api/auth/sso` with the JWT in the body (or `Authorization: Bearer <jwt>`); assert it mints a session (302 + Set-Cookie). Reuse the JWT-mint helper from existing SSO tests.

- [ ] **Step 2: Run — expect failure** (only GET ?token= exists).

- [ ] **Step 3: Implement.** Add:

```python
class SsoTokenRequest(BaseModel):
    token: str = ""


@router.post("/sso")
async def auth_sso_post(body: SsoTokenRequest, request: Request, response: Response, db=Depends(get_db), settings=Depends(get_settings)):
    token = body.token or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(400, "Missing SSO token")
    return await _exchange_sso_token(token, request, db, settings)
```

Refactor the existing GET handler body into `_exchange_sso_token(token, request, db, settings)`; keep the GET handler calling it, gated by a `settings`/env deprecation flag (e.g. `ODIGOS_SSO_ALLOW_QUERY_TOKEN`, default True during rollout, set False after the platform is updated). Log a deprecation warning when the query path is used.

- [ ] **Step 4: Run — expect pass.** Ensure existing GET-based SSO tests still pass.

- [ ] **Step 5: Commit.** `git add odigos/api/auth.py tests/test_sso_token_channel.py && git commit -m "feat(auth): accept SSO token via POST/header; deprecate query-param channel"`

> NOTE for executor: surface to the user that the platform repo must switch to POSTing the token before `ODIGOS_SSO_ALLOW_QUERY_TOKEN` is disabled.

---

### Task 19: Rate-limit WebSocket upgrades

**Files:**
- Modify: `odigos/api/rate_limit.py:54-55`
- Test: `tests/test_ws_rate_limit.py` (create)

- [ ] **Step 1: Read `rate_limit.py`** fully (it's small) to learn the limiter's state structure and per-IP key.

- [ ] **Step 2: Write the failing test.** Drive the middleware with N rapid upgrade requests from one IP; assert request N+1 is throttled (429 or the middleware's reject path). Match the existing rate-limit test style if one exists.

- [ ] **Step 3: Run — expect failure** (upgrades currently bypass at lines 54-55).

- [ ] **Step 4: Implement.** Replace the unconditional `return await call_next(request)` for websocket upgrades with a per-IP connection-rate check (reuse the existing limiter with a separate, looser bucket for upgrades). Keep normal HTTP behavior unchanged.

- [ ] **Step 5: Run — expect pass.**

- [ ] **Step 6: Commit.** `git add odigos/api/rate_limit.py tests/test_ws_rate_limit.py && git commit -m "fix(dos): rate-limit WebSocket upgrade requests"`

---

### Task 20: Validate `audio_process` time args

**Files:**
- Modify: `odigos/tools/audio_process.py:247-250`
- Test: `tests/test_audio_time_args.py` (create)

- [ ] **Step 1: Read `audio_process.py`** around 230-260 for the execute signature and how `start_time`/`end_time` arrive.

- [ ] **Step 2: Write the failing test.** Call the trim path with `start_time="1*0+0"` (or any non-time string) → expect a validation error (success False) before ffmpeg is invoked; valid `"00:01:30"` and `"12.5"` pass validation.

- [ ] **Step 3: Run — expect failure.**

- [ ] **Step 4: Implement.** Add a module-level validator and call it before building args:

```python
import re
_TIME_RE = re.compile(r"^(\d+(\.\d+)?|\d{1,2}:\d{2}(:\d{2})?(\.\d+)?)$")

def _valid_time(v: str) -> bool:
    return bool(_TIME_RE.match(v or ""))
```

Before lines 247-250, reject if a provided value fails `_valid_time`.

- [ ] **Step 5: Run — expect pass.**

- [ ] **Step 6: Commit.** `git add odigos/tools/audio_process.py tests/test_audio_time_args.py && git commit -m "fix(injection): validate audio_process time arguments"`

---

# PHASE 4 — Low / defense-in-depth + ops

### Task 21: WebAuthn credential `user_id`

**Files:**
- Migration: `migrations/015_webauthn_user_id.sql`
- Modify: `odigos/api/webauthn.py` (registration insert ~214, login lookup ~339)
- Test: `tests/test_webauthn_user.py` (create)

- [ ] **Step 1: Read `webauthn.py`** around 200-230 and 330-350.

- [ ] **Step 2: Migration.**

```sql
ALTER TABLE webauthn_credentials ADD COLUMN user_id TEXT;
-- Backfill existing single-user installs to the sole user.
UPDATE webauthn_credentials SET user_id = (SELECT id FROM users LIMIT 1) WHERE user_id IS NULL;
```

- [ ] **Step 3: Write the failing test.** Register a credential for a specific user; assert login via that credential resolves to that user's id (not `LIMIT 1`). With two users, the second user's credential must resolve to the second user.

- [ ] **Step 4: Run — expect failure.**

- [ ] **Step 5: Implement.** Store `user_id` on registration insert; on login (line 339) look up the credential row and use its `user_id` to load the user instead of `SELECT ... FROM users LIMIT 1`.

- [ ] **Step 6: Run — expect pass.**

- [ ] **Step 7: Commit.** `git add migrations/015_webauthn_user_id.sql odigos/api/webauthn.py tests/test_webauthn_user.py && git commit -m "fix(auth): associate WebAuthn credentials with their user"`

---

### Task 22: HMAC-signed task callbacks

**Files:**
- Modify: `odigos/api/callbacks.py`; the code that generates callback URLs (search `task_id` URL construction)
- Test: `tests/test_callback_hmac.py` (create)

- [ ] **Step 1: Read `callbacks.py`** fully and find where callback URLs are produced (grep for the callback path / `task_id` interpolation).

- [ ] **Step 2: Write the failing test.** POST to the callback with a missing/incorrect signature → 403; with a correct HMAC over `task_id` (using `settings.session_secret`) → accepted.

- [ ] **Step 3: Run — expect failure.**

- [ ] **Step 4: Implement.** Add `sig = hmac.new(secret, task_id.encode(), sha256).hexdigest()` to the generated URL as a `sig` query param; in the handler, recompute and `hmac.compare_digest`. Keep the existing 500KB `len(raw)` enforcement.

- [ ] **Step 5: Run — expect pass.**

- [ ] **Step 6: Commit.** `git add odigos/api/callbacks.py <url-generator file> tests/test_callback_hmac.py && git commit -m "fix(auth): HMAC-sign task callback URLs"`

---

### Task 23: Persist generated `api_key` to `.env`, not `config.yaml`

**Files:**
- Modify: `odigos/bootstrap.py` (`_persist_generated_api_key`)
- Test: `tests/test_api_key_persist.py` (create)

- [ ] **Step 1: Read `_persist_generated_api_key`** and the `.env` writer used for `SESSION_SECRET` (the session-secret persist path writes to `.env` already — reuse it).

- [ ] **Step 2: Write the failing test.** With a temp config + env path and no api_key, run the persist step; assert the key lands in `.env` and is NOT written into `config.yaml`.

- [ ] **Step 3: Run — expect failure.**

- [ ] **Step 4: Implement.** Switch `_persist_generated_api_key` to append `ODIGOS_API_KEY=<key>` to `.env` (mirror the SESSION_SECRET writer) and ensure config loading reads the key from env. Confirm `.env` is in `.gitignore` (add if missing).

- [ ] **Step 5: Run — expect pass.**

- [ ] **Step 6: Commit.** `git add odigos/bootstrap.py .gitignore tests/test_api_key_persist.py && git commit -m "fix(secrets): persist generated api_key to .env, not config.yaml"`

---

### Task 24: `reject_option_args` in CLITool (fold into arg_guard)

**Files:**
- Modify: `odigos/tools/cli_tool.py:104-109`
- Test: `tests/test_cli_arg_guard.py` (create)

- [ ] **Step 1: Write the failing test.** `_validate_cli_arg("--force", reject_option_args=True)` raises; default mode leaves current behavior. Also assert `--output` used internally by `run_json` (line 90-91) is NOT broken — `run_json` builds `--output json` itself; ensure `reject_option_args` is OFF for that internal path.

- [ ] **Step 2: Run — expect failure.**

- [ ] **Step 3: Implement.** Extend `_validate_cli_arg` with an optional `reject_option_args=False` param that additionally blocks leading `-`/absolute paths; keep existing checks. Subclasses passing free-text args opt in. Default OFF preserves `run_json`'s internal `--output json`.

- [ ] **Step 4: Run — expect pass.** Then `tests/ -k cli` to confirm Marp/other CLITool tests still pass.

- [ ] **Step 5: Commit.** `git add odigos/tools/cli_tool.py tests/test_cli_arg_guard.py && git commit -m "harden(cli): optional reject_option_args mode"`

---

### Task 25: Login timing oracle (dummy bcrypt)

**Files:**
- Modify: `odigos/api/auth.py:190-195`
- Test: `tests/test_login_timing.py` (create)

- [ ] **Step 1: Write the test.** Patch `_verify_password` to record calls; call login with a non-existent username; assert `_verify_password` was still called (against a dummy hash) — proving the no-user path does bcrypt work.

- [ ] **Step 2: Run — expect failure** (current code short-circuits on `not user`).

- [ ] **Step 3: Implement.** Add a module constant `_DUMMY_HASH = _hash_password("invalid")` (computed once at import). In `auth_login`:

```python
    if not user:
        _verify_password(password, _DUMMY_HASH)  # constant-time-ish; avoid user enumeration
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not _verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
```

- [ ] **Step 4: Run — expect pass.**

- [ ] **Step 5: Commit.** `git add odigos/api/auth.py tests/test_login_timing.py && git commit -m "harden(auth): dummy bcrypt on unknown-user login to reduce enumeration"`

---

### Task 26: Security event logging (redacting, rate-limited)

**Files:**
- Create: `odigos/security/events.py`
- Wire into: sandbox disabled (Task 2), url_guard blocks (Tasks 8-10), CSRF failures (`_check_csrf`), auth denials (`require_auth`)
- Test: `tests/test_security_events.py` (create)

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_security_events.py
from odigos.security.events import log_security_event, _redact


def test_redacts_secrets_and_query():
    assert "token=" not in _redact("https://x/cb?token=abc123")
    assert _redact("Bearer sk-secret") == "Bearer [redacted]"


def test_rate_limited(monkeypatch):
    seen = []
    monkeypatch.setattr("odigos.security.events._emit", lambda kind, msg: seen.append((kind, msg)))
    for _ in range(100):
        log_security_event("ssrf_blocked", "http://127.0.0.1/?token=x")
    assert len(seen) < 100  # rate-limited
```

- [ ] **Step 2: Run — expect failure.**

- [ ] **Step 3: Implement `odigos/security/events.py`** with `_redact(text)` (strip query strings on URLs, replace `Bearer <x>`/`sk-…`/`.env`-like tokens with `[redacted]`), a simple per-kind token-bucket counter, `_emit(kind, msg)` → `logger.warning`, and `log_security_event(kind, detail, **ids)`. Use only stdlib + a module-level dict for counters (no `Date.now`/random concerns — use `time.monotonic`).

- [ ] **Step 4: Wire calls.** At each block/denial site, call `log_security_event(...)` with user/request IDs where available. Keep it best-effort (`try/except` around logging).

- [ ] **Step 5: Run — expect pass.**

- [ ] **Step 6: Commit.** `git add odigos/security/events.py <wired files> tests/test_security_events.py && git commit -m "feat(security): redacting, rate-limited security event log"`

---

## Final verification

- [ ] **Run the full suite gate.** `.venv/bin/python -m pytest -m "not slow and not network" -p no:cacheprovider -q` → all green.
- [ ] **Run ruff.** `.venv/bin/ruff check odigos/ tests/` → clean.
- [ ] **Walk the spec's release-blocker checklist** (`docs/superpowers/specs/2026-05-29-security-hardening-multitenant.md`) and tick each box; the bwrap-gated sandbox escape tests run on the hosted CI image.
- [ ] **Dispatch the final whole-implementation code review** (subagent-driven-development final step).
- [ ] **Surface cross-repo + ops follow-ups to the user:** the platform repo's SSO token POST change (Task 18), and the C0 OS-isolation checklist (`docs/deployment/2026-05-29-os-isolation-checklist.md`).
