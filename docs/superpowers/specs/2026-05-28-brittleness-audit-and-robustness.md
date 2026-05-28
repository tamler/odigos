# System Brittleness Audit & Robustness Plan

**Status:** spec / planning
**Date:** 2026-05-28
**Motivation:** Multiple "simplifications" shipped over the past months have backfired when met with real LLM behavior. Pattern is consistent enough to be worth a systematic audit and a set of guiding principles going forward.

---

## 1. The pattern

We keep finding the same shape of bug:

> A change that **looked like cleanup or optimization** — shorter responses, tighter caps, smaller display strings, fewer "redundant" fields — broke real LLM behavior because the LLM treats every byte it sees as authoritative.

The simplifications were not wrong in intent. They were wrong in **assumption** — that the LLM would tolerate ambiguity the way a human reader would. Small/cheap models don't have that tolerance; they treat the prompt as ground truth and act on what's literally there.

## 2. Catalog of known instances (2026-05-28)

| Site | "Simplification" | What broke | Fix |
|------|------------------|------------|-----|
| `_load_identity()` (context.py) | Only loaded `identity.md`, dropped `capabilities.md` + `guardrails.md` + 6 others "to keep the prompt short" | Agents lost their behavioral rules and drifted off-role. Sales answered as a generic chatbot, claimed to be "trained by Google" on one provider | `10b913f` — concatenate all `always_include` sections |
| `_PRUNED_MAX_CHARS = 200` (executor.py) | Truncate tool results > 200 chars after 2 turns "to save context tokens" | Rich `find_tools` output (~1400 chars) got shredded mid-sentence after turn 2, model lost tool grounding | `509c214` — raised to 1500 chars / 4 turns; every model in routing now has ≥128k context |
| `find_tools` output (`tools/find_tools.py`) | One-line-per-tool: `- [TOOL] name [cat]: desc[:100] (params: a, b)` | Model saw "tool exists" but no schema, no example. Defaulted to calling find_tools again (loop) | `2374f07` — full schema, per-param descriptions, "Next step" instruction; loop guard at 2 consecutive turns |
| `find_tools` "Next step: tool_name(arg=<string>)" | Compact placeholder example | Model emitted `<board_id>` literally as a string value | `b95b249` — replaced with descriptive instruction, no syntactic placeholders |
| Kanban tool responses `(id: {id[:8]})` | Truncated UUIDs "for readability" | Model copied 8-char prefixes as real IDs, all subsequent calls failed | `b95b249` — full UUIDs labeled with the param name |
| `KanbanCreateBoardTool` didn't exist | Surface was list/get + card CRUD only | Model had no path from "make a board" to a working board; tried `create_card` against a board that didn't exist | `d8eee65` — added create_board tool that seeds default columns |
| `skills/kanban.md`, `skills/journal.md` missing `tools:` block | Skills declared without tool allowlists | `activate_skill('kanban')` set `_active_skill_tools = set()`, every kanban call logged as a "Tool mismatch" | `d8eee65` — declare the real tool list on each skill |
| `kanban_create_card` no FK guard | Let SQLite throw the FK exception verbatim | Model got "FOREIGN KEY constraint failed" with no recovery path | `d8eee65` — validate board + column up front; on miss return an actionable error pointing to `create_board` |

Different surfaces, same lesson: **LLM-facing output is contract, not display.**

## 3. Principles for the system going forward

### 3.1 LLM-facing output is contract

Anything the model reads is potentially something the model will copy. Treat tool result strings, error messages, and find_tools output with the same care as JSON schemas:

- **Full IDs, never truncated.** If the LLM needs to use it, it must be the real value.
- **No placeholder syntax in examples.** `<string>` / `<param_name>` / `...` get emitted verbatim. Use descriptive prose instead: "use real values from the user's request."
- **Label values with their target parameter name** (`board_id: abc123`, not `id: abc123`) so the model knows which slot to put it in.
- **Errors should explain the next step.** "Foreign key constraint failed" → "No board exists with id X. Call kanban_create_board first." The model can read; give it directions.

### 3.2 Surface completeness over surface minimalism

A tool surface with gaps (no `create_board`, no `create_column`) forces the model into unrecoverable paths. Before considering a tool family "done," ask: **from a blank slate, can the model build the data structures this tool family operates on?**

- list / get / create / update / delete should all exist for each resource the agent can manipulate
- "It can be created via the dashboard" doesn't count — the model has no dashboard
- Auto-creating sensible defaults (kanban_create_board → To Do/Doing/Done columns) is good UX, not over-engineering

### 3.3 Skills declare their tools explicitly

Empty `tools:` blocks in skill frontmatter look like "use any tool" but actually mean "no tools expected" to the executor. The skill activation system constrains based on this list — silence is not the same as wildcard.

Required for every skill .md frontmatter:

```yaml
---
name: <skill>
description: <one line>
tools:
  - <every tool name this skill expects to invoke>
---
```

### 3.4 Context budgets should be sized for 128k+, not 8k

Every model in our current routing has at least 128k context. Most have 200k–1M. Pruning constants written for the 8k–32k era are over-optimizing on the wrong axis — we're saving 1–5 KB of token budget at the cost of breaking multi-turn tool sequences.

