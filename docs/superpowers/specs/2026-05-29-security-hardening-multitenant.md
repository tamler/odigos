# Security Hardening for Hosted Launch — Design Spec

> Status: proposed 2026-05-29 (rev 2 — incorporates external review + verified tenancy model)

**Goal:** Close every finding from the whole-system security review so odigos.one can run hosted agents on a shared VPS without RCE, cross-install data exfiltration, SSRF into internal services, CSRF, or auth-bypass exposure.

**Scope decision (user):** Everything in one plan — Critical through Low. Sandbox fails closed when isolation is unavailable.

**"Hosted multi-tenant" here means multi-install, NOT shared-row tenancy.** Each account is its own process + DB + filesystem root. Do not reintroduce per-row `user_id` scoping.

**Master acceptance invariant (the one sentence everything below serves):**
> From Bob's app process, Bob's sandboxed code, and Bob's URL-capable tools, it must be impossible to read Jessica's install files, reach Jessica's local service, reach host-local admin services, or perform state-changing actions without Bob's authenticated browser session and CSRF proof.

This invariant must hold at **four boundaries**: filesystem, network, backup, and process. Cross-install A→B tests at those boundaries are **in scope** (only per-row object scoping is out).

---

## Tenancy model — verified, and what it means for this spec

Verified against `schema.sql` (69 tables, **zero `user_id`/`tenant_id` columns**) and the deploy layout:

- Each account is a **separate OS process** with its **own SQLite DB** (`data/odigos.db`) and **own filesystem root** (`/opt/odigos` for Bob, `/opt/odigos-jessica` for Jessica). Today: **Bob + Jessica only, hand-provisioned** — no open public signups.
- Data within an instance is **instance-global**. The `users` table gates *login* to one agent; it does not scope data. An agent is a personal brain shared by whoever can log into it.
- **Isolation between accounts is therefore the OS/filesystem boundary between installs**, not application-level row scoping.

**Consequences:**
- **OUT OF SCOPE (non-goal):** per-tenant row scoping, horizontal A→B object-access tests, unscoped-row audits, per-tenant cache/vector keys. These assume a shared-app multi-tenant model that does not exist here. Do not add `user_id` scoping to data tables — it is not the isolation mechanism.
- **IN SCOPE and elevated:** the sandbox filesystem boundary (C1) is the primary thing preventing one agent's sandboxed code from reading a *sibling* install's `.env`, config, or DB. The review's "read the sibling install's secrets and assert it fails" tests are adopted as sandbox-escape tests.

**Threat model:** A logged-in user — or a prompt-injected LLM acting on that user's content — controls tool arguments and exercises auth flows. The VPS co-hosts Postgres (127.0.0.1:5432), the sibling agent (port 8002), Caddy admin (localhost:2019), and a sibling install's data dir. Anything reachable from the host is sensitive. "Exploitable-now" = an LLM-controlled argument or unauthenticated request reaches a dangerous sink today.

---

## Deployment security mode (cross-cutting invariant)

Add a single switch `deployment.mode: "dev" | "hosted"` (default `"dev"` in code; production config sets `"hosted"`). `hosted` forcibly enables the secure posture and refuses insecure dev overrides, giving **one invariant to assert at startup and in CI** instead of many drifting knobs.

When `deployment.mode == "hosted"`:
- `sandbox.require_isolation` is forced `true` regardless of config.
- `ODIGOS_SANDBOX_ALLOW_INSECURE` is **rejected**: startup hard-fails if it is set.
- SSRF guard, CSRF checks, and `Secure`-cookie derivation are all on (no opt-out).
- Startup validates bubblewrap is present and the sandbox self-test passes, else hard-fail.

`startup_security_report()` logs the resolved posture (mode, isolation tier, SSRF on/off, CSRF on/off) at boot so the operator sees it.

**Verify:** test that `mode="hosted"` + missing `bwrap` raises at startup; `mode="hosted"` + `ODIGOS_SANDBOX_ALLOW_INSECURE=1` raises; `mode="dev"` permits the fallback.

---

