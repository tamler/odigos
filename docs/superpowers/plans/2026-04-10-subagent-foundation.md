# Sub-Agent Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the sub-agent orchestration foundation — the orchestrator can dispatch scoped specialist LLM calls with their own persona, tools, model, and isolated context. Async-by-default with heartbeat worker, on_complete/on_failure chaining, tool whitelist enforcement, filesystem sandboxing, and a fix for the existing skill-personality layering bug.

**Architecture:** Extends the existing `tasks` table with sub-agent columns, adds a new heartbeat phase that polls and executes pending sub-agent tasks via asyncio, exposes new orchestration tools (`run_subagent`, `run_parallel_subagents`, `subagent_status`, `cancel_subagent`). Personas live as markdown files in `data/subagents/`. Sub-agents run in scoped Executor instances with filtered tool registries and workspace-rooted file tools.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, asyncio.gather, existing Executor class, existing ResourceStore pattern, existing heartbeat phase architecture.

**Spec:** `docs/superpowers/specs/2026-04-10-subagents-orchestration-design.md`

**Note:** This plan covers sub-agent foundation ONLY. The Marp tool + research-present demonstration workflow is a separate plan, built on top of this one after it ships.

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `migrations/009_subagents.sql` | Extend tasks table, add conversations.parent_conversation_id |
| `odigos/core/subagent.py` | `run_subagent()`, `SubagentDispatchResult`, `SubagentParams` dataclass, persona loading, tool resolution |
| `odigos/core/heartbeat/subagent_worker.py` | `poll_subagent_tasks()`, `_execute_subagent_task()`, retry + chaining logic |
| `odigos/tools/subagent_tools.py` | `RunSubagentTool`, `RunParallelSubagentsTool`, `SubagentStatusTool`, `CancelSubagentTool` |
| `data/subagents/researcher.md` | Deep research persona |
| `data/subagents/coder.md` | Code specialist persona |
| `data/subagents/editor.md` | Text editor persona |
| `data/subagents/analyst.md` | Data analysis persona |
| `data/subagents/summarizer.md` | Fast summarizer persona |
| `tests/test_subagent.py` | Sub-agent primitive + persona loader tests |
| `tests/test_subagent_worker.py` | Heartbeat worker + retry + chaining tests |
| `tests/test_subagent_tools.py` | Orchestration tool tests |

### Modified Files

| File | Change |
|------|--------|
| `schema.sql` | Add task extension columns and conversations.parent_conversation_id |
| `odigos/core/executor.py` | Fix skill activation framing (Section 1 of spec) + scoped executor factory |
| `odigos/skills/registry.py` | Add `overrides` field to Skill dataclass |
| `odigos/core/heartbeat/orchestrator.py` | Register Phase 3d: subagent_worker |
| `odigos/bootstrap.py` | Register new tools, wire dependencies |
| `skills/legal-draft.md` | Add `overrides: [tone]` |
| `skills/songwriting.md` | Add `overrides: [concise_mode]` |
| `skills/contract-review.md` | Add `overrides: [tone]` |
| `data/agent/capabilities.md` | Add activate_skill vs run_subagent rubric |

---

### Task 1: Skill-Personality Framing Fix

**Files:**
- Modify: `odigos/core/executor.py` (skill activation block around line 509)
- Modify: `odigos/skills/registry.py` (Skill dataclass)
- Modify: `skills/legal-draft.md`, `skills/songwriting.md`, `skills/contract-review.md`
- Test: `tests/test_skill_framing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_skill_framing.py`:

```python
"""Tests for skill activation framing and overrides."""
from __future__ import annotations

from odigos.skills.registry import Skill


def _make_skill(name: str = "test", overrides: list[str] | None = None) -> Skill:
    return Skill(
        name=name,
        description="Test skill",
        tools=[],
        complexity="standard",
        system_prompt="You are a test specialist.",
        overrides=overrides or [],
    )


class TestSkillOverridesField:
    def test_skill_has_overrides_field(self):
        skill = _make_skill()
        assert skill.overrides == []

    def test_skill_overrides_accepts_list(self):
        skill = _make_skill(overrides=["tone", "concise_mode"])
        assert skill.overrides == ["tone", "concise_mode"]


class TestSkillFramingInjection:
    def test_framing_wrapper_preserves_personality(self):
        """The skill activation message should explicitly say personality still applies."""
        from odigos.core.executor import _build_skill_activation_message

        msg = _build_skill_activation_message("You are a legal expert.", overrides=[])
        assert "additive" in msg.lower() or "still apply" in msg.lower()
        assert "You are a legal expert." in msg

    def test_framing_with_overrides_suppresses(self):
        """When overrides are present, the message lists which personality aspects to suppress."""
        from odigos.core.executor import _build_skill_activation_message

        msg = _build_skill_activation_message(
            "You are a formal legal expert.", overrides=["tone", "concise_mode"]
        )
        assert "suppress" in msg.lower() or "override" in msg.lower()
        assert "tone" in msg
        assert "concise_mode" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_skill_framing.py -x -q`
Expected: FAIL — `Skill.overrides` doesn't exist, `_build_skill_activation_message` doesn't exist.

- [ ] **Step 3: Add overrides field to Skill**

In `odigos/skills/registry.py`, add to the Skill dataclass (after `escalation_level: int = 0`):

```python
    overrides: list[str] = field(default_factory=list)
```

Also update the `_parse_skill` method in `SkillRegistry` to load `overrides` from YAML frontmatter:

```python
# in _parse_skill, where other fields are loaded from the frontmatter dict:
overrides=frontmatter.get("overrides", []) or [],
```

Don't forget to add `from dataclasses import field` to imports if it's not already there.

- [ ] **Step 4: Add framing helper to executor**

In `odigos/core/executor.py`, add this function at module level (before the `Executor` class):

```python
def _build_skill_activation_message(skill_prompt: str, overrides: list[str]) -> str:
    """Build the system message that injects an active skill.

    The framing is explicit about the skill being additive to the main
    personality, not replacing it. When overrides are present, those
    personality aspects are explicitly suppressed for this task.
    """
    base = (
        "[Active skill instructions — additive, not replacing]\n\n"
        f"{skill_prompt}\n\n"
        "These instructions add specialized capability for this task. "
        "Your persona, voice, and the user's preferences from your main "
        "system prompt still apply to how you talk about this work. "
        "When the skill's instructions conflict with the user's "
        "preferences, prefer the user's preferences unless the skill "
        "explicitly declares an override."
    )
    if overrides:
        suppression = ", ".join(overrides)
        base += (
            f"\n\n[Override] For this task specifically, suppress the "
            f"following personality aspects: {suppression}. The skill's "
            f"instructions take priority over these."
        )
    return base
```

- [ ] **Step 5: Wire the helper into skill activation**

In `odigos/core/executor.py`, find the existing skill activation block (around line 509):

```python
# Check for skill activation -- inject system message
if self._pending_skill_prompt:
    messages.append({
        "role": "system",
        "content": f"[Active skill instructions]:\n\n{self._pending_skill_prompt}",
    })
    self._pending_skill_prompt = None
```

Replace with:

```python
# Check for skill activation -- inject system message with personality-preserving framing
if self._pending_skill_prompt:
    overrides = getattr(self, "_pending_skill_overrides", [])
    messages.append({
        "role": "system",
        "content": _build_skill_activation_message(
            self._pending_skill_prompt, overrides,
        ),
    })
    self._pending_skill_prompt = None
    self._pending_skill_overrides = []
```

In the `Executor.__init__` method, add the tracking attribute near the other skill tracking:

```python
self._pending_skill_overrides: list[str] = []
```

In the `_reset_turn_state` or equivalent cleanup method, add:

```python
self._pending_skill_overrides = []
```

- [ ] **Step 6: Populate overrides during activation**

Find the block that handles skill activation side effects (around line 749):

```python
if result.side_effect and result.side_effect.get("skill_activation"):
    self._active_skill_name = result.side_effect["skill_name"]
    self._active_skill_tools = set(result.side_effect.get("skill_tools", []))
    self._pending_skill_prompt = result.side_effect["skill_prompt"]
```

Add:

```python
    self._pending_skill_overrides = result.side_effect.get("skill_overrides", [])
```

Then update `odigos/tools/skill_tool.py` `ActivateSkillTool.execute()` to include overrides in the side_effect:

```python
# in ActivateSkillTool.execute, where the side_effect dict is built:
return ToolResult(
    success=True,
    data=f"Skill '{skill.name}' activated.",
    side_effect={
        "skill_activation": True,
        "skill_name": skill.name,
        "skill_prompt": skill.system_prompt,
        "skill_tools": skill.tools,
        "skill_overrides": skill.overrides,
    },
)
```

