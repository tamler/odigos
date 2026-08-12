# Container 01 — cleanup

You are working on the **kitchen sink**: the Odigos personal-agent harness. Your job is to make
it work correctly, make it smaller, and **write down what it learned** so the sibling projects
can start from it.

Read first, in this order: `/THE-PLAN.md` (§3 is this charter's context),
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
(python-telegram-bot), `docs` (markitdown, python-docx, openpyxl, pytesseract). Prerequisite
for containers 03 and 04.

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

- [ ] `uv sync && uv run pytest tests/ -q` green — the venv is currently dead
      (`.venv/bin/python` is a broken symlink), so rebuild before trusting anything
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
