# THE PLAN

**The only plan doc.** Everything I wrote earlier is either absorbed here or deleted by
`scripts/01-files.sh`. Two documents survive alongside it:
`docs/superpowers/specs/2026-08-12-strategic-review.md` (the evidence, with file:line) and
`docs/superpowers/anti-patterns.md` (your incident registry, referenced by every charter).

Run order is §2. Complete file inventory is §2.1. Nothing is left to figure out.

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
| **A** | `odigos` cleanup — kitchen sink works, smaller, engine visible | existing repo, `chore/cleanup` worktree | Phase 0 |
| **B** | tier 2 — provisioning + admin management | existing repo, `feat/tier2-provisioning` worktree | A |
| **C** | `zodigos` — the race car | **new repo** | A's `DESIGN-DECISIONS.md` |
| **D** | `tool-router` — `find_tools` as a standalone MCP router | **new repo** | A |

A gates everything. B, C, D are independent of each other.

---

## 2. Execution — three scripts, one job each

Run in order, in a **real terminal**. Not through Cowork: the device bridge mount cannot
`unlink()`, which is why git stranded lock files earlier.

```bash
cd ~/Projects/test/odigos
bash scripts/01-files.sh        # every file/dir operation. no git branch work.
bash scripts/02-git.sh          # merge + branch deletes + commit. no file surgery.
uv sync && uv run pytest tests/ -q | tail -40    # READ THIS before pushing
git push origin main
bash scripts/03-containers.sh   # worktrees + charters
```

`01` deletes and ignores. `02` touches branches and commits. `03` creates containers. Nothing
overlaps, each is re-runnable, and none of them push.

### 2.1 The complete file inventory — nothing else to figure out

Verified against the actual tree, 2026-08-12. This is the whole list.

**DELETED by `01-files.sh` — junk (434MB)**

| Path | Why |
|---|---|
| `_to_delete/odigos.db-wal` (360MB) | orphaned WAL; `data/odigos.db` gone since 13 Apr. SQLite cannot replay a WAL with no database — unrecoverable, and you approved discarding it |
| `_to_delete/odigos.db-shm` | same |
| `_to_delete/odigos-snap.tgz` (77MB) | my analysis snapshot |
| `_to_delete/gitlocks/*.lock` (3) | git locks the bridge stranded |
| `_to_delete/local-mods/{uv.lock,project.yml}` | backups; both regenerate (`uv sync`, serena) |
| `_to_delete/.__writetest` | my probe file |
| `.snap/` | empty dir left behind |
| `odigos.db` (root, 0 bytes) | stray; the real DB is `data/odigos.db` |
| `.DS_Store` | Finder litter, now gitignored |
| `data/test_final.db-{shm,wal}` | orphaned test-DB sidecars |
| `data/test_evolution.db-{shm,wal}` | orphaned test-DB sidecars |

**DELETED by `01-files.sh` — stale docs (11 GEMINI handoffs, all April, all landed)**

| Location | Files |
|---|---|
| root | `GEMINI.md`, `GEMINI-BACKGROUND-TASKS-HANDOFF.md`, `GEMINI-POLISH-HANDOFF.md`, `GEMINI-SERVICES-HANDOFF.md` |
| `docs/` | `GEMINI-HANDOFF.md`, `GEMINI-BUBBLE-HANDOFF.md`, `GEMINI-IMAGES-HANDOFF.md`, `GEMINI-PHASE5-HANDOFF.md`, `GEMINI-PWA-HANDOFF.md`, `GEMINI-VOICE-HANDOFF.md`, `GEMINI-WORKSPACE-HANDOFF.md` |

**DELETED by `01-files.sh` — my own scaffolding, superseded**

`docs/superpowers/plans/2026-08-12-decommission-and-rebuild.md` ·
`docs/superpowers/plans/2026-08-12-tiers-revision.md` · `docs/containers/README.md` ·
`docs/containers/setup-containers.sh` · `phase0-cleanup.sh`

Two sources of truth is the failure mode this whole exercise is about. These go.

**KEPT — the nine files that survive from all of this**

| Path | Role |
|---|---|
| `THE-PLAN.md` (root) | this file. the plan |
| `scripts/01-files.sh`, `02-git.sh`, `03-containers.sh` | execution |
| `docs/containers/01-cleanup.md` … `04-tool-router.md` | the four charters, copied in as each project's `CLAUDE.md` |
| `docs/superpowers/specs/2026-08-12-strategic-review.md` | the evidence, with file:line |

**KEPT — untouched, don't let any container delete these**

`docs/superpowers/anti-patterns.md` (the incident registry — referenced by every charter) ·
`docs/superpowers/specs/` (46 design docs, project history) ·
`docs/superpowers/plans/` (34 after the two above are removed) ·
`docs/ARCHITECTURE.md`, `PRD.md`, `integration-api.md`, `deployment/`, `images/`, `plans/` ·
all install/deploy scripts (Projects A and B decide their fate, not this cleanup)

**GITIGNORED by `01-files.sh`** — `.DS_Store`, `_to_delete/`, `.snap/`, `data/*.db{,-wal,-shm}`,
`data/{artifacts,uploads,conversations,chroma,subagents,subagent_workspace,audio,files}/`,
`data/vapid_keys.json`

**LEFT VISIBLE ON PURPOSE — your call, not the script's**

| Path | Size | Why it's your decision |
|---|---|---|
| `data/brain/` | 8K | durable persona knowledge. `memory/brain_writer.py` writes it, `brain_reader.py` rebuilds the DB from it. Content, not state |
| `data/agent/` | 36K | identity, capabilities, guardrails, sources. Same |
| `data/kanban/` | 6.9M | user content from the dead local instance |
| `data/notebooks/` | 6.8M | same |
| `data/{prompts,sources,wiki,plugins}/` | ~200K | same |

Commit them as fixtures or move them out of the repo — but the script won't silently hide 14MB
of your content behind a gitignore.

**CREATED by `03-containers.sh`**

`.worktrees/cleanup/` on branch `chore/cleanup` (+ its `CLAUDE.md`) ·
`.worktrees/tier2/` on branch `feat/tier2-provisioning` (+ its `CLAUDE.md`) ·
`docs/containers/ESCALATIONS.md`

**CREATED BY YOU, later, outside the repo**

`../tool-router/` (Project D, after A) · `../zodigos/` (Project C, after A writes
`docs/DESIGN-DECISIONS.md`). Both are separate repos, not worktrees — D's whole thesis is zero
Odigos imports, and C is a different language.

### 2.2 Not in any script — infrastructure, do it yourself

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

## 3. Project A — cleanup. What Claude Code actually does.

Charter is `docs/containers/01-cleanup.md`, installed as the worktree's `CLAUDE.md`. In order:

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

## 4. Order of operations

```
scripts/01-files.sh  →  scripts/02-git.sh  →  uv sync + pytest  →  git push
                                                     │
                                        scripts/03-containers.sh
                                                     │
                            Project A  .worktrees/cleanup   ← launch Claude Code HERE, only here
                                                     │
                        ┌────────────────────────────┼────────────────────────────┐
                   Project B                    Project C                    Project D
              .worktrees/tier2                 ../zodigos                 ../tool-router
              02-tier2.md                      03-zodigos.md (TS)         04-tool-router.md
                                          needs DESIGN-DECISIONS.md
```

Separately and in parallel: the infrastructure teardown in §2.2.
