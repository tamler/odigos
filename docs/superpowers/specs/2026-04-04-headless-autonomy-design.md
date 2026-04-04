# Headless Heartbeat Autonomy Design

**Date:** 2026-04-04
**Status:** Approved
**Goal:** Eliminate the "turn tax" for background work by replacing full conversation history with plan context summaries, while keeping RAG, experiences, and entity knowledge.

## Context

Currently every heartbeat step (plan execution, todo execution) calls `agent.handle_message()`, which runs the full `ContextAssembler.build()` — fetching 20 messages of conversation history, full RAG, entity lookup, etc. For a 10-step plan, this means resending ~2000 tokens of chat history 10 times. The agent doesn't need chat history for background work — it needs the plan context.

Infrastructure already in place:
- Plan execution in heartbeat (plans.py calls `agent.handle_message()`)
- Todo execution in heartbeat (todos.py calls `agent.handle_message()`)
- `background_model` config on Heartbeat (already passed, not used for plans/todos)
- `task_plans` table with goal, steps, results
- `heartbeat_sessions` table for logging

## Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| What to skip | Full conversation history only | RAG, experiences, entities are useful for background work |
| What to replace with | Plan context summary (goal + completed steps + current step) | Structured, ~300 tokens vs ~2000 for history. Built from DB, no LLM call. |
| Model | Use `background_model` if configured, else main model | User controls cost/quality tradeoff via config |
| Opt-in mechanism | `headless=True` flag on handle_message | Plans and todos opt in; chat stays unchanged |

## Design

### 1. Plan Context Summary Builder

**New function in:** `odigos/core/heartbeat/plans.py`

Builds a structured summary from the `task_plans` table for injection into headless context:

```python
async def build_plan_summary(db, plan_id: str) -> str:
    """Build a plan context summary for headless execution."""
    plan = await db.fetch_one("SELECT * FROM task_plans WHERE id = ?", (plan_id,))
    if not plan:
        return ""

    import json
    steps = json.loads(plan.get("steps", "[]"))
    goal = plan.get("goal", "")

    lines = [f"## Task Context", f"Goal: {goal}"]

    completed = [s for s in steps if s.get("status") == "done"]
    pending = [s for s in steps if s.get("status") != "done"]

    lines.append(f"Plan: {len(steps)} steps, {len(completed)} completed")

    if completed:
        lines.append("Completed:")
        for s in completed[-5:]:  # Last 5 completed steps (cap tokens)
            result_preview = (s.get("result") or "")[:200]
            lines.append(f"- Step {s.get('step', '?')}: {s.get('task', '')} ({result_preview})")

    if pending:
        current = pending[0]
        lines.append(f"\nCurrent step: Step {current.get('step', '?')} — {current.get('task', '')}")

    return "\n".join(lines)
```

Output (~200-400 tokens):
```
## Task Context
Goal: Analyze these 50 PDFs and create a summary report
Plan: 6 steps, 3 completed
Completed:
- Step 1: Listed all PDF files (found 50 files)
- Step 2: Extracted text from first 25 PDFs (saved to /tmp/extracted/)
- Step 3: Extracted text from remaining 25 PDFs (saved to /tmp/extracted/)

Current step: Step 4 — Analyze extracted text for key themes
```

### 2. Headless Context Builder

**New method in:** `odigos/core/context.py` — `ContextAssembler.build_headless()`

```python
async def build_headless(
    self, step_description: str, plan_context: str = "",
) -> list[dict]:
    """Build minimal context for headless heartbeat execution.

    Keeps: RAG (queried against step), experiences, entities, user profile
    Replaces: Conversation history → plan context summary
    Skips: Full history fetch, page context, recovery briefing, skill catalog
    """
```

What it does:
1. Runs RAG recall with `step_description` as the query (finds relevant documents/memories)
2. Runs experience retrieval (XSkill — classification can be inferred or defaulted to "complex")
3. Runs entity context (GraphRAG against step description)
4. Builds system prompt with: agent personality + plan_context + RAG + experiences + entities
5. Returns message list: `[{"role": "system", "content": ...}, {"role": "user", "content": step_description}]`

What it skips:
- `_conversation_history()` — replaced by plan_context
- `_recovery_briefing()` — the plan_context IS the recovery briefing
- `_skill_catalog()` — not needed for individual steps
- `_page_context()` — no page in headless mode
- `_memory_index()` — not needed

Token estimate: ~800-1200 tokens total (vs ~3000-5000 for full context build).

### 3. Agent/Executor Headless Flag

**Modified:** `odigos/core/executor.py` (or `agent.py`, wherever `handle_message` routes to executor)

The executor's `execute()` method needs to accept headless parameters:

```python
async def execute(
    self, ...,
    headless: bool = False,
    plan_context: str = "",
    background_model: str = "",
) -> ExecuteResult:
```

When `headless=True`:
1. Use `context_assembler.build_headless(step_description, plan_context)` instead of `build()`
2. Use `background_model` if provided, else default to main model
3. Skip reflector/entity extraction post-processing (avoid overhead for background work)

### 4. Plans.py Uses Headless Mode

**Modified:** `odigos/core/heartbeat/plans.py`

In `work_in_progress_plans()`, where it currently calls `agent.handle_message(message)`:

```python
# Before:
result = await hb.agent.handle_message(message)

# After:
plan_summary = await build_plan_summary(hb.db, plan["id"])
result = await hb.agent.handle_message(
    message,
    headless=True,
    plan_context=plan_summary,
    background_model=hb._background_model,
)
```

### 5. Todos.py Uses Headless Mode

**Modified:** `odigos/core/heartbeat/todos.py`

For scheduled todos (not user-initiated), use headless mode:

```python
result = await hb.agent.handle_message(
    message,
    headless=True,
    plan_context=f"## Task Context\nExecuting scheduled todo: {description}",
    background_model=hb._background_model,
)
```

## File Change Summary

| File | Change |
|------|--------|
| `odigos/core/context.py` | Add `build_headless()` method to ContextAssembler |
| `odigos/core/executor.py` | Accept `headless`, `plan_context`, `background_model` params |
| `odigos/core/heartbeat/plans.py` | Add `build_plan_summary()`, pass `headless=True` to agent |
| `odigos/core/heartbeat/todos.py` | Pass `headless=True` to agent for scheduled todos |

## What Doesn't Change

- Chat-initiated conversations — full context assembly as before
- `ContextAssembler.build()` — unchanged, still used for chat
- Tool execution within headless steps — same executor, same tools
- Background task polling (Phase 4b) — independent, still works
- Frontend — no changes needed

## Token Impact

| Scenario | Before | After | Savings |
|----------|--------|-------|---------|
| 10-step plan | ~30,000 tokens (history resent 10x) | ~10,000 tokens (plan summary only) | ~67% |
| Scheduled todo | ~3,000 tokens (full context) | ~1,000 tokens (minimal) | ~67% |
| Idle think (unchanged) | ~3,000 tokens | ~3,000 tokens | 0% (not headless) |
