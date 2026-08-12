# Container 01 — cleanup

You are working on the **kitchen sink**: the Odigos personal-agent harness. Your job is to make
it work correctly, make it smaller, and **write down what it learned** so the sibling projects
can start from it.

Read first, in this order: `/THE-PLAN.md` (§2 is this charter's context),
`docs/superpowers/specs/2026-08-12-strategic-review.md` (the evidence, with file:line),
`docs/superpowers/anti-patterns.md` (**why cleanup is dangerous here** — all 8 logged incidents
were caused by changes that looked like cleanup).

---

## Invariants — you may not violate these

- **One install = one process = one SQLite DB = one filesystem root = one brain.** Never add
  `user_id`/`tenant_id` to data tables. Isolation is the OS boundary. Settled in
  `specs/2026-05-29-security-hardening-multitenant.md`.
- **Simplify by finishing the last migration, never by collapsing.** All 8 incidents in
  `anti-patterns.md` are collapse-shaped.
- **LLM-facing output is contract, not display.**

## Hard non-goals — stop and escalate if you think you need these

- ❌ Collapsing tool families. The 7 `kanban_*` tools, `goals`, `notebook` stay separate.
  Brittleness spec §3.2: "surface completeness over surface minimalism." Collapsing kanban is
  what made `kanban_create_board` not exist (registry entry #6).
- ❌ Re-tightening context budgets globally. Spec §3.4. `_PRUNE_AFTER_TURNS = 4` and
  `_PRUNED_MAX_CHARS = 1500` (`executor.py:30-31`) are tuned; read the comment.
- ❌ Touching the executor's failure taxonomy (`core/failure.py:11-51`), the `find_tools` loop
  guard (`executor.py:552-577`), the stuck detector (`:539-550`), or hybrid recall
  (`memory/recall.py:62-107`). This is scar tissue, not over-engineering.
- ❌ New features. Any feature.
- ❌ Extracting anything into a package. That is containers 03 and 04.
- ❌ Touching Zoho, tier-2 provisioning, or the mesh beyond the transport task below.

---

## Work, in this order

### 0. Get to a trustworthy baseline. Change no product code until the suite is green.

Phase 0 left 5 failures and a broken test invocation. **All of it is dependency and
environment debt, not merge damage** — the branch was fast-forwarded, so there was no merge
interaction to break anything. Fix these before touching anything in §1.

**0a. The venv's `webauthn` package is physically corrupted. Pinning alone will not fix it.**

Diagnosed 2026-08-12 — and the obvious explanation is wrong, so don't act on it. This is **not**
major-version drift. `webauthn 2.7.1` is installed and is the correct major:
`from webauthn.helpers.structs import PublicKeyCredentialDescriptor` succeeds.

What actually fails is the *first* import block at `api/webauthn.py:76-82`. `webauthn.__file__`
is `None` — the top-level package is resolving as a **namespace package**, because
`webauthn/__init__.py` is missing from disk even though `webauthn-2.7.1.dist-info/RECORD` lists
it at 664 bytes. So the five top-level names are unavailable while every `webauthn.helpers.*`
import at `:83-92` works. `_WEBAUTHN_AVAILABLE` goes False, `_require_webauthn()` raises
**404**, and four tests fail on that one cause.

Cause: a second distribution, **`py-webauthn 0.0.4`**, had been installed into the same
`webauthn/` directory. Uninstalling it took the shared `__init__.py` with it. The subdirectories
still date from 27 Mar; the parent directory's mtime is today.

Fix, all four parts — the first is the one that's easy to miss:

1. **Force a clean reinstall.** `uv sync` sees 2.7.1 as present and will not repair the missing
   file. `rm -rf .venv && uv sync --extra dev`, or `uv pip install --force-reinstall webauthn`.
   Verify with `uv run python -c "import webauthn; print(webauthn.__file__)"` — it must not be
   `None`.
2. **Make sure `py-webauthn` cannot come back.** It is not in `pyproject.toml` and has no
   business in the venv. Find out how it got there before moving on: `uv pip list | grep -i
   webauthn`, and check whether anything declares it transitively. A package that shadows
   another package's import namespace and deletes its `__init__.py` on uninstall is a
   supply-chain hazard, not just untidiness — the legitimate `py_webauthn` project publishes
   *as* `webauthn`, so a separate `py-webauthn 0.0.4` distribution warrants a look before you
   dismiss it.
3. **Constrain the bare dependency.** `pyproject.toml:38` → `"webauthn>=2,<3"`.
4. **Stop swallowing the error** — see 0f. Two independent availability flags exist for this one
   capability, `api/webauthn.py:94` and `api/system/__init__.py:17`. Fixing one does not fix the
   other.

**0b. The test suite can't be invoked as documented.** `uv sync` removes `pytest` (it's in the
dev extra) and `pytest-httpx` isn't declared at all, so collection fails on
`tests/test_api_tool.py`. Add `pytest-httpx` to the dev extra. The correct command is
`uv sync --extra dev && uv run pytest tests/ -q`; fix it wherever it's written down
(`THE-PLAN.md` §2, `Makefile`, `CLAUDE.md`).

**0c. `test_knowledge.py::test_lookup_wikipedia_explicit`** hits the network. Stub it or mark it
`@pytest.mark.network` and deselect by default. A suite that can't pass offline can't gate
anything.

**0d. Migrations aren't idempotent and their failures are swallowed.** Every migration from 005
on logs `partially failed (schema evolved): duplicate column` during test setup — nine of them.
Make them idempotent and stop swallowing the errors. **This matters twice over for Project B**,
where provisioning means running the full migration chain against N fresh databases.

**0e. Closeout housekeeping — already done, do not redo.** Recorded here because an earlier
draft of this charter got it backwards: it told you to `git rm --cached data/subagents/`. **Do
not.** Those 7 files are shipped subagent personas, loaded by `core/subagent.py:75` — untracking
them would ship a clone with an empty personas directory. The error was gitignoring them in the
first place; that is fixed and all 7 remain tracked. `__pycache__/` was already ignored
(`.gitignore:2`) and 28 stale dirs embedding the dead `/Users/jacob/Projects/odigos/` path have
been purged. Redundant `data/*.db-wal` / `-shm` entries removed.

**0f. Silent degradation — 23 `except ImportError` sites. This is the real finding.**

The webauthn bug is not special; it is one instance of a pattern that has already detonated
silently and unnoticed for months. Audited 2026-08-12. **Five sites do it right** —
`tools/translate.py:71`, `spreadsheet.py:264`, `text_analysis.py:78`, `ics.py:73`, `qr.py:57`
return an error to the caller. **Make the other 18 look like those five.**

Highest severity first:

- **`providers/llm.py:503` and `:521` — `except ImportError: pass` around `jsonschema.validate`.
  If `jsonschema` is ever absent, structured-output validation is skipped and the call returns
  as valid.** Declared at `pyproject.toml:37`, so it is latent today — but it is a correctness
  hole on the hot path, and webauthn is proof that "declared" does not mean "importable."
- **`config.py:406` — `pass` on `dotenv`.** `.env` silently not loaded. That is how an API key
  goes missing with no error.
- `core/notifier.py:116` — bare `return`; web push silently no-ops. Same file as the
  `priority=` bug in §1.
- `api/webauthn.py:94` + `api/system/__init__.py:17` — two independent flags, one capability.
- `core/profiler.py:131` — silently substitutes a word-count heuristic.
- `tools/image.py:15` — `_OCR_AVAILABLE = False`; OCR off, nothing said.
- Five copies of `TextBlob = None`: `classifier.py:13`, `evaluator.py:14`,
  `content_filter.py:15`, `followups.py:9`, `template_index.py:18`. Declared at
  `pyproject.toml:41`. Consolidate into one capability probe.
- Debug-level only, invisible at default log level: `tools/catalog.py:35`, `knowledge.py:20`,
  `knowledge.py:61`, `core/webpush.py:78`.

The rule to apply: **a dependency declared in `pyproject.toml` failing to import is an error,
not a feature flag.** Log at ERROR with the exception, surface the degraded capability in
`/api/state` and the startup banner, and let genuinely-optional extras (§4's dependency groups)
be the only things allowed to degrade quietly. This is the exact failure shape
`anti-patterns.md` exists to catch — a feature that reads as present and isn't.

**Done when:** `rm -rf .venv && uv sync --extra dev && uv run pytest tests/ -q` is green,
offline, from a genuinely clean venv, with no swallowed migration warnings — and every
declared-dependency `ImportError` now logs at ERROR instead of vanishing.

### 1. The live bugs

- **`Notifier.notify()` rejects `priority=`.** `notifier.py:32-42` has no such kwarg and no
  `**kwargs`; all 8 call sites in `heartbeat/maintenance.py` pass it — lines 128, 142, 154,
  193, 204, 235, 261, 284. Every one raises `TypeError` into an `except Exception:
  logger.debug`. Nudges, follow-ups, email alerts, storage warnings and update notices have
  **never worked on any agent.** Add `priority: str = "normal"`, then delete the mocks at
  `tests/test_heartbeat_announce.py:79-90` that hide it.
- **Evolution writes to persona files based on inert trials.** `evolution.py:191` auto-promotes
  LLM-generated text into `data/agent/*.md` — including `identity.md` and `guardrails.md` —
  scored from trials whose treatment is never applied (see #3). Set `evolution.enabled: false`
  as the default **first**, before anything else in this list.
- **Heartbeat starves its own headline features.** Phases 4e, 5, 6, 8, 9, 9.5, 10 are each
  gated `if not did_work` (`orchestrator.py:268, 272, 277, 285, 292, 305, 339`), so on an
  active agent, plan execution / proactive / evolution / experience extraction / memory
  evolution are the *first* things skipped. Decide deliberately and document; don't just
  invert it.
- Smaller: `api/state.py:216` reads a nonexistent `cron_manager.entries`;
  `mark_stale_peers()` always returns 0 (`agent_client.py:444-449`, `db.execute` returns
  `None`); `check_storage_quota` writes `kv.storage_usage_gb` after the notify so it's skipped
  exactly when over threshold (`maintenance.py:209`); `context.py:989` reads a
  `settings.agent.history_limit` that `AgentConfig` doesn't define;
  `evaluate_tool_output`'s result is discarded at `executor.py:494`.

### 2. Verified-dead deletions (~1,050 src / ~550 test LOC)

Every one grep-verified to have zero production callers. Re-verify before deleting.

`core/idle_research.py` (103, only its own test imports it) · `core/vad.py` (97, imported
nowhere) · `tools/template_tools.py` (218, **never `registry.register()`ed**) ·
`core/trajectory.py` (147, 1 caller, 0 tests) · `core/fitness.py` (161 —
`update_fitness_score` has no callers so `current_score` is permanently `0.0`) ·
`ToolSpec` + `register_from_specs` (`registry.py:22-30, 85-104`) · `QueryAnalysis`
(`classifier.py:84-92`, never instantiated) · `evaluator.find_qualified_evaluator`
(`:463-482`) · `agent_client.send_response` (`:165`) and `on_message` (`:288`, which makes the
dispatch loop at `:282-286` unreachable) · `EntityGraph.{traverse,get_related,update_entity,merge_entities}` ·
`CronManager` (`cron.py:147-265`) + heartbeat Phase 3b + `cron_entries` — **keep
`CronExpression`**, `scheduler.py:9` imports it · `post_response.extract_entities_background`
(48, duplicates `memory/extractor.py` with near-identical prompts on the same `[:500]` slices —
also removes one LLM call per turn) · tables `channel_mappings`, `deploy_targets`,
`message_artifacts` · dead config keys `proactive.max_per_cycle`, `proactive.safe_tools`
(FEATURES.md claims an enforced read-only mode that does not exist), `agent.allow_external_evaluation`,
`models.*.vision`, `models.*.notes`.

Also align `config.py` defaults with `config.yaml.example` — `ProactiveConfig.enabled` and
`HeartbeatConfig.morning_briefing` default `True` in code, `false` in the example.

### 3. Port-then-delete `ContextAssembler.build()` — the highest-value item

`build()` (`context.py:149-707`, 559 lines) is **unreachable in production**; the live path is
`build_planned()` (`:708`). It is the only caller of things that are still supposed to work:

- the prompt-injection **canary token** (`personality/prompt_builder.py:37-40`) — a security control
- the instruction-hierarchy line
- `agent.concise_mode` (`prompt_builder.py:78-84`) — configurable, currently no effect
- **`checkpoint_manager.get_working_sections()`** — the only code applying an evolution trial's
  prompt override, which is why the evolution engine scores noise

**Port those into `build_planned()` first** (replacing `fallback_registry.load_all()` at
`context.py:877`). Only then delete `build()`, `personality/prompt_builder.py`,
`core/routing.py`, `registry.validate_routing_rules`, `bootstrap.py:1190-1198`, and
`data/agent/routing_rules.md`. Deleting first silently drops a security control — that is
anti-pattern registry entry #1 all over again.

Also de-duplicate the double history load in `build_planned` (`:962` prose + `:982` real turns,
both fire when `plan.needs.history`), and fold `AgentService` into `Agent` or stop `ws.py`
reaching through it at `:246, 268, 376`.

### 4. `pyproject.toml` → optional dependency groups

~40 hard dependencies, no extras, so `pip install odigos` drags torch. Split into
`[project.optional-dependencies]`: `memory` (sentence-transformers, chonkie, sqlite-vec),
`voice` (edge-tts, groq, webrtcvad-wheels), `browser` (scrapling, patchright), `channels`
(python-telegram-bot), `docs` (markitdown, python-docx, openpyxl, pytesseract).

This is also what makes §0f enforceable: once optional extras are declared as extras, anything
in the *core* dependency list failing to import is unambiguously an error.

### 5. `docs/DESIGN-DECISIONS.md` — **the reason this container gates the others**

Write down what this codebase learned, so a fresh implementation in any language starts ahead
instead of blind. Not a summary — the reasoning, with the numbers:

- **The failure taxonomy.** All 4 categories in `core/failure.py:11-51`, the retry policy per
  category, and *which specific model behaviour caused each one*.
- **`find_tools` + JIT injection.** Why `registry.py:44-49` presents exactly one tool instead of
  N. The same-turn expansion at `executor.py:517-537`. The loop guard (`:552-577`) and stuck
  detector (`:539-550`) and what they each caught. **`_PRUNE_AFTER_TURNS = 4` and
  `_PRUNED_MAX_CHARS = 1500` (`executor.py:30-31`) with the reasoning intact** — port the
  9-line comment verbatim, it explains why the obvious smaller values broke multi-turn chains.
- **Context assembly.** What goes in, in what order, and why the order matters for prompt-cache
  hit rate.
- **Hybrid recall.** Vector + FTS5 + RRF merge (`memory/recall.py:62-107`), and why vector-only
  loses.
- **Budget and cost tracking.** The shape of `core/budget.py`, and that tool spend and LLM spend
  share one cap.
- **The tenancy invariant**, stated as a constraint on any future implementation.
- **Every lesson in `anti-patterns.md`, generalised past its incident** — the incident is the
  evidence, the lesson is the deliverable. Registry entry #1 isn't "identity.md broke," it's
  "partial loading of a composite prompt fails silently for 30+ days."

This is Project C's bill of materials. Without it, C starts from nothing.

*(An earlier draft of this plan asked for a `docs/LAYERS.md` engine/product split plus an
import-boundary test. That existed to let a Python ZOdigos share code. ZOdigos is TypeScript, so
it was speculative machinery — dropped, per this codebase's own YAGNI discipline.)*

### 6. Contract tests — human-readable vs LLM-readable output

Your own brittleness spec names this as the missing primitive: *"There is no contract test
between human-readable and LLM-readable output."* Every bug in §1 and every incident in
`anti-patterns.md` is a variant of it. Property-based assertions, not golden strings —
`anti-patterns.md` B.5 already records golden strings being rejected as brittle.

**Without this, everything you deleted in §2 grows back.**

### 7. The transport ABC (folded in here, it's small)

Introduce a `Transport` ABC in place — `websockets` client impl + starlette server impl — and
one integration test standing up two real agents asserting a round-trip reply. This fixes a
confirmed bug: `api/agent_ws.py:115` stores a starlette `WebSocket` but `agent_client.py:150`
calls `ws.send(str)`, which raises, so **an agent can never reply to a peer that dialed in**.
It also removes the `_ws_connections` private reach-in from all 4 sites. **Do not extract a
library.**

---

## Definition of done

- [ ] `uv sync --extra dev && uv run pytest tests/ -q` green, offline, from a clean sync
- [ ] Every §1 bug fixed, with a test that would have caught it
- [ ] ~1,050 src LOC deleted, zero-callers re-verified at delete time
- [ ] `build()` gone, its four live features demonstrably working in `build_planned`
- [ ] `docs/DESIGN-DECISIONS.md` written — the tuned constants carry their reasoning
- [ ] Contract-test harness exists with at least the tool-output cases
- [ ] Two real agents round-trip a peer reply in an integration test
- [ ] `CLAUDE.md`, `FEATURES.md`, `README.md`, `ROADMAP.md` describe what actually exists
      (CLAUDE.md says "95+ tests" — there are 1,399; FEATURES.md says "45+ tools" — 64 are
      registered of 69 declared)
- [ ] `docs/` stale handoffs removed: 8 `GEMINI-*-HANDOFF.md` files in `docs/` plus the 4 at
      repo root

## Escalate, don't decide

Write to `docs/containers/ESCALATIONS.md` and stop if you find: a needed change outside `odigos/` + `tests/` + `docs/`, anything that would
alter the tenancy model, or a case where a non-goal above looks genuinely necessary.
