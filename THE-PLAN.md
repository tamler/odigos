# THE PLAN

**The only plan doc.** Six files survive from all of this planning:

| File | Role |
|---|---|
| `THE-PLAN.md` | this — decisions, Project A, what's outstanding |
| `docs/containers/01-cleanup.md` … `04-tool-router.md` | the four project charters |
| `docs/superpowers/specs/2026-08-12-strategic-review.md` | the evidence, with file:line |

Plus `docs/superpowers/anti-patterns.md`, which was already yours and is referenced by every
charter. The closeout scripts and prompt files were consumed and deleted.

Phase 0 closeout is done — see the Appendix for what happened and how to revert. What's live
now is §2 (Project A) and §3 (infrastructure teardown). §4 is the order.

---

## 1. Decisions — settled, with the reasoning compressed

### 1.1 Tenancy

**One person = one instance = one process = one SQLite DB = one filesystem root = one brain.**
Multi-user means provisioning more installs. **Never** add `user_id`/`tenant_id` to data tables.

Already true and already documented: 68 of 69 tables have no tenancy column, 642 raw SQL sites,
and `specs/2026-05-29-security-hardening-multitenant.md` states it outright. Closed. Goes in
`CLAUDE.md` so no future session reopens it.

### 1.2 Three tiers are orchestration, not product variants

| Tier | What it is | Where the work lives |
|---|---|---|
| 1. Single self-host | one install, one person | exists today |
| 2. Team/company self-host | N isolated installs + provisioning + admin management | Project B |
| 3. Multi-user hosted | tier 2 + signup, billing, quota | `odigos-platform`, un-archive later |

**The admin control plane runs outside every instance**, with no access to any instance's DB or
data dir. Fleet management inside an agent would breach the boundary tier 2 exists to enforce.

### 1.3 ZOdigos is a sibling product, not a config profile

You were right and I was wrong. A deep Zoho product **removes** more than it adds — kanban,
notebooks, feed, music, images, quiz, personal-memory schema, the personal dashboard are all
noise to a CRM/Books/Desk operator, and the memory layer wants an entity graph over
accounts/deals/contacts instead of over someone's life. Kitchen sink and race car.

### 1.4 Rewrite vs port — you were right, and my argument was bad

I said a rewrite loses the scar tissue. That assumed a rewrite done in ignorance, which is a
strawman: you have the registry, the tuned constants, the failure taxonomy. A rewrite that
*reads* them starts ahead, not blind.

The narrow true version of my point: what transfers is the lessons **already written down**. So
write them down properly. That's a real deliverable — `docs/DESIGN-DECISIONS.md`, built in Project A (§3, A5) — the
distilled "what we learned and why" that any fresh implementation follows. It replaces the
shared-engine idea, which was load-bearing only if ZOdigos were Python.

### 1.5 ZOdigos is TypeScript/Node — for install and distribution

**The reason is install friction, and the evidence is in this repo: 1,240 lines of shell
installer** across `install.sh` (525), `install-bare.sh` (596) and `install-voice.sh` (119).
That is not a coincidence, it's a symptom. A Python service that someone else has to install
needs a Python version, a venv, `uv` or pip, and native builds — and the moment
`sentence-transformers` is in the tree, a multi-GB torch download.

Node's distribution story is materially better for software other people install:

- `npx <pkg>` — run with no install step at all
- single-file executables via Node SEA or `bun build --compile`
- npm present on essentially every developer and consultant machine
- no venv, no interpreter version management

If ZOdigos is sold to Zoho consulting partners who deploy it on client machines, that gap is a
revenue factor, not a preference. Decision: **TypeScript/Node.**

**One design constraint makes it pay off, and it is not optional: no local ML.** Hosted
embeddings only, over the API. The moment you pull in `transformers.js`/ONNX or a natively-built
`sqlite-vec`, you are back to a build step and every distribution advantage evaporates —
`sqlite-vec` extension loading is the recurring Node failure in the wild (`node:sqlite` builds
compiled with `OMIT_LOAD_EXTENSION` on macOS, better-sqlite3 breakage on Node 24, native-ABI
rebuilds each upgrade). Target **zero native dependencies** so `npx zodigos` genuinely works;
use Node 22+'s built-in `node:sqlite` or hosted vector search.

