# Sub-Agents: Async Orchestration with Scoped Specialists

**Date:** 2026-04-10
**Status:** Approved
**Group:** New — Sub-Agent Architecture

## Research References

- [npcpy](https://github.com/NPC-Worldwide/npcpy) — NPC abstraction, team orchestration, @mention delegation, file-based definitions
- [Marp](https://github.com/marp-team/marp) — Markdown-based slide generation (first concrete downstream consumer)

---

## Goal

Give the Odigos main agent the ability to orchestrate specialized, scoped, asynchronously-executed sub-agents that produce pure task-optimal output. The main agent retains personality and user awareness; sub-agents are stateless specialists with their own LLM, tools, and context isolation. This enables deep research, multi-stage workflows (research → present), and parallel task decomposition without blocking the user.

This spec also fixes a long-standing tension: **skills currently bleed personality into specialized output**. The fix is twofold: (1) improve the direct-skill framing so personality is explicitly preserved, and (2) introduce sub-agents as the preferred path when isolation is needed.

---

## Architectural Principle: Three-Layer Separation

The agent has three distinct layers, and sub-agents slot cleanly into the picture:

1. **Memory layer** — user-facing knowledge (facts, preferences, entities, tasks). Flows INTO sub-agents as `context_facts`.
2. **Self-improvement layer** — agent operational data (experiences, corrections, trial history). Never visible to sub-agents or the user.
3. **User-facing artifacts** — notifications, document notes, chat messages, sub-agent outputs. Produced by sub-agents, wrapped by the orchestrator.

**Personality lives ONLY with the orchestrator.** Sub-agents have no personality. They produce the pinnacle of their task output, and the orchestrator wraps it with voice, context, and user awareness when delivering to the user.

**Skills stay as reusable capability packages.** Sub-agents may reference a skill for their system prompt, or define ad-hoc instructions, or do both. The orchestrator can also use skills directly (without going through a sub-agent) for cases where isolation isn't needed.

---

## Section 1: Fix Skill-Personality Layering

Current behavior: when `activate_skill` runs, the skill's system prompt is appended as a system message. The main personality prompt is still present, but the LLM gravitates toward the more specific/recent skill instructions, so personality gets drowned out.

### Fix: Explicit Framing + Optional Hard Overrides

**Framing change** at `odigos/core/executor.py` in the skill activation branch:

Instead of:
```python
messages.append({
    "role": "system",
    "content": f"[Active skill instructions]:\n\n{self._pending_skill_prompt}",
})
```

Use:
```python
messages.append({
    "role": "system",
    "content": (
        "[Active skill instructions — additive, not replacing]\n\n"
        f"{self._pending_skill_prompt}\n\n"
        "These instructions add specialized capability for this task. "
        "Your persona, voice, and the user's preferences from your main "
        "system prompt still apply to how you talk about this work. "
        "When the skill's instructions conflict with the user's "
        "preferences, prefer the user's preferences unless the skill "
        "explicitly declares an override."
    ),
})
```

**Optional hard overrides** in skill frontmatter:

```yaml
---
name: legal-draft
overrides: [tone, concise_mode]   # NEW: suppress these personality aspects
---
```

When a skill with `overrides` is active, the executor injects an additional suppression hint:

```python
if skill.overrides:
    suppression = ", ".join(skill.overrides)
    messages.append({
        "role": "system",
        "content": (
            f"[Override] For this task specifically, suppress the following "
            f"personality aspects: {suppression}. The skill's instructions "
            f"take priority over these."
        ),
    })
```

Skills that declare overrides:
- `legal-draft` — overrides `tone` (must be formal regardless of user casual preference)
- `songwriting` — overrides `concise_mode` (must expand creatively)
- `contract-review` — overrides `tone`
- Most skills declare no overrides and inherit user preferences naturally

### Why This Matters Even With Sub-Agents

The sub-agent path solves the layering problem by eliminating it (sub-agents have no personality to conflict with). But skills can still be activated directly by the orchestrator for lightweight cases where context is already present. The framing fix is needed for those cases.

---

## Section 2: Sub-Agent Primitive

### Module: `odigos/core/subagent.py`

```python
@dataclass
class SubagentDispatchResult:
    task_id: str
    status: str                       # 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
    result: str | None = None         # populated only when wait_for_result=True
    artifact_path: str | None = None  # if the sub-agent produced an artifact
    error: str | None = None
    duration_ms: int | None = None
    cost_usd: float | None = None


async def run_subagent(
    task: str,
    *,
    persona: str | None = None,
    skill: str | None = None,
    system_prompt: str | None = None,
    tools: list[str] | None = None,
    model: str | None = None,
    context_facts: list[str] | None = None,
    input_artifact: str | None = None,
    wait_for_result: bool = False,
    timeout_seconds: int | None = None,
    on_complete: dict | None = None,
    concurrency_key: str | None = None,
    conversation_id: str | None = None,
) -> SubagentDispatchResult:
    """Dispatch a sub-agent task.

    Args:
        task: The task description (required).
        persona: Name of a persona definition in data/subagents/.
        skill: Name of a skill to use as system prompt base.
        system_prompt: Ad-hoc system prompt (alternative to persona/skill).
        tools: Tool whitelist for this sub-agent. Defaults to empty.
        model: Model override (default, background, reasoning, or specific ID).
        context_facts: User-facing knowledge to inject (from memory layer).
        input_artifact: Current state for refinement tasks.
        wait_for_result: If True, block until complete or timeout. If False,
            dispatch async and return task_id immediately.
        timeout_seconds: Max runtime (defaults vary by mode).
        on_complete: Optional follow-up dispatch: {persona, task, input_from: 'result'}.
        concurrency_key: Optional key for grouping concurrent tasks (budget).
        conversation_id: Parent conversation for tracking/context.

    Returns:
        SubagentDispatchResult with task_id and status.
    """
```

### Two Execution Paths

**Synchronous path (`wait_for_result=True`):**
- Creates a fresh `Executor` instance with scoped config
- Runs the sub-agent inline
- Returns result directly
- Used for fast tasks (< 10s) where immediate integration is needed
- Default timeout: 30 seconds

**Asynchronous path (`wait_for_result=False`) — DEFAULT:**
- Creates a row in `tasks` table with `type='subagent'`, `status='pending'`
- Serializes the dispatch params as JSON
- Returns task_id immediately
- Heartbeat worker picks up the task and executes it
- Default timeout: 10 minutes
- On completion, creates notification + artifact + publishes WebSocket event

### Sub-Agent Execution (internal)

The worker (`_execute_subagent_task`) does:

1. Resolve system prompt:
   - If `persona` given, load from `data/subagents/{persona}.md`
   - If `skill` given, load from `SkillRegistry.get(skill)` and use its `system_prompt`
   - If `system_prompt` given, use directly
   - Combine: persona's template can reference a skill for base instructions + extra
2. Resolve tool whitelist: persona's defaults, overridden by explicit `tools` param
3. Resolve model: explicit `model` → persona default → global default
4. Create a fresh conversation in DB with `channel='subagent'`, `parent_conversation_id=conversation_id`
5. Build context facts block (markdown formatted) if provided
6. Build input artifact block if provided
7. Construct initial message: `{system: system_prompt + facts + artifact + persona constraints, user: task}`
8. Run via `Executor.execute()` with scoped tool registry (whitelist filter)
9. Capture the final response text
10. Store result in `tasks.result_json`
11. If result > 500 chars OR structured: write as an artifact, set `artifact_path`
12. Update `tasks.status = 'done'`, `completed_at = now`
13. Publish WebSocket `subagent_complete` event
14. Create notification: `{type: 'suggestion', title: 'Sub-agent task complete: {persona}', body: result[:200], metadata: {task_id, artifact_path}}`
15. If `on_complete` set: dispatch the next sub-agent with the current result as input

### Sub-Agents Cannot Recurse (V1 constraint)

A sub-agent's tool whitelist does NOT include `run_subagent`. They're leaves in the tree. The orchestrator is always the root. If we need recursive composition later, we add it deliberately with depth limits.

### Context Isolation

The sub-agent's conversation has:
- A fresh conversation_id (scoped to this task)
- No user chat history
- No orchestrator's personality sections
- No access to other conversations

The sub-agent's context has:
- The task description
- Provided context_facts (from memory layer, chosen by orchestrator)
- Provided input_artifact (for refinement tasks)
- The persona/skill system prompt

That's it. Clean isolation by construction.

---

## Section 3: Persona Library

### Directory: `data/subagents/`

Each persona is a markdown file with YAML frontmatter, same format as skills but with additional fields:

```yaml
---
name: researcher
description: Deep research specialist
model: reasoning
tools:
  - web_search
  - scrape
  - memory_recall
  - read_file
skill: null              # optional: reference an existing skill for system prompt base
max_runtime_seconds: 600
---

# Deep Research Specialist

You are a research specialist. Given a topic, produce a thorough, well-sourced
summary with clear structure.

## Rules

- Cite every non-obvious claim with its source URL or reference
- Structure: overview → key concepts → current state → open questions
- Prefer primary sources (papers, docs, official announcements) over blog posts
- When sources conflict, surface the conflict and note both positions
- Target length: 800-2000 words for normal research, up to 5000 for deep dives

## Output format

Markdown with headings. Include a "Sources" section at the end listing all
cited URLs with one-line descriptions.
```

### Seed Personas (V1)

| Persona | Model | Tools | Purpose |
|---|---|---|---|
| `researcher` | reasoning | web_search, scrape, memory_recall, read_file | Deep research with sourcing |
| `coder` | reasoning | execute_code, read_file, write_file, run_tests | Code generation and review |
| `editor` | default | read_file, write_file | Text editing and refinement |
| `presenter` | default | read_file, write_file, marp | Convert research into Marp slides |
| `analyst` | reasoning | web_search, scrape, memory_recall, calculator | Data analysis and synthesis |
| `summarizer` | background | read_file | Fast summarization of long content |

### Persona File Loading

`odigos/core/subagent.py` loads persona files from `data/subagents/` on demand. Uses a simple in-memory cache keyed by filename, invalidated on mtime change. No DB registration — persona definitions are just files.

If the persona references a skill (via `skill:` frontmatter), the skill's system_prompt is used as the base and the persona's body is appended as additional instructions.

---

## Section 4: Database Schema

### Extend `tasks` table

The `tasks` table already supports `type='background_poll'` for image/music generation. Add support for sub-agents:

```sql
-- tasks already has: id, type, status, conversation_id, tool_name,
-- external_task_id, arguments_json, result_json, error, retry_count,
-- max_retries, created_at, completed_at

-- Add new columns:
ALTER TABLE tasks ADD COLUMN persona TEXT;              -- sub-agent persona name
ALTER TABLE tasks ADD COLUMN parent_task_id TEXT;       -- for on_complete chains
ALTER TABLE tasks ADD COLUMN concurrency_key TEXT;      -- for grouping
ALTER TABLE tasks ADD COLUMN max_runtime_seconds INTEGER DEFAULT 600;
ALTER TABLE tasks ADD COLUMN cancel_requested INTEGER DEFAULT 0;
ALTER TABLE tasks ADD COLUMN started_at TEXT;           -- when worker picked it up
ALTER TABLE tasks ADD COLUMN artifact_path TEXT;        -- produced artifact location
ALTER TABLE tasks ADD COLUMN duration_ms INTEGER;       -- execution time
ALTER TABLE tasks ADD COLUMN cost_usd REAL;             -- LLM cost for this task

CREATE INDEX IF NOT EXISTS idx_tasks_type_status ON tasks(type, status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);
```

For sub-agents, `type='subagent'`. `arguments_json` contains the full dispatch params (task, persona, skill, tools, model, context_facts, input_artifact, on_complete).

### Sub-Agent Conversations

Sub-agent LLM calls use the existing `conversations` table with `channel='subagent'` and a new optional `parent_conversation_id` field:

```sql
ALTER TABLE conversations ADD COLUMN parent_conversation_id TEXT;
CREATE INDEX IF NOT EXISTS idx_conversations_parent ON conversations(parent_conversation_id);
```

This links sub-agent work back to the user conversation that spawned it. Useful for debugging and for the activity page to show "sub-agent tasks spawned by this conversation."

Migration: `migrations/009_subagents.sql`

---

## Section 5: Heartbeat Worker

### New Module: `odigos/core/heartbeat/subagent_worker.py`

Extends the existing Phase 3c background task polling pattern. Handles tasks with `type='subagent'`.

```python
MAX_CONCURRENT_SUBAGENTS = 3
SUBAGENT_POLL_LIMIT = 5  # tasks checked per heartbeat cycle


async def poll_subagent_tasks(hb) -> int:
    """Phase 3d: poll and execute pending sub-agent tasks.

    Returns number of tasks started in this cycle.
    """
```

Flow:

1. Check budget via `hb.budget_tracker`. If over limit, skip this cycle.
2. Count currently running sub-agent tasks (status='running'). If >= MAX_CONCURRENT_SUBAGENTS, skip.
3. Query for pending sub-agent tasks:
   ```sql
   SELECT * FROM tasks
   WHERE type='subagent' AND status='pending'
     AND (cancel_requested = 0)
   ORDER BY created_at ASC
   LIMIT ?
   ```
4. For each task (respecting the concurrency limit):
   - Mark `status='running'`, `started_at=now`
   - Create an asyncio task to execute it via `_execute_subagent_task(hb, task_row)`
   - Don't await — let it run in the background
   - Track the asyncio.Task in a module-level dict for cancellation
5. Return count of started tasks

The executor function:
```python
async def _execute_subagent_task(hb, task_row: dict) -> None:
    """Execute a single sub-agent task and update its status."""
    try:
        params = json.loads(task_row['arguments_json'])
        timeout = task_row.get('max_runtime_seconds', 600)

        result = await asyncio.wait_for(
            _run_subagent_inline(hb, params),
            timeout=timeout,
        )

        # Store result + optional artifact
        await _store_result(hb.db, task_row['id'], result)

        # Publish completion
        await hb.message_bus.publish({
            'type': 'subagent_complete',
            'task_id': task_row['id'],
            'persona': params.get('persona'),
            'artifact_path': result.get('artifact_path'),
        })

        # Create notification
        await hb.notifier.create(...)

        # Handle on_complete chaining
        if params.get('on_complete'):
            await _dispatch_chained_subagent(hb.db, task_row, result, params['on_complete'])

    except asyncio.TimeoutError:
        await hb.db.execute(
            "UPDATE tasks SET status='failed', error='timeout' WHERE id=?",
            (task_row['id'],),
        )
    except Exception as exc:
        logger.exception("Sub-agent task failed: %s", task_row['id'][:8])
        await hb.db.execute(
            "UPDATE tasks SET status='failed', error=? WHERE id=?",
            (str(exc)[:500], task_row['id']),
        )
```

### Heartbeat Integration

Add Phase 3d (after Phase 3c background task polling):

```python
# Phase 3d: Sub-agent task execution
try:
    from odigos.core.heartbeat import subagent_worker
    started = await subagent_worker.poll_subagent_tasks(self)
    if started > 0:
        logger.info("Sub-agent worker: started %d tasks", started)
except Exception:
    logger.debug("Sub-agent worker failed", exc_info=True)
```

### Concurrency & Resource Management

- **MAX_CONCURRENT_SUBAGENTS = 3** — bounded parallelism
- **Budget gating** — if budget is at danger threshold, new tasks are not started (but existing ones continue)
- **Timeout** — per-task timeout via `asyncio.wait_for`
- **Cancellation** — `cancel_requested=1` marks the task; worker checks before starting, active tasks are cancelled via stored asyncio.Task reference
- **Retry** — failed sub-agent tasks are NOT auto-retried (different from network tasks). User can manually retry via API if needed.

---

## Section 6: On-Complete Chaining

When a sub-agent task completes, the worker checks for an `on_complete` field in the task's dispatch params. If present, it dispatches a follow-up sub-agent automatically.

### Chain Specification

```python
on_complete = {
    "persona": "presenter",              # next persona
    "task": "Turn this research into a 5-slide Marp deck",
    "input_from": "result",              # 'result' or 'artifact'
    "tools": None,                       # optional override
    "model": None,                       # optional override
    "on_complete": {...},                # chains can nest (V2)
    "notify_user_on_final": True,        # suppress intermediate notifications
}
```

### Flow

1. Researcher sub-agent completes with result `"<markdown research report>"`
2. Worker sees `on_complete` field in the researcher's task params
3. Worker creates a new task row: `type='subagent'`, `status='pending'`, `parent_task_id=<researcher's id>`, `arguments_json=<presenter params with input_artifact=researcher's result>`
4. If `notify_user_on_final=True`, suppress the researcher's completion notification (user only hears when the whole chain is done)
5. Next heartbeat cycle picks up the presenter task
6. Presenter produces a Marp deck artifact
7. Since presenter has no `on_complete`, this is the final step
8. User notification: "Research + primer ready: {artifact_link}"

### Chain Limits

- **Max chain depth: 5** — prevents runaway chains
- **Total chain budget** — respected via the existing budget tracker; each task in the chain consumes from the same pool
- **Chain cancellation** — cancelling a parent task cancels all descendants

---

## Section 7: Main Agent Integration

### New Tool: `run_subagent`

Exposed to the main agent's tool registry:

```python
class RunSubagentTool(BaseTool):
    name = "run_subagent"
    category = "orchestration"
    description = (
        "Dispatch a specialized sub-agent to handle a scoped task. "
        "Use for research, heavy analysis, content generation, or any task "
        "that benefits from a fresh context and specialized tools. "
        "By default runs asynchronously — the main agent responds to the user "
        "immediately and the sub-agent's result is delivered via notification "
        "when complete. Set wait_for_result=True for fast tasks where you need "
        "the result in the current turn."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "What the sub-agent should do"},
            "persona": {
                "type": "string",
                "description": "Persona name (researcher, coder, editor, presenter, analyst, summarizer)",
            },
            "wait_for_result": {
                "type": "boolean",
                "description": "If true, block until complete (max 30s). Default false.",
            },
            "context_facts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "User facts to pass to the sub-agent (from memory)",
            },
            "input_artifact": {
                "type": "string",
                "description": "Current state (for refinement tasks)",
            },
            "on_complete": {
                "type": "object",
                "description": "Optional follow-up dispatch for chaining",
            },
        },
        "required": ["task", "persona"],
    }
```

### New Tool: `run_parallel_subagents`

Convenience wrapper for dispatching multiple sub-agents at once:

```python
class RunParallelSubagentsTool(BaseTool):
    name = "run_parallel_subagents"
    category = "orchestration"
    description = (
        "Dispatch multiple sub-agents in parallel. Each runs independently with "
        "its own fresh context. All are dispatched asynchronously — results "
        "arrive via notifications as each completes."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "persona": {"type": "string"},
                        "context_facts": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["task", "persona"],
                },
                "description": "List of sub-agent dispatches",
            },
        },
        "required": ["tasks"],
    }
```

Returns: `{task_ids: [...], dispatched: N}`

### Status Query Tool

```python
class SubagentStatusTool(BaseTool):
    name = "subagent_status"
    description = "Check the status of a dispatched sub-agent task by task_id."
    # Returns: {task_id, status, result?, artifact_path?, error?}
```

Lets the main agent check on dispatched tasks if the user asks ("is the research done yet?").

### Cancellation

```python
class CancelSubagentTool(BaseTool):
    name = "cancel_subagent"
    description = "Cancel a running or pending sub-agent task."
```

---

## Section 8: Marp Tool + Research-Present Workflow

### Module: `odigos/tools/marp_tool.py`

Extends the existing `CLITool` base class.

```python
class MarpTool(CLITool):
    name = "marp"
    category = "media"
    description = (
        "Render Markdown slides into PDF, PPTX, or HTML using marp-cli. "
        "Input must be marp-compatible markdown (--- separators for slides, "
        "optional YAML frontmatter for theme)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "input_markdown": {"type": "string"},
            "output_format": {
                "type": "string",
                "enum": ["pdf", "pptx", "html", "png"],
                "default": "pdf",
            },
            "theme": {
                "type": "string",
                "description": "Marp theme (default, gaia, uncover)",
                "default": "default",
            },
        },
        "required": ["input_markdown"],
    }

    async def execute(self, params: dict) -> ToolResult:
        # Write input to temp file
        # Run: marp {input} -o {output} --theme {theme}
        # Return artifact path
```

Requires `@marp-team/marp-cli` installed in the container (add to Dockerfile).

### Research-Present Workflow

User request: "Make me a 5-slide primer on LLM memory architectures."

1. Main agent recognizes: research + present workflow
2. Dispatches:
   ```python
   run_subagent(
       task="Research the current state of LLM memory architectures - key papers, approaches, and open questions",
       persona="researcher",
       wait_for_result=False,
       on_complete={
           "persona": "presenter",
           "task": "Turn this research into a 5-slide Marp deck suitable for a technical audience",
           "input_from": "result",
           "notify_user_on_final": True,
       },
   )
   ```
3. Main responds immediately: "On it. I'll research LLM memory architectures and draft a 5-slide primer. I'll ping you when it's ready — probably a few minutes."
4. Heartbeat picks up the researcher task
5. Researcher runs with reasoning model, uses web_search/scrape/memory_recall
6. Produces a markdown research report with citations
7. Worker sees `on_complete`, dispatches the presenter task with researcher's output as input_artifact
8. Heartbeat picks up the presenter task
9. Presenter uses the marp tool to render the slides
10. Artifact saved: `data/artifacts/primer-llm-memory-2026-04-10.pdf`
11. Notification created: "Primer ready: LLM memory architectures"
12. User clicks the notification, views the artifact
13. If user wants changes, they chat: "Make slide 3 more detailed" → main dispatches a new presenter task with the current PDF as input_artifact and the edit request

---

## Section 9: Migration — Replace `activate_skill` Where Appropriate?

**Keep `activate_skill` as-is.** The skill-personality framing fix (Section 1) makes direct skill activation work better. Sub-agents are an additional capability for when isolation is needed.

**Existing skills don't change.** The skill registry, skill files, and code skill runners all stay the same. Personas in `data/subagents/` are a new concept that can optionally reference skills.

**The orchestrator learns to use both:**
- Direct skill activation for lightweight mode shifts with full context
- Sub-agent dispatch for isolation, heavy work, and parallel decomposition

The `run_subagent` tool becomes available alongside `activate_skill`. The main agent decides per-task which to use, guided by a new entry in `data/agent/capabilities.md` (the personality section that describes the orchestrator's operational modes):

> **When to activate a skill vs. dispatch a sub-agent:**
>
> Use `activate_skill` for quick specialized responses where you already have the full user context (draft an email, summarize what we discussed, format something). The skill's instructions layer on top of your persona for one turn.
>
> Use `run_subagent` for heavy work (research, large content generation, complex analysis), parallel decomposition, or anything that benefits from a fresh context. By default sub-agents run asynchronously — respond to the user immediately with "on it" and the result will arrive via notification. Set `wait_for_result=True` only for fast tasks (< 10 seconds) where you need the result in the current turn.
>
> When a sub-agent produces output, YOU deliver it to the user with your voice and context. The sub-agent produces the pinnacle of the specialized task; you provide the warmth, the framing, and the user-aware commentary.

This rubric gets added to `data/agent/capabilities.md` as part of the V1 ship so the orchestrator knows how to choose.

---

## Section 10: New/Modified Files

### New Files

| File | Purpose |
|------|---------|
| `odigos/core/subagent.py` | `run_subagent()` function, `SubagentDispatchResult` dataclass |
| `odigos/core/heartbeat/subagent_worker.py` | Phase 3d worker: poll, execute, chain, cancel |
| `odigos/tools/subagent_tools.py` | `RunSubagentTool`, `RunParallelSubagentsTool`, `SubagentStatusTool`, `CancelSubagentTool` |
| `odigos/tools/marp_tool.py` | `MarpTool` extending CLITool |
| `data/subagents/researcher.md` | Deep research persona |
| `data/subagents/coder.md` | Code specialist persona |
| `data/subagents/editor.md` | Text editor persona |
| `data/subagents/presenter.md` | Marp slide generator persona |
| `data/subagents/analyst.md` | Data analysis persona |
| `data/subagents/summarizer.md` | Fast summarizer persona |
| `migrations/009_subagents.sql` | Task table extensions, conversation parent_id |
| `tests/test_subagent.py` | Sub-agent dispatch + execution tests |
| `tests/test_subagent_worker.py` | Heartbeat worker + chaining tests |
| `tests/test_marp_tool.py` | Marp rendering smoke test |

### Modified Files

| File | Change |
|------|--------|
| `schema.sql` | Add task extension columns, conversations.parent_conversation_id |
| `odigos/core/executor.py` | Fix skill activation framing (Section 1) + inject override suppression |
| `odigos/skills/registry.py` | Add `overrides` field to Skill dataclass |
| `odigos/core/heartbeat/orchestrator.py` | Add Phase 3d call to subagent_worker |
| `odigos/bootstrap.py` | Register new tools, wire subagent worker dependencies |
| `odigos/tools/__init__.py` or similar | Register new tools |
| `Dockerfile` | Install `@marp-team/marp-cli` globally |
| `skills/legal-draft.md` | Add `overrides: [tone]` |
| `skills/songwriting.md` | Add `overrides: [concise_mode]` |
| `skills/contract-review.md` | Add `overrides: [tone]` |
| `data/agent/capabilities.md` | Add the activate_skill vs run_subagent rubric |

---

## Section 11: Frontend (optional, not required for V1)

The existing notification system delivers sub-agent completion messages. Users can view results via the activity page. No new frontend work is strictly required.

Nice-to-haves (defer):
- Activity page hero gets a "Running sub-agents (N)" indicator
- Sub-agent task list under activity page with status, progress, cancel buttons
- Sub-agent cancel button wired through a new API endpoint

These can ship as a Phase 6 follow-up after the backend is proven.

---

## Section 12: Deliberately NOT in V1

- **Sub-agent recursion** — sub-agents cannot invoke other sub-agents. Only the orchestrator can dispatch. Revisit when a concrete need appears.
- **Peer sub-agents** — Florence, Jessica, Rachel don't become sub-agents yet. They stay as separate peer deployments. Future mesh work may unify them.
- **Sub-agent memory** — sub-agents don't persist their own memories. If a sub-agent learns something important, the orchestrator observes its output and decides what to store.
- **Sub-agent self-improvement** — sub-agents don't trigger prompt evolution on themselves. They use static persona definitions. The existing skill verifier may verify them during skill creation, but there's no in-flight learning loop.
- **Dynamic persona creation** — personas are file-based. Agent-created personas (via a `create_subagent` tool) are deferred until we know what patterns are worth naming.
- **Cross-session sub-agent conversations** — each sub-agent task is a fresh conversation. No continuity across dispatches. State is managed by the orchestrator via artifacts.
- **Sub-agent UI panel** — activity page enhancements deferred.
- **Inter-sub-agent communication** — sub-agents in a parallel dispatch don't talk to each other. They run independently. If collaboration is needed, the orchestrator mediates via `on_complete` chains.

---

## Success Metrics

This feature is successful if:

- Users dispatch long-running tasks ("research X and make slides") and receive completed artifacts via notification without blocking their chat flow
- The orchestrator's chat responses remain concise and personality-driven even when heavy specialized work is happening in the background
- Parallel sub-agent dispatch produces meaningfully faster results than sequential work (measurable on research + present workflows)
- The skill-personality tension is visibly fixed — users report that formal/technical skill outputs (legal, code, research) now feel appropriately clinical while conversational framing remains warm
- Budget tracking correctly accounts for sub-agent work; budget exhaustion gracefully pauses new dispatches
- Marp presentations are produced end-to-end without manual intervention

## Risk Mitigation

- **Runaway cost** → concurrency cap (3) + budget gating + per-task timeout (10 min default)
- **Hung sub-agents** → asyncio.wait_for timeout, marked failed if exceeded
- **Hallucinated chains** → max chain depth (5), chain cancellation cascades
- **Tool whitelist bypass** → sub-agent Executor filters the tool registry at construction time; sub-agent cannot call tools outside its whitelist
- **Context pollution** → fresh conversation per sub-agent, no access to user history or other conversations
- **Lost results on crash** → tasks table persists state; heartbeat restart picks up interrupted work (pending and running tasks → retry pending, failed running tasks marked failed with "interrupted")