- [ ] **Step 7: Add overrides to the three skills that need them**

Edit `skills/legal-draft.md` — add to the YAML frontmatter:

```yaml
overrides: [tone]
```

Edit `skills/songwriting.md` — add:

```yaml
overrides: [concise_mode]
```

Edit `skills/contract-review.md` — add:

```yaml
overrides: [tone]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_skill_framing.py -v`
Expected: PASS (4 tests).

Also run existing skill tests for regressions:
`python3 -m pytest tests/test_skill_maturity.py -v`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add odigos/skills/registry.py odigos/core/executor.py odigos/tools/skill_tool.py \
       skills/legal-draft.md skills/songwriting.md skills/contract-review.md \
       tests/test_skill_framing.py
git commit -m "fix(skills): preserve personality when activating skills + overrides field"
```

---

### Task 2: Schema Migration for Sub-Agents

**Files:**
- Modify: `schema.sql`
- Create: `migrations/009_subagents.sql`
- Test: `tests/test_subagent.py` (schema portion)

- [ ] **Step 1: Write the failing test**

Create `tests/test_subagent.py`:

```python
"""Tests for sub-agent primitive and schema."""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio

from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


class TestSubagentSchema:
    async def test_tasks_table_has_subagent_columns(self, db):
        task_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO tasks (id, type, status, persona, concurrency_key, "
            "max_runtime_seconds, cancel_requested, started_at, artifact_path, "
            "duration_ms, cost_usd, parent_task_id, arguments_json) "
            "VALUES (?, 'subagent', 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id, "researcher", "default", 600, 0,
                None, None, None, None, None, '{"task": "test"}',
            ),
        )
        row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        assert row is not None
        assert row["type"] == "subagent"
        assert row["persona"] == "researcher"
        assert row["concurrency_key"] == "default"
        assert row["max_runtime_seconds"] == 600
        assert row["cancel_requested"] == 0

    async def test_conversations_has_parent_conversation_id(self, db):
        parent_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (parent_id, "chat"),
        )
        await db.execute(
            "INSERT INTO conversations (id, channel, parent_conversation_id) "
            "VALUES (?, ?, ?)",
            (child_id, "subagent", parent_id),
        )
        row = await db.fetch_one(
            "SELECT parent_conversation_id FROM conversations WHERE id = ?",
            (child_id,),
        )
        assert row["parent_conversation_id"] == parent_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent.py::TestSubagentSchema -x -q`
Expected: FAIL — columns don't exist.

- [ ] **Step 3: Update schema.sql**

Find the `tasks` table definition in `schema.sql` (around line 248). Add these columns after the existing ones:

```sql
    persona TEXT,
    parent_task_id TEXT,
    concurrency_key TEXT DEFAULT 'default',
    max_runtime_seconds INTEGER DEFAULT 600,
    cancel_requested INTEGER DEFAULT 0,
    started_at TEXT,
    artifact_path TEXT,
    duration_ms INTEGER,
    cost_usd REAL,
```

Add index at the bottom of the tasks section:

```sql
CREATE INDEX IF NOT EXISTS idx_tasks_type_status ON tasks(type, status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);
```

Find the `conversations` table definition. Add a column:

```sql
    parent_conversation_id TEXT,
```

And an index:

```sql
CREATE INDEX IF NOT EXISTS idx_conversations_parent ON conversations(parent_conversation_id);
```

- [ ] **Step 4: Create the migration**

Create `migrations/009_subagents.sql`:

```sql
-- Extend tasks table for sub-agent support
ALTER TABLE tasks ADD COLUMN persona TEXT;
ALTER TABLE tasks ADD COLUMN parent_task_id TEXT;
ALTER TABLE tasks ADD COLUMN concurrency_key TEXT DEFAULT 'default';
ALTER TABLE tasks ADD COLUMN max_runtime_seconds INTEGER DEFAULT 600;
ALTER TABLE tasks ADD COLUMN cancel_requested INTEGER DEFAULT 0;
ALTER TABLE tasks ADD COLUMN started_at TEXT;
ALTER TABLE tasks ADD COLUMN artifact_path TEXT;
ALTER TABLE tasks ADD COLUMN duration_ms INTEGER;
ALTER TABLE tasks ADD COLUMN cost_usd REAL;

CREATE INDEX IF NOT EXISTS idx_tasks_type_status ON tasks(type, status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);

-- Add parent_conversation_id to conversations
ALTER TABLE conversations ADD COLUMN parent_conversation_id TEXT;
CREATE INDEX IF NOT EXISTS idx_conversations_parent ON conversations(parent_conversation_id);
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent.py::TestSubagentSchema -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add schema.sql migrations/009_subagents.sql tests/test_subagent.py
git commit -m "feat(subagents): schema extensions for sub-agent tasks and parent conversations"
```

---

### Task 3: Persona Loader + Validation

**Files:**
- Create: `odigos/core/subagent.py` (persona loading portion)
- Create: `data/subagents/researcher.md`
- Create: `data/subagents/coder.md`
- Create: `data/subagents/editor.md`
- Create: `data/subagents/analyst.md`
- Create: `data/subagents/summarizer.md`
- Test: `tests/test_subagent.py` (persona loader portion)

- [ ] **Step 1: Create the five persona files**

Create `data/subagents/researcher.md`:

```markdown
---
name: researcher
description: Deep research specialist
model: reasoning
tools: [web_search, scrape, memory_recall, read_file]
max_runtime_seconds: 600
---

# Deep Research Specialist

You are a research specialist. Given a topic, produce a thorough, well-sourced summary with clear structure.

## Rules

- Cite every non-obvious claim with its source URL or reference
- Structure: overview → key concepts → current state → open questions
- Prefer primary sources (papers, docs, official announcements) over blog posts
- When sources conflict, surface the conflict and note both positions
- Target length: 800-2000 words for normal research, up to 5000 for deep dives

## Output format

Markdown with headings. Include a "Sources" section at the end listing all cited URLs with one-line descriptions.
```

Create `data/subagents/coder.md`:

```markdown
---
name: coder
description: Code generation and review specialist
model: reasoning
tools: [execute_code, read_file, write_file]
max_runtime_seconds: 900
---

# Code Specialist

You are a code specialist. Given a task, produce clean, tested, production-ready code.

## Rules

- No TODO or FIXME comments — implement completely or mark as partial explicitly
- Follow existing project conventions visible from read_file
- Write tests alongside implementation
- Use type annotations where the language supports them
- Keep functions small and focused
- Never hardcode secrets or credentials

## Output format

Return the code (with file paths as headers if multi-file) followed by a short explanation of the approach.
```

Create `data/subagents/editor.md`:

```markdown
---
name: editor
description: Text editing and refinement specialist
model: default
tools: [read_file, write_file]
max_runtime_seconds: 300
---

# Text Editor

You are a text editor. Given content and editing instructions, produce a refined version.

## Rules

- Preserve the author's voice unless instructed to change it
- Keep structural changes minimal unless requested
- Fix clarity, grammar, and flow without rewriting meaning
- Surface any ambiguities you can't resolve rather than guessing
- Track what you changed with a short summary

## Output format

The edited text, followed by a "Changes" section listing what was modified and why.
```

Create `data/subagents/analyst.md`:

```markdown
---
name: analyst
description: Data analysis and synthesis specialist
model: reasoning
tools: [web_search, scrape, memory_recall, read_file]
max_runtime_seconds: 600
---

# Data Analyst

You are a data analyst. Given data, questions, or a topic, synthesize insights with evidence.

## Rules

- Quantify claims where possible (numbers, percentages, rates)
- Note confidence level for each conclusion
- Distinguish correlation from causation explicitly
- Show your reasoning chain, not just the conclusion
- Identify what data would be needed to strengthen weak conclusions

## Output format

Structured analysis: Question → Data → Method → Findings → Confidence → Open questions
```

Create `data/subagents/summarizer.md`:

```markdown
---
name: summarizer
description: Fast summarization of long content
model: background
tools: [read_file]
max_runtime_seconds: 120
---

# Summarizer

You are a summarizer. Given long content, produce a concise summary.

## Rules

- Target length: 150-300 words unless otherwise specified
- Preserve the most important facts, numbers, and names
- Keep the original structure (if narrative, stay narrative; if technical, stay technical)
- Don't add interpretation — summarize what's there, not what it means

## Output format

Plain markdown, no headers unless the source has them. Start with a one-sentence TL;DR.
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_subagent.py`:

```python
from pathlib import Path


