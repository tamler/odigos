# LLM-Facing Brittleness Anti-Patterns

**Living registry. Append-only. PR reviewers should consult this before approving any change to tool result formats, system-prompt sections, or skill declarations.**

Linked from: [`docs/superpowers/specs/2026-05-28-brittleness-audit-and-robustness.md`](specs/2026-05-28-brittleness-audit-and-robustness.md) (the doc that explains *why* this registry exists)

## How to use this doc

- **Adding an entry.** When a brittleness bug ships, add a row at the bottom with the date, the surface, what failed, what fixed it, and a severity/frequency/detection-latency annotation. Don't edit older entries — they're dated history.
- **As a PR reviewer.** When a PR changes a tool's result format, a skill's frontmatter, a system-prompt section, or executor's tool-invocation contract: scan this registry for the closest analog and confirm the PR isn't recreating that failure mode.
- **As a PR author.** Before requesting review on the above categories, link the registry entry your change is informed by (if any) in the PR description.

## Annotation key

- **Severity:** `🔴 high` (user-visible failure / data corruption) · `🟡 medium` (degraded behavior, recovers) · `🟢 low` (telemetry only, not user-facing)
- **Frequency:** how many distinct manifestations were observed before fix (`1x`, `3x`, `loop`)
- **Detection latency:** time from introduction to surfacing (`same-day`, `<7d`, `<30d`, `>30d`, `unknown`)

---

## 2026-05-28 — first eight entries

