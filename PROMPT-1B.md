# PROMPT 1B — finish Phase 0

Paste into the same Claude Code session in `~/Projects/test/odigos`.

```
Good report — four of those mismatches were my errors and one of your conclusions needs
revising. Here's the resolution, then finish closeout.

FIRST, the diagnosis you should overwrite: the 5 test failures are NOT a regression the
merge introduced. It was a fast-forward, so main IS the branch tip — there is no merge
interaction that could break anything. Four of the five are one cause:

  pyproject.toml:38 declares a bare "webauthn" with NO version constraint.
  odigos/api/webauthn.py:75-96 wraps its imports in try/except ImportError and sets
  _WEBAUTHN_AVAILABLE = False. Every endpoint calls _require_webauthn() FIRST, which
  raises 404 "WebAuthn not available".

  The proof is which test passed: test_login_begin_no_credentials expects 404 and passed,
  because it gets 404 either way. The three expecting 401/401/400 failed WITH 404, and
  test_webauthn_user.py fails for the same reason. One cause, not four bugs.

Confirm it:
  uv run python -c "import webauthn; print(webauthn.__version__)"
  uv run python -c "from webauthn.helpers.structs import PublicKeyCredentialDescriptor; print('ok')"

Report what those two print. Do NOT fix it — pinning webauthn and fixing the silent
ImportError degradation is Project A section 0a, and I want it done inside that container
with the suite as its gate. test_knowledge.py::test_lookup_wikipedia_explicit is a
separate cause: it hits the network.

NOW finish closeout. Nothing here touches odigos/ or tests/ product code:

1. Push main. That resolves the -d refusal — the branch is 1 ahead of its upstream because
   of the unpushed closeout commit, which is exactly what -d guards against.
     git push origin main
     git branch -d security/hardening-hosted-launch
     git push origin --delete security/hardening-hosted-launch    # if it exists remotely
   If -d still refuses, stop and tell me. Do not use -D.

2. Repo hygiene the scripts couldn't finish:
   - Purge stale __pycache__ (tracebacks reference /Users/jacob/Projects/odigos/tests/...,
     a path that no longer exists) and add __pycache__/ to .gitignore.
   - git rm --cached the 7 files tracked under data/subagents/ — gitignoring a tracked file
     does nothing.
   - Drop the redundant data/*.db-wal and data/*.db-shm entries; data/*.db-* covers them.

3. Replace scripts/03-containers.sh with the v2 I'm sending (it no longer copies charters
   over CLAUDE.md — you were right, that clobbers a tracked file and leaves every worktree
   dirty, and it's pointless because worktrees share the repo). Then run it.

4. Commit hygiene + the updated docs as one commit and push.

Then stop. Report: what main is at, remaining branches, the two webauthn probe outputs, and
the worktree list.
```

---

## Then launch Project A

New Claude Code session, opened on `~/Projects/test/odigos/.worktrees/cleanup`:

```
Read docs/containers/01-cleanup.md. It is your charter and it is binding — especially the
Hard non-goals.

Start with section 0 and do not touch anything in section 1 until the suite is green
offline from a clean `uv sync --extra dev`. Section 0 is the dependency and environment
debt Phase 0 surfaced: the unpinned webauthn package that silently disables passkey login
and causes 4 test failures, the missing pytest-httpx declaration, a network-dependent
knowledge test, and nine migrations whose "duplicate column" failures are swallowed as
warnings.

After each numbered section: run the suite, commit, and give me a one-paragraph summary.
Do not batch sections into one commit.

Two things to actively resist:
- Collapsing tool families or tightening context budgets. Read
  docs/superpowers/anti-patterns.md first — all 8 logged incidents came from changes that
  looked exactly like sensible cleanup. Brittleness spec §3.2 and §3.4 forbid these two
  by name.
- Deleting ContextAssembler.build() before porting its four live features into
  build_planned(). One of them is a prompt-injection canary. Port, verify, then delete.

If you need something the charter forbids, write it to docs/containers/ESCALATIONS.md and
stop.
```