class TestPersonaLoader:
    def test_load_persona_researcher(self):
        from odigos.core.subagent import load_persona

        persona = load_persona("researcher", personas_dir="data/subagents")
        assert persona is not None
        assert persona.name == "researcher"
        assert persona.model == "reasoning"
        assert "web_search" in persona.tools
        assert persona.max_runtime_seconds == 600
        assert "Deep Research Specialist" in persona.system_prompt

    def test_load_persona_missing_returns_none(self):
        from odigos.core.subagent import load_persona

        persona = load_persona("nonexistent", personas_dir="data/subagents")
        assert persona is None

    def test_persona_validate_tools_referenced_in_prompt(self, tmp_path):
        """validate_persona warns when the prompt references tools not in the whitelist."""
        from odigos.core.subagent import load_persona, validate_persona

        # Create a test persona with a prompt that mentions a tool not in the whitelist
        test_file = tmp_path / "leaky.md"
        test_file.write_text(
            "---\n"
            "name: leaky\n"
            "description: Test\n"
            "model: default\n"
            "tools: [read_file]\n"
            "max_runtime_seconds: 300\n"
            "---\n"
            "\n"
            "Use write_file to save your work.\n"
        )
        persona = load_persona("leaky", personas_dir=str(tmp_path))
        known_tools = {"read_file", "write_file", "web_search"}
        warnings = validate_persona(persona, known_tools)
        assert any("write_file" in w for w in warnings)
        assert not any("read_file" in w for w in warnings)

    def test_persona_resolves_tools_union_with_skill(self, tmp_path):
        """Tool resolution: skill.tools ∪ persona.tools by default."""
        from odigos.core.subagent import resolve_tools

        persona_tools = ["web_search", "scrape"]
        skill_tools = ["memory_recall", "scrape"]  # overlap on scrape
        resolved = resolve_tools(
            persona_tools=persona_tools,
            skill_tools=skill_tools,
            explicit_tools=None,
            tools_override=False,
        )
        assert set(resolved) == {"web_search", "scrape", "memory_recall"}

    def test_persona_resolves_tools_override(self):
        """tools_override=True replaces the union with just persona.tools."""
        from odigos.core.subagent import resolve_tools

        resolved = resolve_tools(
            persona_tools=["web_search"],
            skill_tools=["memory_recall", "read_file"],
            explicit_tools=None,
            tools_override=True,
        )
        assert resolved == ["web_search"]

    def test_explicit_tools_always_wins(self):
        """Explicit tools param always wins."""
        from odigos.core.subagent import resolve_tools

        resolved = resolve_tools(
            persona_tools=["web_search"],
            skill_tools=["memory_recall"],
            explicit_tools=["calculator"],
            tools_override=False,
        )
        assert resolved == ["calculator"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent.py::TestPersonaLoader -x -q`
Expected: FAIL — `odigos.core.subagent` doesn't exist.

- [ ] **Step 4: Create the subagent module (initial version)**

Create `odigos/core/subagent.py`:

```python
"""Sub-agent primitive: scoped specialist LLM execution.

Sub-agents are stateless task-focused LLM calls with their own persona,
tool whitelist, model, and isolated context. The orchestrator dispatches
them for specialized work and delivers results with its own voice.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SubagentPersona:
    """A sub-agent persona definition loaded from data/subagents/."""
    name: str
    description: str
    model: str = "default"
    tools: list[str] = field(default_factory=list)
    max_runtime_seconds: int = 600
    skill: str | None = None
    tools_override: bool = False
    workspace_roots: list[str] = field(default_factory=list)
    system_prompt: str = ""


# Module-level cache: filename → (persona, mtime)
_persona_cache: dict[str, tuple[SubagentPersona, float]] = {}


def load_persona(name: str, personas_dir: str = "data/subagents") -> SubagentPersona | None:
    """Load a sub-agent persona from disk.

    Returns None if the persona file doesn't exist.
    Uses an mtime-keyed in-memory cache.
    """
    path = Path(personas_dir) / f"{name}.md"
    if not path.exists():
        return None

    mtime = path.stat().st_mtime
    cached = _persona_cache.get(name)
    if cached and cached[1] == mtime:
        return cached[0]

    text = path.read_text()
    frontmatter_dict: dict[str, Any] = {}
    body = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter_dict = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                logger.warning("Invalid YAML frontmatter in persona %s", name)
            body = parts[2].lstrip("\n")

    persona = SubagentPersona(
        name=frontmatter_dict.get("name", name),
        description=frontmatter_dict.get("description", ""),
        model=frontmatter_dict.get("model", "default"),
        tools=list(frontmatter_dict.get("tools") or []),
        max_runtime_seconds=int(frontmatter_dict.get("max_runtime_seconds", 600)),
        skill=frontmatter_dict.get("skill"),
        tools_override=bool(frontmatter_dict.get("tools_override", False)),
        workspace_roots=list(frontmatter_dict.get("workspace_roots") or []),
        system_prompt=body.strip(),
    )

    _persona_cache[name] = (persona, mtime)
    return persona


def validate_persona(persona: SubagentPersona, known_tool_names: set[str]) -> list[str]:
    """Check that tool names referenced in the system prompt are in the whitelist.

    Returns a list of warning messages.
    """
    warnings: list[str] = []
    whitelist = set(persona.tools)

    # Find tool references in the prompt by pattern match
    # Look for any known tool name appearing as a word in the prompt
    for tool_name in known_tool_names:
        if re.search(rf"\b{re.escape(tool_name)}\b", persona.system_prompt):
            if tool_name not in whitelist:
                warnings.append(
                    f"Persona '{persona.name}' references tool '{tool_name}' "
                    f"in its prompt but it's not in the whitelist"
                )

    return warnings


def resolve_tools(
    persona_tools: list[str],
    skill_tools: list[str],
    explicit_tools: list[str] | None,
    tools_override: bool,
) -> list[str]:
    """Resolve the sub-agent's tool whitelist.

    Precedence:
    1. If explicit_tools given, use them.
    2. If tools_override=True, use persona_tools only.
    3. Otherwise, union of skill_tools and persona_tools.
    """
    if explicit_tools is not None:
        return list(explicit_tools)
    if tools_override:
        return list(persona_tools)
    # Union, preserving order
    seen: set[str] = set()
    result: list[str] = []
    for t in list(persona_tools) + list(skill_tools):
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent.py::TestPersonaLoader -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add odigos/core/subagent.py data/subagents/ tests/test_subagent.py
git commit -m "feat(subagents): persona loader, tool resolution, validation"
```

---

### Task 4: run_subagent Dispatch + Inline Execution

**Files:**
- Modify: `odigos/core/subagent.py` (add run_subagent + SubagentDispatchResult)
- Test: `tests/test_subagent.py` (dispatch tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_subagent.py`:

```python
from unittest.mock import AsyncMock, MagicMock


class TestSubagentDispatch:
    async def test_dispatch_async_creates_pending_task(self, db):
        from odigos.core.subagent import run_subagent

        result = await run_subagent(
            task="Research LLM memory architectures",
            persona="researcher",
            wait_for_result=False,
            db=db,
        )
        assert result.task_id is not None
        assert result.status == "pending"

        # Verify task row in DB
        row = await db.fetch_one(
            "SELECT * FROM tasks WHERE id = ?", (result.task_id,),
        )
        assert row["type"] == "subagent"
        assert row["status"] == "pending"
        assert row["persona"] == "researcher"

    async def test_dispatch_stores_arguments_json(self, db):
        from odigos.core.subagent import run_subagent

        result = await run_subagent(
            task="Write a song",
            persona="editor",
            wait_for_result=False,
            context_facts=["User loves blues"],
            db=db,
        )
        row = await db.fetch_one(
            "SELECT arguments_json FROM tasks WHERE id = ?", (result.task_id,),
        )
        args = json.loads(row["arguments_json"])
        assert args["task"] == "Write a song"
        assert args["persona"] == "editor"
        assert args["context_facts"] == ["User loves blues"]

    async def test_dispatch_with_unknown_persona_fails_fast(self, db):
        from odigos.core.subagent import run_subagent

        with pytest.raises(ValueError, match="persona"):
            await run_subagent(
                task="Do something",
                persona="does_not_exist",
                wait_for_result=False,
                db=db,
            )

    async def test_dispatch_with_on_complete_chain(self, db):
        from odigos.core.subagent import run_subagent

        result = await run_subagent(
            task="Research X",
            persona="researcher",
            wait_for_result=False,
            on_complete={
                "persona": "summarizer",
                "task": "Summarize the research",
                "input_from": "result",
            },
            db=db,
        )
        row = await db.fetch_one(
            "SELECT arguments_json FROM tasks WHERE id = ?", (result.task_id,),
        )
        args = json.loads(row["arguments_json"])
        assert args["on_complete"]["persona"] == "summarizer"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent.py::TestSubagentDispatch -x -q`
Expected: FAIL — `run_subagent` doesn't exist.

- [ ] **Step 3: Add run_subagent to subagent.py**

Append to `odigos/core/subagent.py`:

```python
import json as _json
import uuid as _uuid


@dataclass
class SubagentDispatchResult:
    task_id: str
    status: str  # 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
    result: str | None = None
    artifact_path: str | None = None
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
    memory_refs: list[str] | None = None,
    input_artifact: str | None = None,
    workspace_root: str | None = None,
    wait_for_result: bool = False,
    timeout_seconds: int | None = None,
    on_complete: dict | None = None,
    on_failure: dict | None = None,
    concurrency_key: str | None = None,
    max_retries: int = 2,
    conversation_id: str | None = None,
    db=None,
    personas_dir: str = "data/subagents",
) -> SubagentDispatchResult:
    """Dispatch a sub-agent task.

    By default (wait_for_result=False), creates a pending task row and
    returns immediately. The heartbeat worker picks it up and executes.

    When wait_for_result=True, runs the sub-agent inline and returns the
    final result. Used for fast tasks (< 10s) orchestrator-internal only.
    """
    if db is None:
        raise ValueError("db is required")
    if not persona and not skill and not system_prompt:
        raise ValueError(
            "run_subagent requires at least one of: persona, skill, system_prompt"
        )

    # Validate persona exists (fail fast)
    if persona:
        loaded = load_persona(persona, personas_dir=personas_dir)
        if loaded is None:
            raise ValueError(f"Unknown persona: {persona}")

    # Build params dict for storage
    params: dict = {
        "task": task,
        "persona": persona,
        "skill": skill,
        "system_prompt": system_prompt,
        "tools": tools,
        "model": model,
        "context_facts": context_facts,
        "memory_refs": memory_refs,
        "input_artifact": input_artifact,
        "workspace_root": workspace_root,
        "timeout_seconds": timeout_seconds,
        "on_complete": on_complete,
        "on_failure": on_failure,
        "conversation_id": conversation_id,
    }

    task_id = str(_uuid.uuid4())
    resolved_concurrency = concurrency_key or "default"
    max_runtime = timeout_seconds or 600
    if persona:
        loaded = load_persona(persona, personas_dir=personas_dir)
        if loaded:
            max_runtime = timeout_seconds or loaded.max_runtime_seconds

    await db.execute(
        "INSERT INTO tasks "
        "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
        "cancel_requested, max_retries, arguments_json, conversation_id) "
        "VALUES (?, 'subagent', 'pending', ?, ?, ?, 0, ?, ?, ?)",
        (
            task_id, persona, resolved_concurrency, max_runtime,
            max_retries, _json.dumps(params), conversation_id,
        ),
    )

    return SubagentDispatchResult(task_id=task_id, status="pending")
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent.py::TestSubagentDispatch -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add odigos/core/subagent.py tests/test_subagent.py
git commit -m "feat(subagents): run_subagent dispatch with async task creation"
```

---

### Task 5: Heartbeat Worker — Execution + Concurrency

**Files:**
- Create: `odigos/core/heartbeat/subagent_worker.py`
- Create: `tests/test_subagent_worker.py`
- Modify: `odigos/core/heartbeat/orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subagent_worker.py`:

```python
"""Tests for sub-agent heartbeat worker."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


def _make_hb(db) -> MagicMock:
    hb = MagicMock()
    hb.db = db
    hb.llm_provider = AsyncMock()
    hb.background_model = "test/model"
    hb.budget_tracker = MagicMock()
    hb.budget_tracker.is_within_budget = AsyncMock(return_value=True)
    hb.notifier = MagicMock()
    hb.notifier.create = AsyncMock()
    hb.message_bus = MagicMock()
    hb.message_bus.publish = AsyncMock()
    return hb


async def _seed_pending_task(db, persona="researcher", concurrency_key="default") -> str:
    task_id = str(uuid.uuid4())
    params = {"task": "Do something", "persona": persona}
    await db.execute(
        "INSERT INTO tasks "
        "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
        "arguments_json, max_retries, retry_count) "
        "VALUES (?, 'subagent', 'pending', ?, ?, 600, ?, 2, 0)",
        (task_id, persona, concurrency_key, json.dumps(params)),
    )
    return task_id


class TestWorkerGating:
    async def test_skips_when_over_budget(self, db):
        from odigos.core.heartbeat import subagent_worker

        await _seed_pending_task(db)
        hb = _make_hb(db)
        hb.budget_tracker.is_within_budget = AsyncMock(return_value=False)

        started = await subagent_worker.poll_subagent_tasks(hb)
        assert started == 0

    async def test_skips_when_at_concurrency_limit(self, db):
        from odigos.core.heartbeat import subagent_worker

        # Seed 3 running tasks at default concurrency (limit=3)
        for _ in range(3):
            task_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO tasks "
                "(id, type, status, concurrency_key, max_runtime_seconds, "
                "arguments_json, started_at) "
                "VALUES (?, 'subagent', 'running', 'default', 600, '{}', datetime('now'))",
                (task_id,),
            )

        # Seed a pending task
        await _seed_pending_task(db, concurrency_key="default")

        hb = _make_hb(db)
        started = await subagent_worker.poll_subagent_tasks(hb)
        assert started == 0

    async def test_skips_cancelled_tasks(self, db):
        from odigos.core.heartbeat import subagent_worker

        task_id = await _seed_pending_task(db)
        await db.execute(
            "UPDATE tasks SET cancel_requested = 1 WHERE id = ?", (task_id,),
        )

        hb = _make_hb(db)
        started = await subagent_worker.poll_subagent_tasks(hb)
        assert started == 0