Two things this costs, stated once so they're not surprises: no numpy for evaluation scripts,
and no reuse of the Python harness — but per §1.4 that was a rewrite anyway.

*Separately, if you ever host on Zoho Catalyst: AppSail's persistent-disk semantics are
undocumented and a SQLite-file harness needs durable disk. Verify first; a VPS sidesteps it.*

### 1.6 What the four projects are

| | Project | Repo | Gated on |
|---|---|---|---|
| **A** | `odigos` cleanup — works, smaller, lessons written down | existing repo, branch `chore/cleanup` | Phase 0 ✅ |
| **B** | tier 2 — provisioning + admin management | existing repo, branch `feat/tier2-provisioning` | A |
| **C** | `zodigos` — the race car | **new repo** | A's `DESIGN-DECISIONS.md` |
| **D** | `tool-router` — `find_tools` as a standalone MCP router | **new repo** | A |

A gates everything. B, C, D are independent of each other.

---

## 2. Project A — cleanup

Charter: `docs/containers/01-cleanup.md`. Run it on branch `chore/cleanup` in this repo — no worktree. In order:

**A1. The live bugs.**
- `Notifier.notify()` has no `priority` kwarg (`notifier.py:32-42`) but all 8 call sites in
  `heartbeat/maintenance.py` pass one — lines 128, 142, 154, 193, 204, 235, 261, 284. Every one
  raises `TypeError` into an `except Exception: logger.debug`. Nudges, follow-ups, email alerts,
  storage warnings, update notices have **never worked**. Fix, then delete the mocks at
  `tests/test_heartbeat_announce.py:79-90` that hide it.
- `evolution.enabled: false` **first**, before anything else — `evolution.py:191` auto-promotes
  LLM text into `data/agent/identity.md` and `guardrails.md`, scored from trials whose treatment
  never applies.
- Heartbeat starvation: phases 4e, 5, 6, 8, 9, 9.5, 10 all gated `if not did_work`
  (`orchestrator.py:268-339`), so on an active agent proactive/evolution/plans are skipped first.
  Decide deliberately, document; don't just invert it.
- Small ones: `api/state.py:216` (nonexistent `cron_manager.entries`),
  `agent_client.py:444-449` (`mark_stale_peers` always returns 0), `maintenance.py:209` (quota
  write skipped exactly when over threshold), `context.py:989` (phantom
  `settings.agent.history_limit`), `executor.py:494` (discarded evaluation result).

**A2. Verified-dead deletions, ~1,050 src LOC.** Full list with line numbers in the charter.
Re-verify zero callers at delete time, don't trust my grep.

**A3. Port-then-delete `ContextAssembler.build()`.** 559 lines, unreachable in production, but
sole caller of the prompt-injection canary, the instruction-hierarchy line, `concise_mode`, and
`checkpoint_manager.get_working_sections()`. **Port those into `build_planned()` first.**
Deleting first silently drops a security control — that's anti-pattern entry #1 again.

**A4. `pyproject.toml` → optional-dependency groups.** ~40 hard deps, so `pip install odigos`
drags torch.

**A5. `docs/DESIGN-DECISIONS.md` — the distillation artifact.** *This is why Project A gates C.*
The written-down version of everything ZOdigos should start from:
- the 4-category failure taxonomy and its retry policy, and which model behaviour caused each
- `find_tools` + same-turn JIT injection: why one tool is presented instead of N, the loop
  guard, the stuck detector, and **`_PRUNE_AFTER_TURNS = 4` / `_PRUNED_MAX_CHARS = 1500` with
  the reasoning intact**
- context assembly: what goes in, in what order, and why the order matters for prompt caching
- hybrid recall: vector + FTS5 + RRF merge, and why not vector-only
- budget/cost tracking shape
- the tenancy invariant
- every lesson in `anti-patterns.md`, generalised past its incident

A fresh implementation in any language reads this and starts ahead.