## C0. OS install isolation — the permission contract that makes separate processes real

> **Tracked separately** (user decision): C0 is host-side work executed during the VPS migration, not in-repo code. It lives in `docs/deployment/2026-05-29-os-isolation-checklist.md`. The one in-repo touchpoint — `deploy.sh` mapping each install to a *distinct* service user — is captured there too. This section remains here as the rationale and the source of the cross-install acceptance invariant that the in-repo sandbox tests (C1) still assert.

**Verified gap:** `deploy.sh:34-38` runs `/opt/odigos`, `/opt/odigos-rachel`, `/opt/odigos-honey`, `/opt/odigos-homerun` **all as the same Unix user `odigos_agent`**. Same user ⇒ each install can read every sibling's `.env`, DB, and data dir. The "separate filesystem root" isolation is fiction under a shared user. The sandbox (C1) protects against *sandboxed code*, but a normal app-process bug, a plugin/tool bug, SSRF to a sibling port, a backup job, or loose Unix perms can still cross installs without it.

**Design — per-install permission contract:**
- **Separate Unix user per install.** Bob runs as `odigos_bob`, Jessica as `odigos_jessica`. Never a shared `odigos_agent`. `deploy.sh`'s install table must map each dir to a *distinct* user; the deploy `chown` uses that user.
- **`chmod 700` on each install root and data dir** (`/opt/odigos`, `/opt/odigos/data`, `.env`, `config.yaml`), owned by the install user. No shared writable group. A sibling user gets no read bit.
- **systemd unit hardening** per service (units live on the host; the spec pins the required directives and the plan adds a checked template):
  - `User=odigos_bob` (the dedicated user), `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, `ReadWritePaths=/opt/odigos/data` (only its own data), `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, `RestrictNamespaces=` left permissive enough for bubblewrap to work (bwrap needs user namespaces — verify `bwrap` still functions under the chosen `RestrictNamespaces`/`SystemCallFilter`; do not lock these so tight that the sandbox breaks).
- **Backups (exist via `storage.py`/`data_export.py`):** backup/export artifacts MUST be written under the install's `0700` data dir, owned by the install user — never a world/group-readable shared location. No install user can read another's backups.

**Verify (cross-install, filesystem + process boundary):**
- As `odigos_bob`, attempt to `read` `/opt/odigos-jessica/.env`, `config.yaml`, `data/odigos.db`, and any backup artifact → assert permission denied.
- `deploy.sh` install table asserts distinct users per dir (a test/lint over the array).
- systemd unit conformance: a check (see fleet conformance, Operational) asserts each unit carries the required hardening directives and a distinct `User=`.

---

## CRITICAL

### C1. Sandbox must fail closed without filesystem isolation
**File:** `odigos/providers/sandbox.py`

Today `_detect_isolation()` falls back to `"ulimit"` when bubblewrap is absent (current prod state). The ulimit path (`_wrap_isolation`, lines 172-219) gives **no filesystem and no network isolation** — `allow_network` is silently ignored and user code can read `/opt/odigos/.env`, `config.yaml`, the SQLite DB, SSH keys, and the **sibling install's data dir**. The `unshare` tier isolates network only, not the filesystem, so it is also insufficient for untrusted code.

**Design:**
- Add config `sandbox.require_isolation: bool = True` (default true in code). Precedence: `deployment.mode=hosted` forces true; otherwise config value; `ODIGOS_SANDBOX_ALLOW_INSECURE=1` permits the fallback **only when not hosted**.
- When `require_isolation` is effective and the detected tier is not `bwrap`, `SandboxProvider.execute()` returns `SandboxResult(exit_code=-1, timed_out=False, stderr="Code execution disabled: filesystem isolation (bubblewrap) is required but unavailable.")` and **must not spawn a subprocess**.
- The user-facing tool error (in `CodeTool`) surfaces this as a clear, non-retryable message; the agent should not retry and should treat the tool as unavailable for the turn (do not silently hide it — the user/agent should know code execution is disabled).