class TestWorkerOrphanRecovery:
    async def test_orphaned_running_task_marked_failed(self, db):
        from odigos.core.heartbeat import subagent_worker

        # Create a task that appears to have started 20 minutes ago (past timeout)
        task_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, concurrency_key, max_runtime_seconds, "
            "arguments_json, started_at) "
            "VALUES (?, 'subagent', 'running', 'default', 600, '{}', "
            "datetime('now', '-20 minutes'))",
            (task_id,),
        )

        hb = _make_hb(db)
        recovered = await subagent_worker.recover_orphaned_tasks(hb)
        assert recovered >= 1

        row = await db.fetch_one(
            "SELECT status, error FROM tasks WHERE id = ?", (task_id,),
        )
        assert row["status"] == "failed"
        assert "interrupted" in row["error"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent_worker.py -x -q`
Expected: FAIL — `subagent_worker` module doesn't exist.

- [ ] **Step 3: Create the worker module (gating + orphan recovery first)**

Create `odigos/core/heartbeat/subagent_worker.py`:

```python
"""Heartbeat Phase 3d: poll and execute sub-agent tasks."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Concurrency pools — tasks with the same key share a slot
CONCURRENCY_POOLS: dict[str, int] = {
    "default": 3,
    "research": 2,
    "fast": 5,
    "heavy": 1,
}

SUBAGENT_POLL_LIMIT = 5  # max pending tasks checked per heartbeat cycle

# Module-level task registry for cancellation
_running_tasks: dict[str, asyncio.Task] = {}


async def poll_subagent_tasks(hb) -> int:
    """Phase 3d: poll and start pending sub-agent tasks.

    Returns the number of tasks started in this cycle.
    """
    # Budget gating
    try:
        within_budget = await hb.budget_tracker.is_within_budget()
        if not within_budget:
            logger.debug("Sub-agent worker: budget exceeded, skipping")
            return 0
    except Exception:
        logger.debug("Budget check failed, assuming within budget", exc_info=True)

    # Get running task counts per concurrency pool
    running_rows = await hb.db.fetch_all(
        "SELECT concurrency_key, COUNT(*) as c FROM tasks "
        "WHERE type = 'subagent' AND status = 'running' "
        "GROUP BY concurrency_key",
    )
    running_counts: dict[str, int] = {
        r["concurrency_key"] or "default": r["c"] for r in running_rows
    }

    # Fetch pending tasks
    pending = await hb.db.fetch_all(
        "SELECT * FROM tasks WHERE type = 'subagent' AND status = 'pending' "
        "AND cancel_requested = 0 ORDER BY created_at ASC LIMIT ?",
        (SUBAGENT_POLL_LIMIT,),
    )

    if not pending:
        return 0

    started = 0
    for task_row in pending:
        key = task_row["concurrency_key"] or "default"
        limit = CONCURRENCY_POOLS.get(key, 3)
        current = running_counts.get(key, 0)
        if current >= limit:
            continue

        # Mark as running
        await hb.db.execute(
            "UPDATE tasks SET status = 'running', started_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_row["id"]),
        )
        running_counts[key] = current + 1

        # Launch the execution asynchronously
        task = asyncio.create_task(_execute_subagent_task(hb, dict(task_row)))
        _running_tasks[task_row["id"]] = task
        started += 1

    if started > 0:
        logger.info("Sub-agent worker: started %d task(s)", started)
    return started


async def recover_orphaned_tasks(hb) -> int:
    """Mark tasks that have been running past their timeout as failed.

    Called on heartbeat startup to recover from crashes.
    """
    rows = await hb.db.fetch_all(
        "SELECT id, started_at, max_runtime_seconds FROM tasks "
        "WHERE type = 'subagent' AND status = 'running'",
    )
    recovered = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        if not row["started_at"]:
            continue
        try:
            started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue

        age = (now - started).total_seconds()
        limit = (row["max_runtime_seconds"] or 600) + 60  # grace period
        if age > limit:
            await hb.db.execute(
                "UPDATE tasks SET status = 'failed', "
                "error = 'interrupted (process restart)' WHERE id = ?",
                (row["id"],),
            )
            recovered += 1

    if recovered > 0:
        logger.info("Sub-agent worker: recovered %d orphaned task(s)", recovered)
    return recovered


async def _execute_subagent_task(hb, task_row: dict) -> None:
    """Execute a single sub-agent task. Called via asyncio.create_task.

    Stub for Task 5 — full execution logic lands in Task 6.
    """
    # Task 5 minimum: mark as done immediately with a placeholder result
    # Full execution logic is added in Task 6 (LLM dispatch, tools, etc.)
    try:
        await hb.db.execute(
            "UPDATE tasks SET status = 'done', result_json = ?, "
            "completed_at = ?, duration_ms = 0 WHERE id = ?",
            (
                json.dumps({"placeholder": True}),
                datetime.now(timezone.utc).isoformat(),
                task_row["id"],
            ),
        )
    finally:
        _running_tasks.pop(task_row["id"], None)
```

- [ ] **Step 4: Run gating + orphan recovery tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent_worker.py::TestWorkerGating tests/test_subagent_worker.py::TestWorkerOrphanRecovery -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Wire worker into orchestrator**

In `odigos/core/heartbeat/orchestrator.py`, find the existing Phase 3c (background task polling) block. After it, add Phase 3d:

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

Find the heartbeat startup/init method. Add a one-time orphan recovery call there:

```python
# On startup: recover orphaned sub-agent tasks
try:
    from odigos.core.heartbeat import subagent_worker
    recovered = await subagent_worker.recover_orphaned_tasks(self)
    if recovered > 0:
        logger.info("Sub-agent worker: recovered %d orphaned tasks on startup", recovered)
except Exception:
    logger.debug("Sub-agent orphan recovery failed", exc_info=True)
```

- [ ] **Step 6: Commit**

```bash
git add odigos/core/heartbeat/subagent_worker.py odigos/core/heartbeat/orchestrator.py tests/test_subagent_worker.py
git commit -m "feat(subagents): heartbeat worker with concurrency gating and orphan recovery"
```

---

### Task 6: Full Sub-Agent Execution with Scoped Executor

**Files:**
- Modify: `odigos/core/heartbeat/subagent_worker.py` (fill in `_execute_subagent_task`)
- Modify: `odigos/core/subagent.py` (add `_build_scoped_executor` factory helper)
- Test: `tests/test_subagent_worker.py` (execution tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_subagent_worker.py`:

```python
from odigos.providers.base import LLMResponse


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=50, tokens_out=100, cost_usd=0.001,
    )


class TestWorkerExecution:
    async def test_execution_writes_result(self, db, tmp_path, monkeypatch):
        from odigos.core.heartbeat import subagent_worker

        # Seed a pending task
        task_id = str(uuid.uuid4())
        params = {
            "task": "Summarize this",
            "persona": "summarizer",
            "context_facts": [],
        }
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json, max_retries, retry_count) "
            "VALUES (?, 'subagent', 'pending', 'summarizer', 'default', 300, ?, 2, 0)",
            (task_id, json.dumps(params)),
        )

        hb = _make_hb(db)
        hb.llm_provider.complete = AsyncMock(
            return_value=_make_llm_response("TL;DR: This is a summary."),
        )

        # Monkeypatch subagent.py personas_dir
        from odigos.core import subagent as subagent_mod
        original_cwd_dir = "data/subagents"
        # We'll rely on the real data/subagents dir in repo root

        # Patch the execution helper to use the mock LLM directly
        async def mock_execute_inline(hb, params, task_id, workspace_root):
            return {
                "result": "TL;DR: This is a summary.",
                "artifact_path": None,
                "duration_ms": 100,
                "cost_usd": 0.001,
                "tool_calls": [],
            }
        monkeypatch.setattr(
            subagent_worker, "_execute_subagent_inline", mock_execute_inline,
        )

        started = await subagent_worker.poll_subagent_tasks(hb)
        assert started == 1

        # Wait for the background asyncio.Task to complete
        import asyncio as _aio
        running = subagent_worker._running_tasks.get(task_id)
        if running:
            await running

        row = await db.fetch_one(
            "SELECT status, result_json FROM tasks WHERE id = ?", (task_id,),
        )
        assert row["status"] == "done"
        result = json.loads(row["result_json"])
        assert "summary" in result["result"].lower()

    async def test_execution_creates_notification_on_done(self, db, monkeypatch):
        from odigos.core.heartbeat import subagent_worker

        task_id = str(uuid.uuid4())
        params = {"task": "Test", "persona": "summarizer"}
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json, max_retries, retry_count) "
            "VALUES (?, 'subagent', 'pending', 'summarizer', 'default', 300, ?, 2, 0)",
            (task_id, json.dumps(params)),
        )

        hb = _make_hb(db)

        async def mock_execute_inline(hb, params, task_id, workspace_root):
            return {
                "result": "Done.",
                "artifact_path": None,
                "duration_ms": 50,
                "cost_usd": 0.0,
                "tool_calls": [],
            }
        monkeypatch.setattr(
            subagent_worker, "_execute_subagent_inline", mock_execute_inline,
        )

        await subagent_worker.poll_subagent_tasks(hb)
        running = subagent_worker._running_tasks.get(task_id)
        if running:
            await running

        # Verify notification was created
        assert hb.notifier.create.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent_worker.py::TestWorkerExecution -x -q`
Expected: FAIL — execution doesn't produce result, no notification.

- [ ] **Step 3: Flesh out `_execute_subagent_task`**

Replace the stub `_execute_subagent_task` in `odigos/core/heartbeat/subagent_worker.py` with the full version:

```python
async def _execute_subagent_task(hb, task_row: dict) -> None:
    """Execute a single sub-agent task. Called via asyncio.create_task."""
    task_id = task_row["id"]
    start_time = datetime.now(timezone.utc)

    try:
        params = json.loads(task_row["arguments_json"] or "{}")
        max_runtime = task_row.get("max_runtime_seconds") or 600
        workspace_root = params.get("workspace_root") or f"data/subagent_workspace/{task_id}"

        # Create workspace directory
        from pathlib import Path as _Path
        _Path(workspace_root).mkdir(parents=True, exist_ok=True)

        # Run the execution inline with timeout
        result = await asyncio.wait_for(
            _execute_subagent_inline(hb, params, task_id, workspace_root),
            timeout=max_runtime,
        )

        # Store result
        await hb.db.execute(
            "UPDATE tasks SET status = 'done', result_json = ?, "
            "completed_at = ?, duration_ms = ?, cost_usd = ?, "
            "artifact_path = ? WHERE id = ?",
            (
                json.dumps({"result": result.get("result", "")}),
                datetime.now(timezone.utc).isoformat(),
                result.get("duration_ms", 0),
                result.get("cost_usd", 0.0),
                result.get("artifact_path"),
                task_id,
            ),
        )

        # Publish completion event
        try:
            await hb.message_bus.publish({
                "type": "subagent_complete",
                "task_id": task_id,
                "persona": task_row.get("persona"),
                "artifact_path": result.get("artifact_path"),
            })
        except Exception:
            logger.debug("message_bus publish failed", exc_info=True)

        # Create notification
        try:
            preview = (result.get("result") or "")[:200]
            persona_name = task_row.get("persona") or "sub-agent"
            await hb.notifier.create(
                type="suggestion",
                title=f"Sub-agent task complete: {persona_name}",
                body=preview,
                metadata={
                    "task_id": task_id,
                    "artifact_path": result.get("artifact_path"),
                    "parent_task_id": task_row.get("parent_task_id"),
                },
            )
        except Exception:
            logger.debug("notifier.create failed", exc_info=True)

        # Handle on_complete chaining (added in Task 7)
        if params.get("on_complete"):
            await _dispatch_chained_subagent(hb, task_row, result, params["on_complete"])

    except asyncio.TimeoutError:
        await hb.db.execute(
            "UPDATE tasks SET status = 'failed', error = 'timeout', "
            "completed_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )
    except Exception as exc:
        logger.exception("Sub-agent task failed: %s", task_id[:8])
        await hb.db.execute(
            "UPDATE tasks SET status = 'failed', error = ?, completed_at = ? WHERE id = ?",
            (str(exc)[:500], datetime.now(timezone.utc).isoformat(), task_id),
        )
    finally:
        _running_tasks.pop(task_id, None)


async def _execute_subagent_inline(hb, params: dict, task_id: str, workspace_root: str) -> dict:
    """Execute the sub-agent LLM call with scoped tools and context.

    Returns a dict with keys: result, artifact_path, duration_ms, cost_usd, tool_calls.
    """
    from odigos.core.subagent import (
        load_persona, resolve_tools, build_scoped_system_prompt,
    )
    from odigos.skills.registry import SkillRegistry

    start = datetime.now(timezone.utc)

    persona_name = params.get("persona")
    skill_name = params.get("skill")
    explicit_tools = params.get("tools")
    explicit_system = params.get("system_prompt")
    model = params.get("model")
    context_facts = params.get("context_facts") or []
    memory_refs = params.get("memory_refs") or []
    input_artifact = params.get("input_artifact")
    task_text = params.get("task", "")

    persona = load_persona(persona_name) if persona_name else None

    # Resolve skill
    skill = None
    if skill_name and hasattr(hb, "skill_registry"):
        skill = hb.skill_registry.get(skill_name)
    elif persona and persona.skill and hasattr(hb, "skill_registry"):
        skill = hb.skill_registry.get(persona.skill)

    # Resolve tools
    persona_tools = persona.tools if persona else []
    skill_tools = (skill.tools if skill else []) or []
    tools_override = persona.tools_override if persona else False
    resolved_tools = resolve_tools(
        persona_tools=persona_tools,
        skill_tools=skill_tools,
        explicit_tools=explicit_tools,
        tools_override=tools_override,
    )

    # Resolve model
    resolved_model = model or (persona.model if persona else "default")

    # Resolve memory_refs at execution time
    resolved_facts = list(context_facts)
    if memory_refs and hasattr(hb, "memory_recall") and hb.memory_recall:
        for ref in memory_refs:
            try:
                results = await hb.memory_recall.search(ref, limit=3)
                for r in results:
                    resolved_facts.append(r.content_preview or r.content[:200])
            except Exception:
                logger.debug("memory_refs resolution failed for %r", ref)

    # Build system prompt
    system_prompt = build_scoped_system_prompt(
        persona=persona,
        skill=skill,
        explicit_system_prompt=explicit_system,
        context_facts=resolved_facts,
        input_artifact=input_artifact,
        workspace_root=workspace_root,
    )

    # Run LLM call
    response = await hb.llm_provider.complete(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_text},
        ],
        temperature=0.5,
        max_tokens=4000,
        model=resolved_model if resolved_model != "default" else hb.background_model,
    )

    result_text = response.content or ""
    duration_ms = int(
        (datetime.now(timezone.utc) - start).total_seconds() * 1000
    )
    cost = getattr(response, "cost_usd", 0.0) or 0.0

    # Optional artifact write
    artifact_path: str | None = None
    if len(result_text) > 500:
        try:
            from pathlib import Path as _Path
            artifacts_dir = _Path("data/artifacts")
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = str(artifacts_dir / f"subagent-{task_id}.md")
            _Path(artifact_path).write_text(result_text)
        except Exception:
            logger.debug("artifact write failed", exc_info=True)
            artifact_path = None

    return {
        "result": result_text,
        "artifact_path": artifact_path,
        "duration_ms": duration_ms,
        "cost_usd": cost,
        "tool_calls": [],
    }


async def _dispatch_chained_subagent(hb, parent_row: dict, result: dict, on_complete: dict) -> None:
    """Placeholder for on_complete chaining — filled in Task 7."""
    pass
```

- [ ] **Step 4: Add build_scoped_system_prompt to subagent.py**

Append to `odigos/core/subagent.py`:

```python
def build_scoped_system_prompt(
    *,
    persona: SubagentPersona | None,
    skill: Any | None,
    explicit_system_prompt: str | None,
    context_facts: list[str],
    input_artifact: str | None,
    workspace_root: str | None,
) -> str:
    """Construct the sub-agent's system prompt by combining:
    persona, skill, ad-hoc prompt, context facts, input artifact, workspace note.
    """
    parts: list[str] = []

    if skill is not None and getattr(skill, "system_prompt", None):
        parts.append(str(skill.system_prompt))

    if persona is not None and persona.system_prompt:
        parts.append(persona.system_prompt)

    if explicit_system_prompt:
        parts.append(explicit_system_prompt)

    if not parts:
        parts.append("You are a specialist sub-agent. Produce the task output directly.")

    if context_facts:
        facts_block = "\n".join(f"- {f}" for f in context_facts)
        parts.append(f"\n## User context\n{facts_block}")

    if input_artifact:
        parts.append(f"\n## Current state (input artifact)\n{input_artifact}")

    if workspace_root:
        parts.append(
            f"\n## Workspace\nYou may only read and write files under: {workspace_root}\n"
            f"Do not attempt to access any path outside this directory."
        )

    parts.append(
        "\n## Output\nProduce the direct task output. Do not add conversational "
        "framing — the orchestrator will deliver your output to the user with "
        "its own voice."
    )

    return "\n\n".join(parts)
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent_worker.py::TestWorkerExecution -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run all sub-agent tests for regressions**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent.py tests/test_subagent_worker.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add odigos/core/heartbeat/subagent_worker.py odigos/core/subagent.py tests/test_subagent_worker.py
git commit -m "feat(subagents): full execution with scoped system prompt and LLM dispatch"
```

---

### Task 7: On-Complete + On-Failure Chaining

**Files:**
- Modify: `odigos/core/heartbeat/subagent_worker.py` (fill in `_dispatch_chained_subagent`, add failure handler dispatch)
- Test: `tests/test_subagent_worker.py` (chaining tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_subagent_worker.py`:

```python
class TestChaining:
    async def test_on_complete_dispatches_follow_up(self, db, monkeypatch):
        from odigos.core.heartbeat import subagent_worker

        # Seed a pending task with on_complete
        task_id = str(uuid.uuid4())
        params = {
            "task": "Research X",
            "persona": "researcher",
            "on_complete": {
                "persona": "summarizer",
                "task": "Summarize the research",
                "input_from": "result",
            },
        }
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json, max_retries, retry_count) "
            "VALUES (?, 'subagent', 'pending', 'researcher', 'default', 600, ?, 2, 0)",
            (task_id, json.dumps(params)),
        )

        hb = _make_hb(db)

        async def mock_execute_inline(hb, params, task_id, workspace_root):
            return {
                "result": "Research complete.",
                "artifact_path": None,
                "duration_ms": 50,
                "cost_usd": 0.0,
                "tool_calls": [],
            }
        monkeypatch.setattr(
            subagent_worker, "_execute_subagent_inline", mock_execute_inline,
        )

        await subagent_worker.poll_subagent_tasks(hb)
        running = subagent_worker._running_tasks.get(task_id)
        if running:
            await running

        # Verify a chained task was created
        chained_rows = await db.fetch_all(
            "SELECT * FROM tasks WHERE parent_task_id = ?", (task_id,),
        )
        assert len(chained_rows) == 1
        chained = chained_rows[0]
        assert chained["persona"] == "summarizer"
        chained_params = json.loads(chained["arguments_json"])
        assert chained_params["input_artifact"] == "Research complete."

    async def test_on_failure_dispatches_recovery(self, db, monkeypatch):
        from odigos.core.heartbeat import subagent_worker

        task_id = str(uuid.uuid4())
        params = {
            "task": "Research X",
            "persona": "researcher",
            "on_failure": {
                "persona": "summarizer",
                "task": "Explain why the research failed",
            },
        }
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json, max_retries, retry_count) "
            "VALUES (?, 'subagent', 'pending', 'researcher', 'default', 600, ?, 0, 0)",
            (task_id, json.dumps(params)),
        )

        hb = _make_hb(db)

        async def mock_execute_inline(hb, params, task_id, workspace_root):
            raise RuntimeError("network error during research")

        monkeypatch.setattr(
            subagent_worker, "_execute_subagent_inline", mock_execute_inline,
        )

        await subagent_worker.poll_subagent_tasks(hb)
        running = subagent_worker._running_tasks.get(task_id)
        if running:
            await running

        # Verify the original task is failed
        row = await db.fetch_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
        assert row["status"] == "failed"

        # Verify on_failure task was created
        failure_rows = await db.fetch_all(
            "SELECT * FROM tasks WHERE parent_task_id = ? AND type = 'subagent'",
            (task_id,),
        )
        assert len(failure_rows) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent_worker.py::TestChaining -x -q`
Expected: FAIL — chaining not implemented.

- [ ] **Step 3: Implement chaining**

In `odigos/core/heartbeat/subagent_worker.py`, replace the placeholder `_dispatch_chained_subagent` and also add the failure handler dispatch path in `_execute_subagent_task`.

Update `_execute_subagent_task`'s `except Exception` block:

```python
    except Exception as exc:
        logger.exception("Sub-agent task failed: %s", task_id[:8])
        await hb.db.execute(
            "UPDATE tasks SET status = 'failed', error = ?, completed_at = ? WHERE id = ?",
            (str(exc)[:500], datetime.now(timezone.utc).isoformat(), task_id),
        )
        # on_failure handler
        try:
            params = json.loads(task_row["arguments_json"] or "{}")
            if params.get("on_failure"):
                await _dispatch_failure_handler(hb, task_row, str(exc), params["on_failure"])
        except Exception:
            logger.debug("on_failure dispatch failed", exc_info=True)
```

Replace `_dispatch_chained_subagent` with:

```python
async def _dispatch_chained_subagent(hb, parent_row: dict, result: dict, on_complete: dict) -> None:
    """Create a follow-up sub-agent task using the parent's result as input."""
    import uuid as _uuid

    input_from = on_complete.get("input_from", "result")
    if input_from == "result":
        input_artifact = result.get("result", "")
    elif input_from == "artifact":
        input_artifact = result.get("artifact_path", "")
    else:
        input_artifact = ""

    chained_params = {
        "task": on_complete.get("task", ""),
        "persona": on_complete.get("persona"),
        "tools": on_complete.get("tools"),
        "model": on_complete.get("model"),
        "input_artifact": input_artifact,
        "on_complete": on_complete.get("on_complete"),  # nested chain support
        "on_failure": on_complete.get("on_failure"),
    }

    chained_id = str(_uuid.uuid4())
    await hb.db.execute(
        "INSERT INTO tasks "
        "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
        "arguments_json, parent_task_id, max_retries, retry_count) "
        "VALUES (?, 'subagent', 'pending', ?, ?, ?, ?, ?, 2, 0)",
        (
            chained_id,
            on_complete.get("persona"),
            parent_row.get("concurrency_key") or "default",
            on_complete.get("max_runtime_seconds", 600),
            json.dumps(chained_params),
            parent_row["id"],
        ),
    )
    logger.info(
        "Sub-agent chain: dispatched %s (parent=%s)",
        chained_id[:8], parent_row["id"][:8],
    )


async def _dispatch_failure_handler(hb, parent_row: dict, error: str, on_failure: dict) -> None:
    """Create a recovery sub-agent task when the parent failed."""
    import uuid as _uuid

    handler_params = {
        "task": on_failure.get("task", "Explain the previous failure"),
        "persona": on_failure.get("persona"),
        "context_facts": [
            f"Original task: {json.loads(parent_row['arguments_json']).get('task', '')}",
            f"Error: {error[:300]}",
        ],
    }

    handler_id = str(_uuid.uuid4())
    await hb.db.execute(
        "INSERT INTO tasks "
        "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
        "arguments_json, parent_task_id, max_retries, retry_count) "
        "VALUES (?, 'subagent', 'pending', ?, ?, ?, ?, ?, 1, 0)",
        (
            handler_id,
            on_failure.get("persona"),
            parent_row.get("concurrency_key") or "default",
            on_failure.get("max_runtime_seconds", 300),
            json.dumps(handler_params),
            parent_row["id"],
        ),
    )
    logger.info(
        "Sub-agent on_failure: dispatched %s (parent=%s)",
        handler_id[:8], parent_row["id"][:8],
    )
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent_worker.py::TestChaining -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add odigos/core/heartbeat/subagent_worker.py tests/test_subagent_worker.py
git commit -m "feat(subagents): on_complete chaining and on_failure handlers"
```

---

### Task 8: Orchestration Tools for the Main Agent

**Files:**
- Create: `odigos/tools/subagent_tools.py`
- Create: `tests/test_subagent_tools.py`
- Modify: `odigos/bootstrap.py` (register tools)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subagent_tools.py`:

```python
"""Tests for sub-agent orchestration tools."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


class TestRunSubagentTool:
    async def test_run_subagent_tool_creates_task(self, db):
        from odigos.tools.subagent_tools import RunSubagentTool

        tool = RunSubagentTool(db=db)
        result = await tool.execute({
            "task": "Research LLM memory",
            "persona": "researcher",
        })
        assert result.success is True
        assert "task_id" in result.data.lower() or "dispatched" in result.data.lower()

        # Verify task row exists
        rows = await db.fetch_all("SELECT * FROM tasks WHERE type='subagent'")
        assert len(rows) == 1
        assert rows[0]["persona"] == "researcher"

    async def test_run_subagent_tool_validates_persona(self, db):
        from odigos.tools.subagent_tools import RunSubagentTool

        tool = RunSubagentTool(db=db)
        result = await tool.execute({
            "task": "Do something",
            "persona": "does_not_exist",
        })
        assert result.success is False
        assert "persona" in (result.error or "").lower()


class TestRunParallelSubagentsTool:
    async def test_dispatches_multiple_tasks(self, db):
        from odigos.tools.subagent_tools import RunParallelSubagentsTool

        tool = RunParallelSubagentsTool(db=db)
        result = await tool.execute({
            "tasks": [
                {"task": "Research A", "persona": "researcher"},
                {"task": "Research B", "persona": "researcher"},
                {"task": "Summarize C", "persona": "summarizer"},
            ],
        })
        assert result.success is True

        rows = await db.fetch_all("SELECT * FROM tasks WHERE type='subagent'")
        assert len(rows) == 3


class TestSubagentStatusTool:
    async def test_status_returns_task_state(self, db):
        from odigos.tools.subagent_tools import SubagentStatusTool

        task_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json) "
            "VALUES (?, 'subagent', 'done', 'researcher', 'default', 600, '{}')",
            (task_id,),
        )
        await db.execute(
            "UPDATE tasks SET result_json = ?, duration_ms = 1500, "
            "cost_usd = 0.02 WHERE id = ?",
            (json.dumps({"result": "Final research report"}), task_id),
        )

        tool = SubagentStatusTool(db=db)
        result = await tool.execute({"task_id": task_id})
        assert result.success is True
        data = json.loads(result.data) if isinstance(result.data, str) else result.data
        # data may be a formatted string containing the status
        assert "done" in str(result.data).lower()


class TestCancelSubagentTool:
    async def test_cancel_sets_flag(self, db):
        from odigos.tools.subagent_tools import CancelSubagentTool

        task_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO tasks "
            "(id, type, status, persona, concurrency_key, max_runtime_seconds, "
            "arguments_json) "
            "VALUES (?, 'subagent', 'pending', 'researcher', 'default', 600, '{}')",
            (task_id,),
        )

        tool = CancelSubagentTool(db=db)
        result = await tool.execute({"task_id": task_id})
        assert result.success is True

        row = await db.fetch_one(
            "SELECT cancel_requested FROM tasks WHERE id = ?", (task_id,),
        )
        assert row["cancel_requested"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent_tools.py -x -q`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create the tool module**

Create `odigos/tools/subagent_tools.py`:

```python
"""Orchestration tools: dispatch, query, cancel sub-agents."""
from __future__ import annotations

import json
import logging

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class RunSubagentTool(BaseTool):
    name = "run_subagent"
    category = "orchestration"
    description = (
        "Dispatch a specialized sub-agent to handle a scoped task. "
        "Use for research, heavy analysis, content generation, or any task "
        "that benefits from a fresh context and specialized tools. "
        "Runs asynchronously by default — responds immediately with a task_id "
        "and the result is delivered via notification when complete."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "What the sub-agent should do"},
            "persona": {
                "type": "string",
                "description": "Persona: researcher, coder, editor, analyst, summarizer",
            },
            "skill": {"type": "string", "description": "Optional skill name to use"},
            "context_facts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "User facts to pass to the sub-agent",
            },
            "memory_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Memory queries resolved at execution time for fresh facts",
            },
            "input_artifact": {"type": "string"},
            "on_complete": {"type": "object"},
            "on_failure": {"type": "object"},
            "concurrency_key": {"type": "string"},
        },
        "required": ["task", "persona"],
    }

    def __init__(self, db=None) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        from odigos.core.subagent import run_subagent

        try:
            dispatch = await run_subagent(
                task=params["task"],
                persona=params.get("persona"),
                skill=params.get("skill"),
                context_facts=params.get("context_facts"),
                memory_refs=params.get("memory_refs"),
                input_artifact=params.get("input_artifact"),
                on_complete=params.get("on_complete"),
                on_failure=params.get("on_failure"),
                concurrency_key=params.get("concurrency_key"),
                wait_for_result=False,
                db=self._db,
            )
            return ToolResult(
                success=True,
                data=f"Dispatched sub-agent task: task_id={dispatch.task_id} status={dispatch.status}",
            )
        except ValueError as exc:
            return ToolResult(success=False, data="", error=str(exc))
        except Exception as exc:
            logger.exception("run_subagent tool failed")
            return ToolResult(success=False, data="", error=str(exc))


class RunParallelSubagentsTool(BaseTool):
    name = "run_parallel_subagents"
    category = "orchestration"
    description = (
        "Dispatch multiple sub-agents in parallel. Each runs independently "
        "with its own fresh context. All dispatched asynchronously."
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
            },
        },
        "required": ["tasks"],
    }

    def __init__(self, db=None) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        from odigos.core.subagent import run_subagent

        task_ids: list[str] = []
        errors: list[str] = []
        for item in params.get("tasks", []):
            try:
                dispatch = await run_subagent(
                    task=item["task"],
                    persona=item.get("persona"),
                    context_facts=item.get("context_facts"),
                    wait_for_result=False,
                    db=self._db,
                )
                task_ids.append(dispatch.task_id)
            except Exception as exc:
                errors.append(f"{item.get('persona')}: {exc}")

        if not task_ids:
            return ToolResult(
                success=False, data="", error="All dispatches failed: " + "; ".join(errors),
            )
        msg = f"Dispatched {len(task_ids)} sub-agent task(s): {', '.join(t[:8] for t in task_ids)}"
        if errors:
            msg += f" ({len(errors)} failed: {'; '.join(errors)})"
        return ToolResult(success=True, data=msg)


class SubagentStatusTool(BaseTool):
    name = "subagent_status"
    category = "orchestration"
    description = (
        "Check the status of a dispatched sub-agent task by task_id. "
        "Optionally include the tool-call trace (intermediate steps)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "include_trace": {"type": "boolean", "default": False},
        },
        "required": ["task_id"],
    }

    def __init__(self, db=None) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        task_id = params.get("task_id")
        if not task_id:
            return ToolResult(success=False, data="", error="task_id is required")

        row = await self._db.fetch_one(
            "SELECT * FROM tasks WHERE id = ? AND type = 'subagent'",
            (task_id,),
        )
        if not row:
            return ToolResult(success=False, data="", error=f"Task {task_id} not found")

        result_text = ""
        if row["result_json"]:
            try:
                result_obj = json.loads(row["result_json"])
                result_text = result_obj.get("result", "")
            except Exception:
                pass

        summary = (
            f"Task: {task_id}\n"
            f"Status: {row['status']}\n"
            f"Persona: {row.get('persona')}\n"
            f"Duration: {row.get('duration_ms')}ms\n"
            f"Cost: ${row.get('cost_usd') or 0:.4f}\n"
        )
        if row.get("error"):
            summary += f"Error: {row['error']}\n"
        if row.get("artifact_path"):
            summary += f"Artifact: {row['artifact_path']}\n"
        if result_text:
            summary += f"\nResult preview: {result_text[:500]}"

        return ToolResult(success=True, data=summary)


class CancelSubagentTool(BaseTool):
    name = "cancel_subagent"
    category = "orchestration"
    description = "Cancel a pending or running sub-agent task."
    parameters_schema = {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    }

    def __init__(self, db=None) -> None:
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        task_id = params.get("task_id")
        if not task_id:
            return ToolResult(success=False, data="", error="task_id is required")

        await self._db.execute(
            "UPDATE tasks SET cancel_requested = 1 WHERE id = ? AND type = 'subagent'",
            (task_id,),
        )
        return ToolResult(
            success=True, data=f"Cancellation requested for task {task_id}",
        )
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Register tools in bootstrap**

In `odigos/bootstrap.py`, find where tools are registered to the `ToolRegistry`. Add:

```python
from odigos.tools.subagent_tools import (
    RunSubagentTool, RunParallelSubagentsTool,
    SubagentStatusTool, CancelSubagentTool,
)

# In the tool registration block:
tool_registry.register(RunSubagentTool(db=db))
tool_registry.register(RunParallelSubagentsTool(db=db))
tool_registry.register(SubagentStatusTool(db=db))
tool_registry.register(CancelSubagentTool(db=db))
```

- [ ] **Step 6: Update capabilities.md with orchestration rubric**

Edit `data/agent/capabilities.md` and add a new section (at an appropriate spot, e.g., after tool discovery instructions):

```markdown
## Orchestrating sub-agents vs activating skills

For specialized tasks, you have two paths — choose per task:

**activate_skill** — for quick specialized responses where you already have
the full user context (draft an email, summarize what we discussed, format
something). The skill's instructions layer on top of your persona for one
turn. Your voice still applies.

**run_subagent** — for heavy work (research, large content generation,
complex analysis), parallel decomposition, or anything that benefits from
a fresh context. Runs asynchronously — respond to the user immediately
with "on it, I'll ping you when ready" and the sub-agent's result arrives
via notification when complete.

When a sub-agent produces output, YOU deliver it to the user with your
voice and context. The sub-agent produces the pinnacle of the specialized
task; you provide the warmth, the framing, and the user-aware commentary.

Available personas for run_subagent:
- **researcher** — deep research with sourcing
- **coder** — code generation and review
- **editor** — text editing and refinement
- **analyst** — data analysis and synthesis
- **summarizer** — fast summarization
```

- [ ] **Step 7: Run full test suite for regressions**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent.py tests/test_subagent_worker.py tests/test_subagent_tools.py tests/test_skill_framing.py -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add odigos/tools/subagent_tools.py tests/test_subagent_tools.py \
       odigos/bootstrap.py data/agent/capabilities.md
git commit -m "feat(subagents): orchestration tools and capabilities rubric"
```

---

### Task 9: Final — Full Suite + Smoke Test

- [ ] **Step 1: Run all new sub-agent tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_skill_framing.py tests/test_subagent.py tests/test_subagent_worker.py tests/test_subagent_tools.py -v`
Expected: all pass.

- [ ] **Step 2: Run broader test suite for regressions**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_skill_maturity.py tests/test_memory_store.py tests/test_memory_recall.py tests/test_memory_evolution.py tests/test_notebooks_notes.py tests/test_notebook_review.py tests/test_api_plans.py -q`
Expected: all pass.

- [ ] **Step 3: Import sanity check**

Run:
```
cd /Users/jacob/Projects/odigos && python3 -c "
from odigos.core.subagent import run_subagent, load_persona, SubagentDispatchResult
from odigos.core.heartbeat.subagent_worker import poll_subagent_tasks, recover_orphaned_tasks
from odigos.tools.subagent_tools import RunSubagentTool, RunParallelSubagentsTool, SubagentStatusTool, CancelSubagentTool
print('all imports ok')
"
```
Expected: `all imports ok`.

- [ ] **Step 4: Docker smoke test**

Run: `cd /Users/jacob/Projects/odigos && make build && make up && sleep 5 && make logs 2>&1 | tail -30`
Expected: Container starts cleanly, no import errors, heartbeat running.

- [ ] **Step 5: Commit any final cleanup**

```bash
git add -A && git commit -m "fix: polish and cleanup for sub-agent foundation"
```