### 1. Persona-section loader dropped all but identity.md
- **Surface:** `odigos/core/context.py::_load_identity()`
- **What happened:** `_load_identity()` only loaded the single section named `identity` from `data/agent/*.md`. The other 8 sections (capabilities, guardrails, voice, classification rules, etc.) were silently dropped from the system prompt. Agents lost their behavioral rules; Sales answered as a generic chatbot.
- **What fixed it:** [`10b913f`](https://github.com/tamler/odigos/commit/10b913f) — concatenate all `always_include` sections sorted by priority.
- **Annotation:** 🔴 high · `3x` (Bob/Jessica/Sales all affected) · `>30d` (shipped weeks before symptoms surfaced)
- **Principle:** §3.1 (contract not display) — "shorter prompt for token savings" silently broke role grounding

### 2. Tool-result pruning at 200 chars after 2 turns
- **Surface:** `odigos/core/executor.py` constants `_PRUNED_MAX_CHARS = 200`, `_PRUNE_AFTER_TURNS = 2`
- **What happened:** Tool results > 200 chars got truncated to 200 + "[pruned]" after 2 turns to save context tokens. Sized for 8k-context-era models. Defeated rich find_tools output which is ~1400 chars.
- **What fixed it:** [`509c214`](https://github.com/tamler/odigos/commit/509c214) — raised to 1500 chars / 4 turns. Every routing model has ≥128k context.
- **Annotation:** 🔴 high · `loop` (broke every multi-turn tool chain) · `>30d`
- **Principle:** §3.4 (context budgets sized for smallest configured model)

### 3. find_tools output too sparse
- **Surface:** `odigos/tools/find_tools.py`
- **What happened:** One-line-per-tool output: `- [TOOL] name [category]: desc[:100] (params: a, b)`. Model saw "tool exists" but no schema, no example, no required vs optional. Defaulted to calling find_tools again with a different query. Loop until max_tool_turns burned without ever answering the user.
- **What fixed it:** [`2374f07`](https://github.com/tamler/odigos/commit/2374f07) — full schema per parameter, required/optional markers, explicit "now this tool is available" instruction. Loop guard at 2 consecutive turns.
- **Annotation:** 🔴 high · `loop` · `unknown` (find_tools is a 2026-04 feature; brittleness only visible under public sales use)
- **Principle:** §3.1 (contract not display) + §3.7 (executor contract — guard is defense)

### 4. find_tools "Next step: tool_name(arg=<string>)" placeholder
- **Surface:** `odigos/tools/find_tools.py` (the formatter shipped in entry #3)
- **What happened:** Compact placeholder example for the model to follow. Model emitted `board_id="<board_id>"` verbatim in the next call.
- **What fixed it:** [`b95b249`](https://github.com/tamler/odigos/commit/b95b249) — replaced with descriptive instruction, no syntactic placeholders.
- **Annotation:** 🔴 high · `3x` (model retried 3 times with placeholders) · `same-day` (caught in retest)
- **Principle:** §3.1 — placeholder syntax is contract-breaking

### 5. Kanban tool result IDs truncated to 8 chars
- **Surface:** `odigos/tools/kanban.py` (`(id: {x[:8]})` in 6 result strings)
- **What happened:** Cosmetic 8-char prefix for readability. Model treated 8-char prefix as the real UUID. All subsequent kanban calls failed with "Card not found" / "Column not found."
- **What fixed it:** [`b95b249`](https://github.com/tamler/odigos/commit/b95b249) — full UUIDs labeled with the param name (`board_id: 3bf94a92-...`, not `id: 3bf94a92`).
- **Annotation:** 🔴 high · `3x` (3 cards failed in one chain) · `same-day` (retest)
- **Principle:** §3.1

### 6. KanbanCreateBoardTool didn't exist
- **Surface:** `odigos/tools/kanban.py` (the missing class)
- **What happened:** Tool family had list/get/create-card/move/update/delete but no `create_board`. Model had no path from "make a board" to a working board; tried `create_card` against a board that didn't exist; got raw `FOREIGN KEY constraint failed`.
- **What fixed it:** [`d8eee65`](https://github.com/tamler/odigos/commit/d8eee65) — `KanbanCreateBoardTool` that creates a board + 3 default columns + FK guards on `create_card`.
- **Annotation:** 🔴 high · `1x` (one full failure chain) · `unknown` (shipped without the tool; never tested from a blank slate)
- **Principle:** §3.2 (surface completeness) + §3.5 (blank-slate testing)

### 7. Skill `tools:` blocks missing or referencing non-existent tools
- **Surface:** `skills/kanban.md`, `skills/journal.md`, `skills/agent-browser.md`, `skills/compliance-check.md`, `skills/google-workspace.md`, `skills/legal-draft.md`
- **What happened:** Six skill files either had no `tools:` block (`activate_skill` constrained to empty set, every tool call logged as "Tool mismatch") or declared tools that didn't exist in the registry (`run_browser`, `run_gws`, `lookup`).
- **What fixed it:** [`d8eee65`](https://github.com/tamler/odigos/commit/d8eee65) + [`89d6a97`](https://github.com/tamler/odigos/commit/89d6a97) — declare real tool lists or `tools: []` with FIXME for genuinely missing surfaces.
- **Annotation:** 🟡 medium (calls worked, just logged as mismatch) · `6x` distinct files · `>30d`
- **Principle:** §3.3 (skills declare tools explicitly)

### 8. Activity page crashed on `.toFixed()` of undefined
- **Surface:** `dashboard/src/components/activity/HeroSection.tsx` + `dashboard/src/hooks/useActivityData.ts`
- **What happened:** Backend `BudgetStatus` returned `daily_spend / daily_limit`. Frontend type expected `total_spent_today / daily_budget / remaining`. Field-name mismatch; first `.toFixed(2)` on `undefined` threw `TypeError`; whole Activity page crashed with "reload the app."
- **What fixed it:** [`61ccf90`](https://github.com/tamler/odigos/commit/61ccf90) — aligned type with backend shape.
- **Annotation:** 🔴 high · `1x` per pageview · `>30d`
- **Principle:** Not LLM-facing but same root cause class — no contract test between two consumers (backend dataclass, frontend type).

### 9. Subagent-tools dispatched task_ids truncated to 8 chars
- **Surface:** `odigos/tools/subagent_tools.py`
- **What happened:** Dispatched task_id list shown as `t[:8] for t in task_ids`. Model called `subagent_status` with 8-char prefix → `Task not found`.
- **What fixed it:** [`89d6a97`](https://github.com/tamler/odigos/commit/89d6a97) — full task_ids in output.
- **Annotation:** 🟡 medium (recoverable: model could re-dispatch) · `unknown` (not observed in production, found via audit) · `>30d`
- **Principle:** §3.1

### 10. goals.py truncated reminder/todo/goal IDs in result strings
- **Surface:** `odigos/tools/goals.py:61,94,119`
- **What happened:** `(id: {rid[:8]})` style in `create_reminder`, `create_todo`, `create_goal`. Model would try to mark a todo complete using the 8-char prefix and fail.
- **What fixed it:** [`89d6a97`](https://github.com/tamler/odigos/commit/89d6a97) — full UUIDs labeled with target param name.
- **Annotation:** 🟡 medium · `unknown` (audit find, not production incident) · `>30d`
- **Principle:** §3.1

---

## Append new entries below this line

<!--
Template:

### N. <short title>
- **Surface:** path or class
- **What happened:** the failure mode in 1-3 sentences
- **What fixed it:** [`<sha>`](https://github.com/tamler/odigos/commit/<sha>) — what the fix did
- **Annotation:** 🔴/🟡/🟢 · `Nx`/`loop` · `same-day`/`<7d`/`<30d`/`>30d`/`unknown`
- **Principle:** §3.X reference
-->