**Pin the bubblewrap filesystem policy explicitly — framed as deny-by-default (this is what makes `bwrap` safe).** The acceptance contract is **what must be INVISIBLE**, not just what is bound: inside the sandbox, only explicitly bound paths exist; `/opt` (this and sibling installs), `/home`, `/root`, app `.env`/`config.yaml`, SQLite DBs, SSH keys, backup artifacts, and host temp dirs are **absent** unless explicitly mounted. The profile:
- `--ro-bind /usr /usr`, `--ro-bind /bin /bin`, `--symlink /usr/lib /lib` (+ `/lib64`).
- Python prefix: ro-bind `/usr/local` **only after confirming it contains no app secrets** — on a VPS, `/usr/local` can hold writable pip caches, project checkouts, or host config. If it does, bind only the specific Python `site-packages`/stdlib paths, not all of `/usr/local`.
- `--proc /proc`. **`/dev`: prefer a minimal device set** (`--dev-bind` of only `null`, `zero`, `urandom`, and `tty` if the runtime needs it) rather than `--dev /dev`, unless Python/runtime compatibility forces broader `/dev` — verify which is needed.
- `--tmpfs /tmp`, `--bind <tmpdir> /sandbox`, `--chdir /sandbox` — the per-execution temp dir is the ONLY writable and the only data location.
- `--unshare-all`, `--die-with-parent`, `--new-session`.
- `--unshare-net` whenever `allow_network` is false.
- MUST NOT bind `/app`, `/opt`, `/etc`, `/home`, `/root`, or any data dir.

**Acceptance tests — sandbox escape (deny-by-default):** from sandboxed code, attempt to read each of `/opt/odigos/.env`, `/opt/odigos/config.yaml`, `/opt/odigos/data/odigos.db`, `/opt/odigos-jessica/data/odigos.db` (sibling), `~/.ssh/`, `/etc/passwd`, and a backup artifact path; assert every attempt fails. Plus escape-vector tests: symlink/hardlink out of `/sandbox`, `/proc/self/root`, `/proc/*/cwd`, and inherited file descriptors (assert no fd to host files leaks into the child). (Run where `bwrap` is available; mark-skip otherwise; the hosted CI image must have `bwrap`.)

**Resource-limit / runaway tests:** prove the timeout cleanup kills child **and grandchild** (fork a grandchild that sleeps past parent exit — under `--die-with-parent` + `--new-session` it must not survive; if it does, add `os.killpg`). Add a **fork-bomb test** (assert `ulimit -u`/nproc cap holds and the host stays responsive), and assert CPU, memory (`-v`), process-count, and output-size limits are all enforced.

**Verify:** `execute()` returns the disabled error and spawns no subprocess when `require_isolation` effective and tier≠`bwrap`; runs normally under `bwrap`; the escape, fd-leak, grandchild, and fork-bomb tests above.

---

## HIGH

### Shared SSRF guard — `odigos/tools/url_guard.py` (new)
One implementation used by H1/H2/H3 — no drift. `is_blocked_url(url) -> bool` MUST:
- Require scheme in `{"http","https"}` (case-insensitive); reject `file://`, `gopher://`, `data:`, `ftp://`, etc.
- Reject **userinfo** in the authority (`http://internal@evil/`, `http://[email protected]`).
- Normalize the host: strip a trailing dot, lowercase, IDNA/punycode-decode, then re-check.
- Parse numeric-literal hosts **before DNS** and block private/loopback/link-local/reserved/unspecified: decimal (`http://2130706433`), octal (`http://0177.0.0.1`), hex (`http://0x7f000001`), and IPv6 forms including `[::1]`, `[fc00::/7]`, `[fe80::/10]`, and IPv4-mapped `[::ffff:127.0.0.1]`.
- Resolve DNS (all A/AAAA records) and block if **any** resolved IP is private/loopback/link-local/reserved/unspecified/multicast (include `0.0.0.0` and `[::]`).
- **Fail closed:** return `True` (blocked) on `gaierror`/`ValueError`/any resolution error.