**A6. Contract tests — human vs LLM-readable output.** Your brittleness spec names this as the
missing primitive; every A1 bug is a variant of it. Property-based, not golden strings
(`anti-patterns.md` B.5 already rejected golden strings as brittle). **Without this, everything
A2 deleted grows back.**

**A7. Transport ABC.** `websockets` client + starlette server impls, plus one test standing up
two real agents and asserting a round-trip reply. Fixes the confirmed bug where
`api/agent_ws.py:115` stores a starlette `WebSocket` and `agent_client.py:150` calls
`ws.send(str)`, so an agent can never reply to a peer that dialed in. **Do not extract a
library.**

**A8. Docs truth-up.** `CLAUDE.md` says "95+ tests" (there are 1,399), `FEATURES.md` says "45+
tools" (64 registered of 69) and claims an enforced proactive read-only mode that doesn't exist
(`proactive.safe_tools` is read nowhere), `README.md` still sells hosted and claims "works
proactively when idle", `ROADMAP.md` fleet table. Plus the 8 `GEMINI-*` files in `docs/`.

**Fences (in the charter, repeated here because they're the point):** no collapsing tool
families, no re-tightening context budgets, no touching the failure taxonomy / `find_tools`
guards / hybrid recall, no new features, no extraction, no tenancy changes.

**Done when:** `uv run pytest tests/ -q` green, every A1 bug has a test that would've caught it,
`build()` gone with its four features proven live, `DESIGN-DECISIONS.md` written, contract tests
exist, two agents round-trip a peer reply, docs true.

---


---

## 3. Still outstanding — infrastructure teardown

- **Verify the archive before cancelling anything.** `tar tzf` every tarball listed in
  `~/odigos-vps-archive/MANIFEST.md`, take a final `pg_dump` of `odigos-postgres`, and restore
  it into a throwaway container to prove it works. It's your only offsite copy.
- **Then** cancel: `51.81.82.221` (current), `82.25.91.86` (old bare-metal), `100.89.147.103`
  (uxrls.com Jessica). The last two have been billing unused since May.
- DNS at the registrar: `odigos.one`, `jacob.`, `jessica.`, and the orphaned
  `trading.odigos.one`.
- Revoke keys — they outlive the servers: OpenRouter, Groq, Kie.ai, the VAPID pair,
  `PLATFORM_AGENT_JWT_SECRET`, any `card-sk-*` mesh keys.
- **Archive, don't delete,** `github.com/tamler/odigos-platform` — tier 3 needs it.


---

## 4. What's next

1. **Finish closeout** in the existing session: push main, delete the merged branch, repo
   hygiene, delete the consumed scaffolding, create branch `chore/cleanup`.
2. **Project A** — fresh session, same folder, on `chore/cleanup`. Brief it with
   `docs/containers/01-cleanup.md`. Start at its section 0: the suite must be green offline
   from a clean `uv sync --extra dev` before any product code changes.
3. **Then** B, C or D — see §1.6. A gates all three; C additionally needs
   `docs/DESIGN-DECISIONS.md` from A.
4. **Independently, whenever:** the teardown in §3. Three servers are still billing.

---

## Appendix — Phase 0, done 2026-08-12

Reverting point: **`git tag pre-cleanup-2026-08-12`** (`ef22dea`, on the remote).

- 433MB junk deleted, 11 stale GEMINI handoffs, 4 orphaned test-DB sidecars, my own
  planning scaffolding. Repo 2.1G → 1.5G, `data/` 18M.
- `main` fast-forwarded over **42** commits of multi-tenant security hardening (sandbox
  fail-closed, SSRF/arg/URL guards, `api/rate_limit.py`, security event log, CSRF + cookie +
  session-epoch hardening, ~35 tests). 7 dead `feat/*` branches deleted with `-d`.
- Suite: **1620 passed, 5 failed, 8 skipped.** Four of the five are one cause — an unpinned
  `webauthn` whose import failure is swallowed, so every endpoint 404s and passkey login is
  silently dead. The fifth hits the network. All of it is Project A §0.
- `data/brain/`, `data/agent/`, `data/kanban/`, `data/notebooks/` untouched by design.