Default rule: **only prune when the conversation actually approaches the context window**, not after N turns. A 50-turn chat at 32k tokens is fine; aggressive turn-based pruning was solving a problem we no longer have.

### 3.5 Test from a blank slate

Every behavioral test should start from a fresh DB. The bugs above were invisible against pre-seeded data:

- "Create a kanban board" only works if `kanban_create_board` exists, AND if the FK guard handles a missing board, AND if the response has usable IDs.
- All three were broken; none were caught because nobody runs an agent without a seeded board.

Add a smoke-test workflow: spin up an empty agent, ask it to do common multi-step tasks (kanban, notebook, image gen with budget tracking, etc.), assert it completes and the DB state matches.

## 4. Audit checklist — areas to systematically review

These were flagged in today's audit but not yet investigated:

### Critical — likely affects LLM behavior

- [ ] **Other `tools/*.py` files with `[:N]` truncation in result strings.** Same risk as kanban. Grep target: `f".*id.*\[:[0-9]+\].*"` in `odigos/tools/`.
- [ ] **All skill .md files** — verify every skill has a `tools:` block matching the real tools it uses. (Tonight covered kanban + journal; 12 others reviewed, all had blocks, but values weren't validated against the live tool registry.)
- [ ] **Other tool families with surface gaps** like kanban-no-create-board. Notebook, kanban (now fixed), todo, plans, contacts — for each: can the model fully bootstrap from empty? See test suggestion in §3.5.
- [ ] **find_tools query-set coverage.** Today the model called find_tools with queries "manage kanban", "generate music", "process document" and got useful results. But what about "save a note", "schedule a reminder", "send an email"? Audit the discoverability of every registered tool by simulating queries.
- [ ] **System prompt cache stability.** The fix in `10b913f` concatenates all persona sections — but the order is by `priority` field. If a new section is added with a priority that interleaves with existing ones, the prefix changes and prompt caching misses for every existing user. Sort order must be stable; consider documenting priority bands ("identity=10, behavioral_rules=20, capabilities=50, ...") so future additions don't shift the prefix.

### Medium — affects telemetry / observability

- [ ] **`post_response.py` user_message[:500] previews** — likely fine since it's only for storage/logging, but verify it's never re-injected into a prompt.
- [ ] **`evaluator.py` user_content[:500] / assistant_content[:500]** — for evaluation traces. Same question: ever re-injected?
- [ ] **`auto_title.py` user_message[:200]** — for title generation, fine since titles are short.
- [ ] **`brain_compiler.py` content[:100] / [:200]** — for wiki page previews. Confirm previews stay as previews and aren't ever the LLM-facing version of the underlying note.
- [ ] **`subagent.py` line 519 context_facts.append(content[:200])** — subagent context truncation. May actually be harmful if subagents need richer facts; investigate.

### Lower — operational

- [ ] **All "Tool mismatch" log lines** in production. Each one is the model trying to call a tool the skill activation system blocked. Real bug somewhere — either skill needs to declare the tool, the model is making a bad call, or the constraint logic is too strict.
- [ ] **`max_tool_turns` defaults** (Sales had 3, Bob/Jessica have 15). Look at distribution of "Hit max tool turns" warnings in journals; tune per-agent if needed.
- [ ] **Kanban "tool was called in parallel with create_board" race.** The model issued create_board + create_card calls in parallel today. Card calls failed cleanly (thanks to the FK guard) and the model recovered, but it would be better if parallel calls had explicit ordering hints, or if the model knew sibling tool calls couldn't see each other's results within a turn.

## 5. Phased plan

### Phase A — audit + immediate fixes (1 day)

Walk the audit checklist in §4. Fix any "critical" item that's a literal LLM-behavior break (truncation, missing tools, missing skill declarations). Defer "medium" and "lower" items to logged tickets.

Output: a list of additional commits in the pattern of the ones in §2.

### Phase B — robustness infrastructure (2-3 days)

1. **Blank-slate smoke test** (§3.5): a pytest fixture that boots a fresh agent and exercises common multi-step flows. Assert DB state + that no `Tool mismatch` / `find_tools loop guard` / `Retrying tool` warnings fired.
2. **Skill frontmatter validation** at agent startup: every skill must declare `tools:` matching tools actually in the registry. Warn (or fail) on empty or invalid declarations.
3. **find_tools coverage check**: spin up a registry, run a fixed list of query strings, assert each registered tool surfaces in at least one query's results. Fail CI if a tool is undiscoverable.
4. **Stable system-prompt prefix order**: codify priority bands and document them in `personality/section_registry.py`. Existing sections keep their numbers; new sections slot into bands.

### Phase C — behavioral telemetry (ongoing)

1. Surface `Tool mismatch` / `Retrying tool` / `find_tools loop guard fired` warnings in the Activity page so operators see brittleness as it happens.
2. Aggregate per-tool failure rates into a per-agent dashboard ("kanban_create_card: 12 failures, 7 successes today").
3. Pre-launch gate: hosted Starter/Pro tiers don't open until a passing blank-slate smoke test exists for every common multi-step flow.

## 6. Disposition

Not a single shippable artifact — this is an **operating principle** doc plus a phased work plan. Phase A can be picked up in the next session; Phase B/C inform CI work that pairs with the pre-launch capabilities-config refactor.

Tags: `hosted-readiness`, `robustness`, `tools-design`, `pre-launch`.