**Algorithm (explicit, not just categories):** parse URL → normalize host → resolve DNS → reject if any resolved IP is in a blocked range → **connect only to the resolved IP** (pass the validated IP to the fetcher / pin it, so the value that was checked is the value that is dialed — this closes the app-layer DNS-rebinding window without relying solely on the firewall) → re-check every redirect hop with the same algorithm.

**Redirects:** application-layer guards are bypassable if the underlying library follows redirects to an internal host. Where we control the fetcher (scrape's httpx path), set `follow_redirects` with a per-hop re-validation hook (validate the `Location` target before following). Where we do **not** control redirects (MarkItDown, agent-browser), document the residual risk and rely on the **host egress firewall** (ops follow-up) as the backstop. The firewall — denying RFC1918 + `169.254.169.254` on the agent's outbound interface — is the real mitigation for both redirect-following and DNS-rebinding; the app guard is the first line.

**Per-tool policy:** `is_blocked_url` takes an optional policy so a tool can be stricter. In `hosted` mode, **browser automation defaults to no outbound internet** unless an allowlist is configured (it rarely needs arbitrary web access); `read_page`/`process_document` keep public-web access. Policy lives in config (`security.ssrf.<tool>`).

**Verify:** parametrized `test_url_guard` across loopback, RFC1918, link-local, reserved, multicast, `0.0.0.0`/`[::]`, decimal/octal/hex IPv4 literals, IPv6 `::1`/ULA/link-local/mapped, userinfo, trailing-dot, mixed-case scheme, custom ports, `file://`, punycode, a public→private **redirect** case, and a DNS-failure case (monkeypatch `getaddrinfo` to raise → blocked). **Explicitly test the real local targets** by hostname and IP form: sibling agent `localhost:8002`/`127.0.0.1:8002`, Postgres `:5432`, Caddy admin `:2019` — all blocked.

### H1. SSRF: `process_document` URL branch unguarded
**File:** `odigos/tools/document.py:65-76`
The local-file branch is containment-checked; the `http(s)://` branch passes the URL straight to `markitdown.convert_url`. Reachable: cloud metadata, Caddy admin, Postgres, sibling agent.
**Fix:** call `is_blocked_url` before `convert_url`; reject with `ToolResult(success=False, error="Cannot fetch private or internal URLs")`. Document the MarkItDown-follows-redirects residual (firewall backstop).
**Verify:** `process_document` with `http://127.0.0.1/`, `http://169.254.169.254/`, `http://10.0.0.1/` rejected with no network call.

### H2. SSRF: `run_browser` URL-bearing args unrestricted
**Files:** `odigos/tools/browser.py`, `odigos/tools/subprocess_tool.py`
`agent-browser` is sent to any URL; `_DANGEROUS_PATTERNS` only blocks `--output`/`../`.
**Fix:** In `BrowserTool.execute()`, `shlex.split` the command — **fail closed if `shlex.split` raises** (do not delegate to `SubprocessTool`). Enumerate **every** URL-bearing subcommand/flag `agent-browser` supports (not just `navigate --url` — also `open`/`visit`/`goto`/`screenshot`/`pdf`/any `--url`/positional URL/`file:` argument) and run each URL through `is_blocked_url` with the browser policy. Reject `file://` and local paths outright. If the subcommand set can't be reliably enumerated, default to an allowlist of known-safe subcommands and reject the rest.

**Browser is harder than fetch:** Playwright follows redirects, iframes, subresources, DNS-prefetch, and JS-triggered navigations — guarding only the initial `--url` is insufficient. In `hosted` mode, **default browser automation to no outbound internet** (the SSRF policy from `url_guard`), enabling it only via an explicit per-install allowlist. If broad browsing is genuinely needed, it requires request interception in `agent-browser` that applies `is_blocked_url` to **every** navigation and subresource request — until that exists, hosted browser access stays allowlist-only.
**Verify:** `run_browser` rejects `navigate --url http://localhost:2019/config`, `open file:///etc/passwd`, and a malformed unbalanced-quote command (shlex raises → rejected, not delegated); a public URL passes (mock subprocess).

### H3. SSRF: `read_page` DNS rebinding + fail-open
**File:** `odigos/tools/scrape.py:18-30`
Replace `_is_private_url` with the shared `is_blocked_url`. For scrape's own httpx fetch path, add per-hop redirect re-validation. Document DNS-rebinding residual (firewall backstop).
**Verify:** covered by `test_url_guard` + a redirect-to-internal test on the scrape fetch path.

### H4. `web_platform` (opencli): no argument sanitization
**File:** `odigos/tools/opencli.py:69`
`command.split()` → `create_subprocess_exec`, no guard. No shell (no shell-injection) but full argument injection.
**Fix:** `shlex.split(command)` (**fail closed if it raises** — return an error, do not exec). Extract `SubprocessTool`'s dangerous-pattern check into a shared `subprocess_arg_guard` and apply it: reject args with `../`, `..\\`, NUL/newline/backtick/`$(`, and option-style flags that read/write arbitrary paths (`--output`, `--config`, and leading-dash absolute-path values).
**Verify:** rejects `search --config /etc/passwd`, `x --output /app/odigos/main.py`, and a malformed shlex string; `search foo` passes (mock subprocess).

### H5. `sso_auto_provision` defaults to `True`
**File:** `odigos/config.py:316`
**Fix:** default `False`. (Even with Bob+Jessica only, a leaked shared `platform_jwt_secret` should not silently mint accounts.)
**Verify:** `/api/auth/sso` with unknown email returns 403 / creates no user when false.

### H6. SSO token in GET query string
**File:** `odigos/api/auth.py:215-216`
JWT in the query string lands in proxy logs, history, referrers.
**Fix:** accept the token via POST body or `Authorization: Bearer` header. The caller is the separate `tamler/odigos-platform` repo, so the agent must accept the new channel **and** keep the legacy query param behind a deprecation flag during rollout; remove the query param after the platform is updated. Plan sequences this cross-repo and notes the platform-side change.
**Verify:** SSO endpoint mints a session via the new channel; HS256/`aud`/`exp` verification unchanged; legacy query param still works while deprecation flag set.

---

## MEDIUM

### M1. CSRF missing on `delete_fact` + `update_profile`
**File:** `odigos/api/auth.py:453-454, 475-476` — add `_check_csrf(request)` (confirmed absent).
**Verify:** both return 403 without `X-Requested-With`.

### M2. Session cookie attributes (Secure behind Caddy + full attribute set)
**File:** `odigos/api/auth.py:99` and every `set_cookie` site in `auth.py` + `platform_auth.py`. Derive scheme from `X-Forwarded-Proto` (as WebAuthn already does). Name the full required attribute set explicitly:
- `Secure=True` (via forwarded-proto), `HttpOnly=True`, `SameSite=Lax` (Strict where it doesn't break the SSO redirect flow), explicit `Path=/`, no over-broad `Domain`, finite `Max-Age`/expiry, and rotation of the session token on login (new token issued, prior epoch invalidated — see M4).
**Verify:** with `X-Forwarded-Proto: https` the cookie is `Secure`+`HttpOnly`+`SameSite`; login issues a fresh token.

### M3. WebSocket upgrades exempt from rate limiting
**File:** `odigos/api/rate_limit.py:54-55` — apply a per-IP connection-rate limit to upgrade requests before forwarding.
**Verify:** rapid repeated upgrades from one IP are throttled.

### M4. No session revocation
**File:** `odigos/api/auth.py` — add a per-user `session_epoch` (integer, bumped on logout + password-change) embedded in the signed token and checked on validation. Bumping invalidates all prior tokens. Lighter than a full session store.
**Verify:** a token minted before a logout/epoch-bump is rejected after.

### M5. `platform_auth.py` email not normalized
**File:** `odigos/api/platform_auth.py:55, 67` — lowercase email before lookup + insert; derive username from local-part (mirror SSO endpoint).
**Verify:** `User@Example.com` matches existing `user@example.com`, no duplicate.

### M6. `audio_process` time args unvalidated to ffmpeg
**File:** `odigos/tools/audio_process.py:247-250` — validate `start_time`/`end_time` against `^\d+(\.\d+)?$` or `^\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$`; reject otherwise.
**Verify:** non-time value rejected; valid formats pass.

### M7. Default-deny auth + route inventory + CSRF/auth-bypass test depth
**Default-deny middleware + route classification.** Establish that auth is required by default and public routes are an explicit, enumerated allowlist (login, status/health, static assets, the SSO entry, password-reset if applicable). Add a **route-inventory test** that walks the FastAPI app's routes and **fails if any route lacks an explicit auth classification** — so adding a new route forces a conscious public/protected decision. Assert every state-changing route (POST/PUT/PATCH/DELETE) carries `require_auth` and, for cookie-auth, `_check_csrf`.

**Origin/Referer defense-in-depth** for cookie-authenticated mutating requests (validate Origin/Referer against the configured host); token-only API clients that don't accept ambient cookie auth are exempt.

**Negative tests that prove bypass-impossibility:**
- **CSRF surface:** cross-site form POST, `fetch` with credentials, HTTP method-override abuse, JSON content-type bypass, CORS preflight misconfiguration.
- **Cookie-vs-token:** token-authenticated (Bearer/api_key) endpoints reject ambient cookie auth where the two would conflict; CSRF header required for cookie-auth state changes only.
- **Auth-bypass negatives:** auth enforced on websocket/SSE endpoints, file downloads, static/private media, OAuth/SSO callbacks, API-key creation, logout, and any admin/debug endpoint.

---

## LOW / defense-in-depth

### L1. WebAuthn login `SELECT ... LIMIT 1`
**File:** `odigos/api/webauthn.py:339` — add `user_id` to `webauthn_credentials` (migration, backfill to sole user), store on registration, look up by credential's `user_id` on login.
**Verify:** a credential resolves to its owning user, not `LIMIT 1`.

### L2. Task callbacks unauthenticated
**File:** `odigos/api/callbacks.py` — HMAC-sign callback URLs over the task_id (using `session_secret` or a dedicated callback secret); verify on POST. Keep the real `len(raw) > 500_000` enforcement.
**Verify:** bad/absent signature rejected; correctly signed succeeds.

### L3. `api_key` written to `config.yaml`
**File:** `odigos/bootstrap.py` (`_persist_generated_api_key`) — write the generated key to `.env`, not `config.yaml`; verify `.env` is gitignored.
**Verify:** fresh bootstrap writes the key to `.env`.

### L4. `CLITool._validate_cli_arg` leading-dash injection
**File:** `odigos/tools/cli_tool.py:104-109` — add opt-in `reject_option_args=True` mode (blocks leading `-`/`--` and absolute paths) for subclasses passing free-text args; don't break allowlisted callers. (Folded into the shared `subprocess_arg_guard` from H4 where practical.)
**Verify:** new mode blocks `--force` and `/etc/passwd`.

### L5. Login timing oracle
**File:** `odigos/api/auth.py:194` — when the user is absent, run `_verify_password` against a static dummy bcrypt hash before the generic 401.
**Verify:** the dummy-hash path is exercised when the user is absent.

---

## Operational rollout (adopted from review)

- **Deploy-time gate:** the release script runs a sandbox self-test (execute trivial code under `bwrap`, assert isolation) and **fails the deploy** if `bwrap` is absent or the self-test fails in `hosted` mode. Production safety must not depend on a human remembering `apt-get install -y bubblewrap` — but that install is also added to host setup.
- **Health/status separation:** add a status flag (surfaced on a health/status endpoint) reporting `code_execution: enabled|disabled (missing isolation)` distinctly from overall app health, so uptime checks don't mask a degraded tool environment.
- **Security logging:** structured logs for blocked sandbox execution, blocked SSRF attempts, CSRF failures, auth denials — including user/request IDs but **never** logging secret-bearing target URLs or tokens (truncate/redact query strings).
- **Rollback plan:** if hardened sandbox breaks code tools in prod, the rollback **disables the code tool**, it does NOT re-enable the insecure fallback.
- **Fleet conformance check** (2 installs today, scriptable): verify every hosted install has `deployment.mode=hosted`, a **distinct** `User=`, the required systemd hardening directives, `0700` perms on root/data, the same app version, `bwrap` present, and no insecure env vars (`ODIGOS_SANDBOX_ALLOW_INSECURE`). Run in the deploy preflight and on demand.
- **Log/trace redaction:** centralized or shared logs must not leak across accounts — redact secrets, tool args containing URLs/tokens, sandbox stderr, cookies, auth headers, `.env` contents, and document snippets. Truncate query strings on logged URLs.
- **Incident-response events (rate-limited):** structured security events for sandbox-escape attempts, blocked private-URL fetches, CSRF failures, and unauthenticated access, tagged with user/request IDs; rate-limit emission so an attacker can't flood the logs.

---

## Cross-cutting modules
- `odigos/tools/url_guard.py` — single SSRF guard (H1/H2/H3), one test file.
- `subprocess_arg_guard` — shared dangerous-arg check (H4 + L4 + SubprocessTool).
- Config additions: `deployment.mode`, `sandbox.require_isolation`, `security.ssrf.<tool>`, `sso_auto_provision` default flip — documented in `config.yaml.example`.
- Migration: `webauthn_credentials.user_id` (L1), existing auto-ALTER pattern, preserve data.

## Testing posture
- No mocks for integration paths where a real check is cheap (project rule); mock only the actual outbound network/subprocess sink.
- Each finding gets a test that fails before the fix and passes after.
- Tests prove bypass-impossibility (negative cases), not only happy "blocked" cases.
- Full suite (`-m "not slow and not network"`) green before deploy; sandbox escape tests run on the `bwrap`-capable CI image.

## Implementation sequencing (drives the plan order)
1. **C1 sandbox fail-closed + hosted-mode hard-fail** — the launch-gating boundary.
2. **C0 OS install hardening** (distinct users, `0700`, systemd directives, backup perms) — the boundary the sandbox depends on; deployable independently.
3. **SSRF** (`url_guard` + H1/H2/H3/H4).
4. **Auth/CSRF route inventory + default-deny** (M7) and H5/H6/M1/M2/M4/M5/M6.
5. **OS/systemd hardening rollout + logging/ops** (deploy gate, fleet conformance, redaction, incident events).
6. **Low/defense-in-depth** (L1–L5).

## Final release-blocker checklist (binary gates — all green before hosted launch)
- [ ] `deployment.mode=hosted` on every install; rejects `ODIGOS_SANDBOX_ALLOW_INSECURE`; fails startup without `bwrap`.
- [ ] No code execution without `bwrap` (disabled error returned, no subprocess spawned).
- [ ] Sandbox escape corpus passes: cannot read this/sibling `.env`/config/DB, SSH keys, backups, `/etc/passwd`; no symlink/proc/fd escape; fork-bomb + rlimits hold; grandchild killed on timeout.
- [ ] SSRF bypass corpus passes across all URL-capable tools (`read_page`/`process_document`/`run_browser`); guard fails closed on DNS error; real local ports (8002/5432/2019) blocked.
- [ ] Auth route-inventory test green (no unclassified route); CSRF enforced on all cookie-auth mutations.
- [ ] OS permissions verified: distinct Unix user per install, `0700` roots/data, no sibling read; backups not cross-readable.
- [ ] Deploy preflight green (bwrap + sandbox self-test + fleet conformance); security events logged without leaking secrets.
- [ ] CI covers each item above.

## Non-goals (explicit)
- **Per-row** object scoping / shared-app multi-tenancy (`user_id` on data tables) — N/A (separate-process model; Bob + Jessica only). **Note:** cross-install A→B isolation at the *filesystem, network, backup, and process* boundaries IS in scope (C0/C1/SSRF cover it); only per-row object scoping is out.
- Full WAF / network segmentation beyond the egress-firewall note.
- Replacing `itsdangerous` sessions with a stateful store (M4 uses the lighter epoch approach).
- Re-auditing the bwrap path internals beyond pinning the profile above.
