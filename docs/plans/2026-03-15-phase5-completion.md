# Phase 5 Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Finish Phase 5 (Voice & Polish) by automating voice install and extracting all hardcoded prompts into editable files, deleting all legacy personality code.

**Architecture:** Two independent tracks — (1) a standalone `install-voice.sh` script integrated into both install scripts, and (2) a prompt reorganization that moves `data/prompt_sections/` to `data/agent/`, extracts 9 hardcoded prompts to files, deletes `personality.yaml` and all legacy code, creates a shared `prompt_loader.py`, and adds a prompts API endpoint. The prompt_builder is simplified to a pure function with no personality parameter, no constants, and no legacy fallback.

**Tech Stack:** Python 3.12+, FastAPI, bash, YAML frontmatter, pathlib

---

### Task 1: Create `install-voice.sh`

**Files:**
- Create: `install-voice.sh`

**Step 1: Write the script**

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── Helpers ──────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
bold()  { echo -e "${BOLD}$1${NC}"; }

echo ""
bold "=== Odigos Voice Setup ==="
echo ""

# ── Detect environment ───────────────────────────────────────────
if [ -d ".venv" ]; then
    PIP=".venv/bin/pip"
    PYTHON=".venv/bin/python"
    info "Bare metal install detected (.venv/)"
elif command -v uv &> /dev/null; then
    PIP="uv pip"
    PYTHON="uv run python"
    info "uv environment detected"
else
    PIP="pip"
    PYTHON="python3"
    info "Docker/system install detected"
fi

# ── Install packages ─────────────────────────────────────────────
info "Installing voice dependencies..."
$PIP install moonshine-voice pocket-tts scipy
info "Voice packages installed"

# ── Download STT model ───────────────────────────────────────────
info "Downloading Moonshine English model (one-time)..."
$PYTHON -m moonshine_voice.download --language en
info "STT model downloaded"

# ── Update config.yaml ───────────────────────────────────────────
if [ -f "config.yaml" ]; then
    # Use python to safely update YAML
    $PYTHON -c "
import yaml
from pathlib import Path

config_path = Path('config.yaml')
data = yaml.safe_load(config_path.read_text()) or {}
data.setdefault('stt', {})['enabled'] = True
data.setdefault('tts', {})['enabled'] = True
config_path.write_text(yaml.dump(data, default_flow_style=False))
print('  Updated config.yaml: stt.enabled=true, tts.enabled=true')
"
    info "Config updated"
else
    warn "No config.yaml found — voice plugins will be enabled once you create one with stt.enabled: true and tts.enabled: true"
fi

echo ""
info "Voice setup complete!"
echo ""
echo "  TTS voices available: alba, marius, javert, jean, fantine, cosette, eponine, azelma"
echo "  STT model: small-en (streaming-capable)"
echo ""
echo "  Restart Odigos to activate voice plugins."
echo ""
```

**Step 2: Make it executable**

Run: `chmod +x install-voice.sh`

**Step 3: Commit**

```bash
git add install-voice.sh
git commit -m "feat: add install-voice.sh for one-click voice setup"
```

---

### Task 2: Integrate voice install into `install.sh` and `install-bare.sh`

**Files:**
- Modify: `install.sh:156-157` (after config.yaml write, before Build and Start)
- Modify: `install-bare.sh:183-184` (after config.yaml write, before systemd/start)

**Step 1: Add voice prompt to `install.sh`**

After the `info "Wrote config.yaml"` / `fi` block (line 156), before the `# ── Build and Start` comment (line 158), add:

```bash
# ── Voice Setup (optional) ────────────────────────────────────────
echo ""
read -rp "$(echo -e "${BOLD}Enable voice (text-to-speech and speech-to-text)? [y/N]:${NC} ")" enable_voice
enable_voice=${enable_voice:-N}

if [[ "$enable_voice" =~ ^[Yy]$ ]]; then
    if [ -f "./install-voice.sh" ]; then
        bash ./install-voice.sh
    else
        warn "install-voice.sh not found. Run it separately after install."
    fi
fi
```

**Step 2: Add same voice prompt to `install-bare.sh`**

After the `info "Wrote config.yaml"` / `fi` block (line 183), before the `# ── Systemd service` comment (line 186), add the same block as Step 1.

**Step 3: Commit**

```bash
git add install.sh install-bare.sh
git commit -m "feat: add optional voice install prompt to install scripts"
```

---

### Task 3: Create shared prompt loader

**Files:**
- Create: `odigos/core/prompt_loader.py`
- Create: `tests/test_prompt_loader.py`

**Step 1: Write the test**

```python
"""Tests for the shared prompt loader."""
import os
import tempfile
import time

from odigos.core.prompt_loader import load_prompt, _cache


def test_returns_fallback_when_file_missing():
    _cache.clear()
    result = load_prompt("nonexistent.md", "default content")
    assert result == "default content"


def test_reads_file_when_exists():
    _cache.clear()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "test.md")
        with open(path, "w") as f:
            f.write("  custom content  ")
        # Patch the base dir
        result = load_prompt("test.md", "fallback", base_dir=d)
        assert result == "custom content"


def test_caches_by_mtime():
    _cache.clear()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "cached.md")
        with open(path, "w") as f:
            f.write("version 1")
        result1 = load_prompt("cached.md", "fallback", base_dir=d)
        assert result1 == "version 1"

        # Write new content without changing mtime
        # (same mtime -> cache hit)
        result2 = load_prompt("cached.md", "fallback", base_dir=d)
        assert result2 == "version 1"


def test_reloads_on_mtime_change():
    _cache.clear()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "reload.md")
        with open(path, "w") as f:
            f.write("version 1")
        load_prompt("reload.md", "fallback", base_dir=d)

        # Force mtime change
        time.sleep(0.05)
        with open(path, "w") as f:
            f.write("version 2")

        result = load_prompt("reload.md", "fallback", base_dir=d)
        assert result == "version 2"
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_prompt_loader.py -v`
Expected: FAIL (module not found)

**Step 3: Write the implementation**

```python
"""Load editable prompt files from data/prompts/ with hardcoded fallbacks."""
from pathlib import Path

_cache: dict[str, tuple[float, str]] = {}

_DEFAULT_BASE_DIR = "data/prompts"


def load_prompt(name: str, fallback: str, base_dir: str | None = None) -> str:
    """Load prompt from {base_dir}/{name}. Cached by mtime. Falls back if missing."""
    base = base_dir or _DEFAULT_BASE_DIR
    path = Path(base) / name
    if not path.exists():
        return fallback
    mtime = path.stat().st_mtime
    cache_key = str(path)
    cached = _cache.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]
    content = path.read_text().strip()
    _cache[cache_key] = (mtime, content)
    return content
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_prompt_loader.py -v`
Expected: PASS (4/4)

**Step 5: Commit**

```bash
git add odigos/core/prompt_loader.py tests/test_prompt_loader.py
git commit -m "feat: add shared prompt loader with mtime caching"
```

---

### Task 4: Move prompt sections to `data/agent/` and create new prompt files

**Files:**
- Create: `data/agent/identity.md` (copy from `data/prompt_sections/identity.md`)
- Create: `data/agent/voice.md` (copy from `data/prompt_sections/voice.md`)
- Create: `data/agent/meta.md` (copy from `data/prompt_sections/meta.md`)
- Create: `data/agent/entity_extraction.md` (from `ENTITY_EXTRACTION_INSTRUCTION` constant in `odigos/personality/prompt_builder.py:5-10`)
- Create: `data/agent/correction_detection.md` (from `CORRECTION_DETECTION_INSTRUCTION` constant in `odigos/personality/prompt_builder.py:12-22`)
- Create: `data/agent/skill_creation.md` (from `SKILL_CREATION_INSTRUCTION` constant in `odigos/personality/prompt_builder.py:24`)
- Create: `data/prompts/summarizer.md` (from `STRUCTURED_COMPACTION_PROMPT` in `odigos/memory/summarizer.py:10-30`)
- Create: `data/prompts/evaluator_rubric.md` (from `evaluator.py:159-168`)
- Create: `data/prompts/evaluator_scoring.md` (from `evaluator.py:184-193`)
- Create: `data/prompts/strategist.md` (from `strategist.py:180-214`)
- Create: `data/prompts/heartbeat_idle.md` (from `heartbeat.py:287-295`)
- Create: `data/prompts/subagent.md` (from `subagent.py:107-109`)
- Create: `data/prompts/spawner_adapt.md` (from `spawner.py:149-159`)

**Step 1: Create `data/agent/` directory and copy existing sections**

```bash
mkdir -p data/agent data/prompts
cp data/prompt_sections/identity.md data/agent/identity.md
cp data/prompt_sections/voice.md data/agent/voice.md
cp data/prompt_sections/meta.md data/agent/meta.md
```

**Step 2: Create `data/agent/entity_extraction.md`**

```markdown
---
priority: 100
always_include: true
---
After your response, on a new line, include extracted entities in this exact format:
<!--entities
[{{"name": "...", "type": "person|project|preference|concept", "relationship": "...", "detail": "..."}}]
-->
Only include entities if the conversation mentions specific people, projects, preferences, or important concepts.
If none are relevant, omit the block entirely.
```

**Step 3: Create `data/agent/correction_detection.md`**

```markdown
---
priority: 95
always_include: true
---
If the user's message is correcting or disagreeing with your previous response, include a correction block after your response in this exact format:
<!--correction
{"original": "brief summary of what you said wrong", "correction": "what the user wants instead", "category": "tone|accuracy|preference|behavior|tool_choice", "context": "brief description of the situation"}
-->
Only include this block when the user is explicitly correcting you. Categories:
- tone: communication style (too formal, too casual, etc.)
- accuracy: factual errors
- preference: user preferences (scheduling, formatting, etc.)
- behavior: action/decision patterns
- tool_choice: wrong tool or approach used
If the user is not correcting you, omit the block entirely.
```

**Step 4: Create `data/agent/skill_creation.md`**

```markdown
---
priority: 80
always_include: true
---
You can create reusable skills for task types you encounter repeatedly using the create_skill tool. A skill is a set of instructions that guide your behavior for a specific kind of task. Create a skill when you notice you've handled the same type of request multiple times with similar steps. Use update_skill to refine a skill you created when you receive corrections or learn better approaches. When you create or update a skill, mention it briefly in your response so the user is aware.
```

**Step 5: Create `data/prompts/summarizer.md`**

```markdown
Summarize this conversation segment using the following structured format.
Include ONLY sections that have relevant content. Be concise.

## Goal
What is the user trying to accomplish? (1 sentence)

## Progress
- Done: What has been completed
- In Progress: What is currently being worked on
- Blocked: Any blockers or issues

## Decisions
Key decisions made during this conversation (bulleted list)

## Next Steps
What should happen next (bulleted list)

## Key Facts
Important facts, preferences, or context worth remembering (bulleted list)
```

**Step 6: Create `data/prompts/evaluator_rubric.md`**

```markdown
You are evaluating an AI assistant's response. Generate a scoring rubric for this type of interaction.

User message: {user_content}
Assistant response: {assistant_content}
User reaction signal: {feedback} (-1=negative, +1=positive)

Return ONLY a JSON object:
{"task_type": "category", "criteria": [{"name": "...", "weight": 0.0-1.0, "description": "what good looks like"}], "notes": "..."}
```

**Step 7: Create `data/prompts/evaluator_scoring.md`**

```markdown
Score this AI assistant interaction against the rubric.

Rubric: {rubric}

User message: {user_content}
Assistant response: {assistant_content}
User reaction signal: {feedback}

Return ONLY a JSON object:
{"scores": [{"criterion": "name", "score": 0-10, "observation": "..."}], "overall": 0-10, "improvement_signal": "what would have been better" or null}
```

**Step 8: Create `data/prompts/strategist.md`**

```markdown
You are the strategist for an AI agent's self-improvement system.
Analyze this agent's recent performance and propose improvements.

## Agent Context
Description: {agent_description}
Available tools: {agent_tools}

## Recent Evaluation Summary (last 7 days)
{task_summary}

## Failed Trials (avoid repeating these)
{failed_summary}

## Recent Direction Log
{direction_summary}

## Instructions
Based on the above, produce a JSON object with:
1. "analysis" -- 1-2 sentence summary of current performance
2. "direction" -- 1 sentence on what to focus on improving
3. "hypotheses" -- Array of 0-3 improvement proposals. Each has:
   - "type": "trial_hypothesis"
   - "hypothesis": what to try
   - "target": "prompt_section"
   - "target_name": which section to modify (e.g. "voice", "identity", "meta")
   - "change": the new content for that section
   - "confidence": 0.0-1.0
4. "specialization_proposals" -- Array of 0-1 proposals if a domain is consistently weak and would benefit from a dedicated specialist agent. Each has:
   - "role": short role name
   - "specialty": routing tag
   - "description": 1-2 sentences
   - "rationale": why this specialist is needed

Do NOT propose changes that have already failed (see failed trials above).
Return ONLY the JSON object, no markdown.
```

**Step 9: Create `data/prompts/heartbeat_idle.md`**

```markdown
You are reviewing your active goals during idle time. If there's something useful you could do right now, respond with a JSON object: {"todo": "description of work item"}. If you have a progress observation, respond with: {"note": "goal_id", "progress": "observation"}. If nothing to do, respond with: {"idle": true}
```

**Step 10: Create `data/prompts/subagent.md`**

```markdown
You are a focused subagent. Complete the given task concisely. Do not ask follow-up questions.
```

**Step 11: Create `data/prompts/spawner_adapt.md`**

```markdown
Below is a specialist agent template. Adapt it into a focused identity and instruction set for an AI agent with:
- Role: {role}
- Description: {description}
- Specialty: {specialty}

Keep the template's personality, workflows, deliverables, and success metrics where relevant. Remove anything that doesn't apply. Write in second person ('You are...'). Output only the adapted identity -- no commentary.

--- TEMPLATE ---
{template_content}
```

**Step 12: Commit**

```bash
git add data/agent/ data/prompts/
git commit -m "feat: extract all prompts to editable files in data/agent/ and data/prompts/"
```

---

### Task 5: Simplify `prompt_builder.py` — remove constants, legacy code, personality parameter

**Files:**
- Modify: `odigos/personality/prompt_builder.py`
- Modify: `tests/test_prompt_builder.py`
- Modify: `tests/test_prompt_builder_dynamic.py`

**Step 1: Rewrite the test files**

Replace `tests/test_prompt_builder.py` with:

```python
"""Tests for the simplified prompt builder."""
from odigos.personality.prompt_builder import build_system_prompt
from odigos.personality.section_registry import PromptSection


class TestBuildSystemPrompt:
    def test_builds_from_sections(self):
        sections = [
            PromptSection(name="identity", content="You are {name}.", priority=10),
            PromptSection(name="voice", content="Be concise.", priority=20),
        ]
        result = build_system_prompt(sections=sections, agent_name="TestBot")
        assert "You are TestBot." in result
        assert "Be concise." in result

    def test_sections_sorted_by_priority(self):
        sections = [
            PromptSection(name="voice", content="VOICE", priority=20),
            PromptSection(name="identity", content="IDENTITY", priority=10),
        ]
        result = build_system_prompt(sections=sections)
        assert result.index("IDENTITY") < result.index("VOICE")

    def test_memory_context_included(self):
        sections = [PromptSection(name="id", content="You are Odigos.", priority=10)]
        result = build_system_prompt(
            sections=sections,
            memory_context="## Relevant memories\n- Alice prefers mornings.",
        )
        assert "Alice prefers mornings" in result

    def test_memory_context_omitted_when_empty(self):
        sections = [PromptSection(name="id", content="Agent.", priority=10)]
        result = build_system_prompt(sections=sections, memory_context="")
        assert "Relevant memories" not in result

    def test_corrections_context_included(self):
        sections = [PromptSection(name="id", content="Agent.", priority=10)]
        corrections = "## Learned corrections\n- Be more casual"
        result = build_system_prompt(sections=sections, corrections_context=corrections)
        assert "Be more casual" in result

    def test_corrections_context_omitted_when_empty(self):
        sections = [PromptSection(name="id", content="Agent.", priority=10)]
        result = build_system_prompt(sections=sections, corrections_context="")
        assert "Learned corrections" not in result

    def test_skill_catalog_included(self):
        sections = [PromptSection(name="id", content="Agent.", priority=10)]
        result = build_system_prompt(
            sections=sections,
            skill_catalog="## Skills\n- research",
        )
        assert "research" in result

    def test_empty_sections_still_works(self):
        result = build_system_prompt(sections=[])
        assert isinstance(result, str)

    def test_name_replacement_in_content(self):
        sections = [PromptSection(name="id", content="I am {name}.", priority=10)]
        result = build_system_prompt(sections=sections, agent_name="Athena")
        assert "I am Athena." in result
        assert "{name}" not in result
```

Replace `tests/test_prompt_builder_dynamic.py` with:

```python
"""Test that prompt builder uses dynamic sections."""
from odigos.personality.prompt_builder import build_system_prompt
from odigos.personality.section_registry import PromptSection


def test_build_with_dynamic_sections():
    sections = [
        PromptSection(name="identity", content="You are Odigos.", priority=10),
        PromptSection(name="voice", content="Be concise.", priority=20),
    ]
    result = build_system_prompt(
        sections=sections,
        memory_context="User likes Python.",
        corrections_context="",
    )
    assert "You are Odigos." in result
    assert "Be concise." in result
    assert "User likes Python." in result
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_prompt_builder.py tests/test_prompt_builder_dynamic.py -v`
Expected: FAIL (signature mismatch — `personality` param still exists)

**Step 3: Rewrite `odigos/personality/prompt_builder.py`**

```python
from __future__ import annotations

from odigos.personality.section_registry import PromptSection


def build_system_prompt(
    sections: list[PromptSection],
    memory_context: str = "",
    skill_catalog: str = "",
    corrections_context: str = "",
    agent_name: str = "",
) -> str:
    """Compose the system prompt from file-based sections.

    Sections are loaded from data/agent/ by the SectionRegistry
    (via CheckpointManager). Each section has a priority for ordering.
    """
    parts = []
    for section in sorted(sections, key=lambda s: s.priority):
        content = section.content.replace("{name}", agent_name)
        parts.append(content)

    if memory_context:
        parts.append(memory_context)
    if skill_catalog:
        parts.append(skill_catalog)
    if corrections_context:
        parts.append(corrections_context)

    return "\n\n".join(parts)
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_prompt_builder.py tests/test_prompt_builder_dynamic.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add odigos/personality/prompt_builder.py tests/test_prompt_builder.py tests/test_prompt_builder_dynamic.py
git commit -m "refactor: simplify prompt_builder — remove personality param, constants, legacy code"
```

---

### Task 6: Delete `personality.yaml`, `loader.py`, `PersonalityConfig`, and update `section_registry.py`

**Files:**
- Delete: `odigos/personality/loader.py`
- Delete: `data/personality.yaml` (if exists)
- Delete: `tests/test_personality.py`
- Modify: `odigos/config.py:34-35` (remove `PersonalityConfig`)
- Modify: `odigos/config.py:166` (remove `personality` field from `Settings`)
- Modify: `odigos/personality/section_registry.py` (no code change needed — default path is passed by caller)

**Step 1: Delete the files**

```bash
rm -f odigos/personality/loader.py
rm -f data/personality.yaml
rm -f tests/test_personality.py
```

**Step 2: Remove `PersonalityConfig` from `odigos/config.py`**

Delete the `PersonalityConfig` class (lines 34-35):
```python
class PersonalityConfig(BaseModel):
    path: str = "data/personality.yaml"
```

Delete the `personality` field from `Settings` (line 166):
```python
    personality: PersonalityConfig = PersonalityConfig()
```

**Step 3: Run tests to see what breaks**

Run: `python3 -m pytest tests/ -v --tb=short 2>&1 | head -80`
Expected: Imports of `Personality`, `load_personality`, and `PersonalityConfig` will fail in several places. This is expected — we fix those in subsequent tasks.

**Step 4: Commit**

```bash
git add -u  # stages deletions and modifications
git commit -m "refactor: delete personality.yaml, loader.py, PersonalityConfig"
```

---

### Task 7: Update `context.py` — remove personality, always use sections

**Files:**
- Modify: `odigos/core/context.py`

**Step 1: Rewrite `context.py`**

Remove:
- `from odigos.personality.loader import load_personality` (line 9)
- `personality_path` parameter from `__init__` (line 38)
- `self.personality_path` assignment (line 48)
- The personality loading block in `build()` (lines 63-67)
- The `personality=personality` kwarg in `build_system_prompt()` call (line 99)

Add:
- `from odigos.personality.section_registry import SectionRegistry` import
- `agent_name` parameter stored on self
- Standalone `SectionRegistry` fallback when no checkpoint_manager
- Pass `agent_name` to `build_system_prompt()`

The updated `__init__` signature:

```python
def __init__(
    self,
    db: Database,
    agent_name: str,
    history_limit: int = 20,
    memory_manager: MemoryManager | None = None,
    summarizer: ConversationSummarizer | None = None,
    skill_registry: SkillRegistry | None = None,
    corrections_manager: CorrectionsManager | None = None,
    checkpoint_manager: CheckpointManager | None = None,
    sections_dir: str = "data/agent",
) -> None:
    self.db = db
    self.agent_name = agent_name
    self.history_limit = history_limit
    self.memory_manager = memory_manager
    self.summarizer = summarizer
    self.skill_registry = skill_registry
    self.corrections_manager = corrections_manager
    self.checkpoint_manager = checkpoint_manager
    self._fallback_registry = SectionRegistry(sections_dir)
```

The updated `build()` method section for system prompt:

```python
    # Load dynamic prompt sections
    if self.checkpoint_manager:
        sections = await self.checkpoint_manager.get_working_sections()
    else:
        sections = self._fallback_registry.load_all()

    # Build system prompt
    system_prompt = build_system_prompt(
        sections=sections,
        memory_context=memory_context,
        skill_catalog=skill_catalog,
        corrections_context=corrections_context,
        agent_name=self.agent_name,
    )
```

Full import block:

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import tiktoken

from odigos.db import Database
from odigos.personality.prompt_builder import build_system_prompt
from odigos.personality.section_registry import SectionRegistry

if TYPE_CHECKING:
    from odigos.core.checkpoint import CheckpointManager
    from odigos.memory.corrections import CorrectionsManager
    from odigos.memory.manager import MemoryManager
    from odigos.memory.summarizer import ConversationSummarizer
    from odigos.skills.registry import SkillRegistry
```

**Step 2: Run prompt builder tests**

Run: `python3 -m pytest tests/test_prompt_builder.py tests/test_prompt_builder_dynamic.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add odigos/core/context.py
git commit -m "refactor: remove personality_path from ContextAssembler, use sections always"
```

---

### Task 8: Update `agent.py` — remove `personality_path`

**Files:**
- Modify: `odigos/core/agent.py`

**Step 1: Update `Agent.__init__`**

Remove the `personality_path` parameter (line 39) and the `personality_path=personality_path` kwarg passed to `ContextAssembler` (line 65).

Updated constructor (relevant diff):

```python
def __init__(
    self,
    db: Database,
    provider: LLMProvider,
    agent_name: str,
    history_limit: int = 20,
    memory_manager: MemoryManager | None = None,
    tool_registry: ToolRegistry | None = None,
    skill_registry: SkillRegistry | None = None,
    cost_fetcher: Callable | None = None,
    budget_tracker: BudgetTracker | None = None,
    max_tool_turns: int = 25,
    run_timeout: int = 300,
    summarizer: ConversationSummarizer | None = None,
    corrections_manager: CorrectionsManager | None = None,
    tracer: Tracer | None = None,
    approval_gate: ApprovalGate | None = None,
) -> None:
```

Updated ContextAssembler construction:

```python
    self.context_assembler = ContextAssembler(
        db,
        agent_name,
        history_limit,
        memory_manager=memory_manager,
        summarizer=summarizer,
        skill_registry=skill_registry,
        corrections_manager=corrections_manager,
    )
```

**Step 2: Commit**

```bash
git add odigos/core/agent.py
git commit -m "refactor: remove personality_path from Agent constructor"
```

---

### Task 9: Update `checkpoint.py` — remove personality, update sections_dir default

**Files:**
- Modify: `odigos/core/checkpoint.py`
- Modify: `tests/test_checkpoint.py`

**Step 1: Update `CheckpointManager.__init__`**

Remove `personality_path` parameter and `self._personality_path` assignment. Remove personality snapshot logic from `create_checkpoint()`.

Updated constructor:

```python
def __init__(
    self,
    db: Database,
    sections_dir: str,
    skills_dir: str = "skills",
) -> None:
    self.db = db
    self._sections_dir = sections_dir
    self._skills_dir = skills_dir
    self._section_registry = SectionRegistry(sections_dir)
```

Updated `create_checkpoint()` — remove `personality_snapshot` variable and `self._personality_path` block. The INSERT still has the `personality_snapshot` column (schema unchanged), just pass empty string:

```python
async def create_checkpoint(self, label: str = "", parent_id: str | None = None) -> str:
    cp_id = str(uuid.uuid4())

    sections_snapshot = {}
    s_dir = Path(self._sections_dir)
    if s_dir.exists():
        for f in s_dir.glob("*.md"):
            sections_snapshot[f.stem] = f.read_text()

    skills_snapshot = {}
    sk_dir = Path(self._skills_dir)
    if sk_dir.exists():
        for f in sk_dir.glob("*.md"):
            skills_snapshot[f.stem] = f.read_text()

    await self.db.execute(
        "INSERT INTO checkpoints (id, parent_id, label, personality_snapshot, "
        "prompt_sections_snapshot, skills_snapshot) VALUES (?, ?, ?, ?, ?, ?)",
        (
            cp_id,
            parent_id,
            label,
            "",  # personality_snapshot deprecated
            json.dumps(sections_snapshot),
            json.dumps(skills_snapshot),
        ),
    )
    return cp_id
```

**Step 2: Update `tests/test_checkpoint.py`**

Remove all `personality_path=""` kwargs from `CheckpointManager()` constructors — the parameter no longer exists. Replace:

```python
mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
```

with:

```python
mgr = CheckpointManager(db=db, sections_dir=sections_dir)
```

This applies to all 6 test functions.

**Step 3: Run checkpoint tests**

Run: `python3 -m pytest tests/test_checkpoint.py -v`
Expected: PASS (6/6)

**Step 4: Commit**

```bash
git add odigos/core/checkpoint.py tests/test_checkpoint.py
git commit -m "refactor: remove personality_path from CheckpointManager"
```

---

### Task 10: Update `main.py` — wire new paths, remove personality refs

**Files:**
- Modify: `odigos/main.py`

**Step 1: Update the Agent constructor call**

Remove `personality_path=settings.personality.path` (line 422). The `Agent` no longer accepts this parameter.

Before:
```python
agent = Agent(
    ...
    personality_path=settings.personality.path,
    ...
)
```

After:
```python
agent = Agent(
    db=_db,
    provider=_provider,
    agent_name=settings.agent.name,
    memory_manager=memory_manager,
    tool_registry=tool_registry,
    skill_registry=skill_registry,
    cost_fetcher=None,
    budget_tracker=budget_tracker,
    max_tool_turns=settings.agent.max_tool_turns,
    run_timeout=settings.agent.run_timeout_seconds,
    summarizer=summarizer,
    corrections_manager=corrections_manager,
    tracer=tracer,
    approval_gate=approval_gate,
)
```

**Step 2: Update the CheckpointManager constructor call**

Change `sections_dir="data/prompt_sections"` to `sections_dir="data/agent"` and remove `personality_path=settings.personality.path`.

Before:
```python
checkpoint_manager = CheckpointManager(
    db=_db,
    sections_dir="data/prompt_sections",
    personality_path=settings.personality.path,
    skills_dir=settings.skills.path,
)
```

After:
```python
checkpoint_manager = CheckpointManager(
    db=_db,
    sections_dir="data/agent",
    skills_dir=settings.skills.path,
)
```

**Step 3: Add migration logic**

After `mkdir -p data data/plugins data/files skills plugins` equivalent (the directories are created elsewhere, but add migration at the start of lifespan, right after `settings = load_settings(config_path)`):

```python
# Migrate prompt_sections -> agent (one-time)
from pathlib import Path as _Path
_agent_dir = _Path("data/agent")
_old_sections = _Path("data/prompt_sections")
if _old_sections.exists() and not _agent_dir.exists():
    import shutil
    shutil.copytree(str(_old_sections), str(_agent_dir))
    logger.info("Migrated data/prompt_sections/ to data/agent/")
if _Path("data/personality.yaml").exists():
    logger.warning("data/personality.yaml is deprecated and ignored — identity is now in data/agent/identity.md")
```

**Step 4: Add prompts router import and include**

Add import:
```python
from odigos.api.prompts import router as prompts_router
```

Add include (alongside other routers):
```python
app.include_router(prompts_router)
```

**Step 5: Commit**

```bash
git add odigos/main.py
git commit -m "refactor: update main.py — use data/agent/, remove personality refs, add migration"
```

---

### Task 11: Wire `load_prompt` into 6 subsystems

**Files:**
- Modify: `odigos/memory/summarizer.py`
- Modify: `odigos/core/evaluator.py`
- Modify: `odigos/core/strategist.py`
- Modify: `odigos/core/heartbeat.py`
- Modify: `odigos/core/subagent.py`
- Modify: `odigos/core/spawner.py`

**Step 1: Update `odigos/memory/summarizer.py`**

Add import at top:
```python
from odigos.core.prompt_loader import load_prompt
```

Change line 98 from:
```python
{"role": "system", "content": STRUCTURED_COMPACTION_PROMPT},
```
to:
```python
{"role": "system", "content": load_prompt("summarizer.md", STRUCTURED_COMPACTION_PROMPT)},
```

Keep `STRUCTURED_COMPACTION_PROMPT` and `SUMMARIZE_PROMPT` constants as fallbacks.

**Step 2: Update `odigos/core/evaluator.py`**

Add import:
```python
from odigos.core.prompt_loader import load_prompt
```

In `_get_or_generate_rubric` (line 159), replace the hardcoded prompt string with:
```python
_RUBRIC_FALLBACK = (
    "You are evaluating an AI assistant's response. "
    "Generate a scoring rubric for this type of interaction.\n\n"
    "User message: {user_content}\n"
    "Assistant response: {assistant_content}\n"
    "User reaction signal: {feedback} (-1=negative, +1=positive)\n\n"
    "Return ONLY a JSON object:\n"
    '{"task_type": "category", "criteria": [{"name": "...", "weight": 0.0-1.0, '
    '"description": "what good looks like"}], "notes": "..."}'
)
```

Then in the method:
```python
prompt_template = load_prompt("evaluator_rubric.md", _RUBRIC_FALLBACK)
prompt = prompt_template.format(
    user_content=user_content[:500],
    assistant_content=assistant_content[:500],
    feedback=f"{feedback:.1f}",
)
```

Similarly for `_score_against_rubric`:
```python
_SCORING_FALLBACK = (
    "Score this AI assistant interaction against the rubric.\n\n"
    "Rubric: {rubric}\n\n"
    "User message: {user_content}\n"
    "Assistant response: {assistant_content}\n"
    "User reaction signal: {feedback}\n\n"
    "Return ONLY a JSON object:\n"
    '{"scores": [{"criterion": "name", "score": 0-10, "observation": "..."}], '
    '"overall": 0-10, "improvement_signal": "what would have been better" or null}'
)
```

Then:
```python
prompt_template = load_prompt("evaluator_scoring.md", _SCORING_FALLBACK)
prompt = prompt_template.format(
    rubric=json.dumps(rubric),
    user_content=user_content[:500],
    assistant_content=assistant_content[:500],
    feedback=f"{feedback:.1f}",
)
```

**Step 3: Update `odigos/core/strategist.py`**

Add import:
```python
from odigos.core.prompt_loader import load_prompt
```

Extract the `_build_prompt` return string as a module-level fallback constant `_STRATEGIST_FALLBACK`. Then in `_build_prompt`, use:

```python
def _build_prompt(self, eval_summary: dict, failed_trials: list, directions: list) -> str:
    # ... build failed_summary, direction_summary, task_summary as before ...

    template = load_prompt("strategist.md", _STRATEGIST_FALLBACK)
    return template.format(
        agent_description=self._agent_description or 'No description set',
        agent_tools=', '.join(self._agent_tools) if self._agent_tools else 'None listed',
        task_summary=task_summary or 'No evaluations yet.',
        failed_summary=failed_summary or 'None.',
        direction_summary=direction_summary or 'No prior direction set.',
    )
```

**Step 4: Update `odigos/core/heartbeat.py`**

Add import:
```python
from odigos.core.prompt_loader import load_prompt
```

Extract the idle think system prompt (lines 287-295) as `_IDLE_THINK_FALLBACK`:
```python
_IDLE_THINK_FALLBACK = (
    "You are reviewing your active goals during idle time. "
    "If there's something useful you could do right now, respond with a JSON object: "
    '{"todo": "description of work item"}. '
    "If you have a progress observation, respond with: "
    '{"note": "goal_id", "progress": "observation"}. '
    'If nothing to do, respond with: {"idle": true}'
)
```

Then in `_idle_think`:
```python
{
    "role": "system",
    "content": load_prompt("heartbeat_idle.md", _IDLE_THINK_FALLBACK),
},
```

**Step 5: Update `odigos/core/subagent.py`**

Add import:
```python
from odigos.core.prompt_loader import load_prompt
```

Add fallback constant:
```python
_SUBAGENT_SYSTEM_FALLBACK = (
    "You are a focused subagent. Complete the given task concisely. "
    "Do not ask follow-up questions."
)
```

In `_run_subagent`, replace the hardcoded system content (line 107-109):
```python
messages: list[dict] = [
    {
        "role": "system",
        "content": load_prompt("subagent.md", _SUBAGENT_SYSTEM_FALLBACK),
    },
]
```

**Step 6: Update `odigos/core/spawner.py`**

Add import:
```python
from odigos.core.prompt_loader import load_prompt
```

Add fallback constant:
```python
_ADAPT_TEMPLATE_FALLBACK = (
    "Below is a specialist agent template. Adapt it into a focused identity "
    "and instruction set for an AI agent with:\n"
    "- Role: {role}\n"
    "- Description: {description}\n"
    "- Specialty: {specialty}\n\n"
    "Keep the template's personality, workflows, deliverables, and success metrics "
    "where relevant. Remove anything that doesn't apply. Write in second person "
    "('You are...'). Output only the adapted identity -- no commentary.\n\n"
    "--- TEMPLATE ---\n{template_content}"
)
```

In `_identity_from_template`, replace the hardcoded prompt:
```python
async def _identity_from_template(
    self,
    template_content: str,
    role: str,
    description: str,
    specialty: str | None,
) -> str:
    template = load_prompt("spawner_adapt.md", _ADAPT_TEMPLATE_FALLBACK)
    prompt = template.format(
        role=role,
        description=description,
        specialty=specialty or 'general',
        template_content=template_content,
    )
    response = await self.provider.complete(
        [{"role": "user", "content": prompt}],
        model=getattr(self.provider, "fallback_model", None),
        max_tokens=1500,
        temperature=0.4,
    )
    return response.content.strip()
```

**Step 7: Run all tests**

Run: `python3 -m pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All existing tests pass. The `load_prompt` calls fall back to constants when files are missing (which they are in test environments).

**Step 8: Commit**

```bash
git add odigos/memory/summarizer.py odigos/core/evaluator.py odigos/core/strategist.py odigos/core/heartbeat.py odigos/core/subagent.py odigos/core/spawner.py
git commit -m "feat: wire load_prompt into 6 subsystems for editable prompts"
```

---

### Task 12: Create prompts API endpoint

**Files:**
- Create: `odigos/api/prompts.py`
- Create: `tests/test_prompts_api.py`

**Step 1: Write the test**

```python
"""Tests for the prompts API endpoint."""
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from odigos.api.prompts import router, _PROMPT_DIRS


@pytest.fixture
def app_with_prompts(tmp_path):
    """Create a test app with temporary prompt directories."""
    agent_dir = tmp_path / "agent"
    prompts_dir = tmp_path / "prompts"
    agent_dir.mkdir()
    prompts_dir.mkdir()

    # Create test files
    (agent_dir / "identity.md").write_text(
        "---\npriority: 10\nalways_include: true\n---\nYou are Odigos."
    )
    (prompts_dir / "summarizer.md").write_text("Summarize this conversation.")

    app = FastAPI()
    app.include_router(router)

    # Mock settings for auth
    settings = MagicMock()
    settings.api_key = "test-key"
    app.state.settings = settings

    # Patch prompt dirs for tests
    original_dirs = dict(_PROMPT_DIRS)
    _PROMPT_DIRS["agent"] = str(agent_dir)
    _PROMPT_DIRS["prompts"] = str(prompts_dir)

    yield TestClient(app)

    _PROMPT_DIRS.update(original_dirs)


def test_list_prompts(app_with_prompts):
    client = app_with_prompts
    resp = client.get("/api/prompts", headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 200
    data = resp.json()
    names = [p["name"] for p in data]
    assert "identity" in names
    assert "summarizer" in names


def test_read_prompt(app_with_prompts):
    client = app_with_prompts
    resp = client.get(
        "/api/prompts/agent/identity",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200
    assert "You are Odigos." in resp.json()["content"]


def test_update_prompt(app_with_prompts):
    client = app_with_prompts
    resp = client.put(
        "/api/prompts/prompts/summarizer",
        json={"content": "New summarizer prompt."},
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 200

    # Verify it changed
    resp = client.get(
        "/api/prompts/prompts/summarizer",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.json()["content"] == "New summarizer prompt."


def test_read_nonexistent_returns_404(app_with_prompts):
    client = app_with_prompts
    resp = client.get(
        "/api/prompts/agent/nonexistent",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 404


def test_invalid_directory_returns_400(app_with_prompts):
    client = app_with_prompts
    resp = client.get(
        "/api/prompts/invalid/identity",
        headers={"Authorization": "Bearer test-key"},
    )
    assert resp.status_code == 400
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_prompts_api.py -v`
Expected: FAIL (module not found)

**Step 3: Write the implementation**

```python
"""API endpoints for listing, reading, and editing prompt files."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from odigos.api.deps import require_api_key

router = APIRouter(prefix="/api/prompts", tags=["prompts"], dependencies=[Depends(require_api_key)])

# Mutable for test patching
_PROMPT_DIRS: dict[str, str] = {
    "agent": "data/agent",
    "prompts": "data/prompts",
}


class PromptUpdate(BaseModel):
    content: str


@router.get("")
async def list_prompts():
    """List all prompt files from both directories."""
    results = []
    for directory, dir_path in _PROMPT_DIRS.items():
        p = Path(dir_path)
        if not p.exists():
            continue
        for f in sorted(p.glob("*.md")):
            results.append({
                "name": f.stem,
                "directory": directory,
                "path": str(f),
            })
    return results


@router.get("/{directory}/{name}")
async def read_prompt(directory: str, name: str):
    """Read a prompt file's content."""
    if directory not in _PROMPT_DIRS:
        raise HTTPException(status_code=400, detail=f"Invalid directory: {directory}. Must be one of: {list(_PROMPT_DIRS.keys())}")

    path = Path(_PROMPT_DIRS[directory]) / f"{name}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Prompt not found: {directory}/{name}")

    return {"name": name, "directory": directory, "content": path.read_text()}


@router.put("/{directory}/{name}")
async def update_prompt(directory: str, name: str, body: PromptUpdate):
    """Update a prompt file's content."""
    if directory not in _PROMPT_DIRS:
        raise HTTPException(status_code=400, detail=f"Invalid directory: {directory}")

    dir_path = Path(_PROMPT_DIRS[directory])
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{name}.md"
    path.write_text(body.content)

    return {"name": name, "directory": directory, "status": "updated"}
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_prompts_api.py -v`
Expected: PASS (5/5)

**Step 5: Commit**

```bash
git add odigos/api/prompts.py tests/test_prompts_api.py
git commit -m "feat: add prompts API for listing, reading, editing prompt files"
```

---

### Task 13: Run full test suite and fix any remaining breakage

**Files:**
- Potentially any file with stale imports

**Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v --tb=short 2>&1 | tail -50`

**Step 2: Fix any remaining import errors**

The most likely issues:
- Any test or module still importing `Personality` from `odigos.personality.loader`
- Any test still importing `ENTITY_EXTRACTION_INSTRUCTION`, `CORRECTION_DETECTION_INSTRUCTION`, `SKILL_CREATION_INSTRUCTION` from `prompt_builder`
- Any code still passing `personality_path` or `personality` to constructors

Search for remaining references:
```bash
grep -rn "from odigos.personality.loader" odigos/ tests/
grep -rn "personality_path" odigos/ tests/
grep -rn "PersonalityConfig" odigos/ tests/
grep -rn "ENTITY_EXTRACTION_INSTRUCTION\|CORRECTION_DETECTION_INSTRUCTION\|SKILL_CREATION_INSTRUCTION" odigos/ tests/
grep -rn "load_personality" odigos/ tests/
grep -rn "personality\.path" odigos/ tests/
```

Fix each broken reference. Common fixes:
- Remove unused imports
- Remove deleted parameters from constructor calls
- Update test assertions that relied on legacy personality building

**Step 3: Run full test suite again**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add -u
git commit -m "fix: clean up stale imports and references after personality removal"
```

---

### Task 14: Clean up old `data/prompt_sections/` directory

**Files:**
- Delete: `data/prompt_sections/` (after migration logic is in place)

**Step 1: Verify migration works**

The migration logic in `main.py` (Task 10) copies `data/prompt_sections/` to `data/agent/` if the latter doesn't exist. Since we've already created `data/agent/` with the correct files, the migration won't trigger. The old directory is now redundant.

**Step 2: Delete**

```bash
rm -rf data/prompt_sections/
```

**Step 3: Update `install.sh` and `install-bare.sh` `mkdir` lines**

Both scripts have:
```bash
mkdir -p data data/plugins data/files skills plugins
```

Update to include new directories:
```bash
mkdir -p data data/agent data/prompts data/plugins data/files skills plugins
```

**Step 4: Commit**

```bash
git add -u
git add install.sh install-bare.sh
git commit -m "chore: remove data/prompt_sections/, add data/agent/ and data/prompts/ to install scripts"
```

---

### Task 15: Final integration test — verify agent starts and prompts load

**Step 1: Verify all prompt files exist**

```bash
ls -la data/agent/
ls -la data/prompts/
```

Expected: 6 files in `data/agent/` (identity, voice, meta, entity_extraction, correction_detection, skill_creation) and 7 files in `data/prompts/` (summarizer, evaluator_rubric, evaluator_scoring, strategist, heartbeat_idle, subagent, spawner_adapt).

**Step 2: Run full test suite one final time**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS

**Step 3: Verify no stale references remain**

```bash
grep -rn "prompt_sections" odigos/ tests/ --include="*.py"
grep -rn "personality\.yaml" odigos/ tests/ --include="*.py"
grep -rn "from odigos.personality.loader" odigos/ tests/ --include="*.py"
```

Expected: Zero matches (except possibly comments or migration logic in `main.py`)

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: Phase 5 completion — voice install + prompt reorganization"
```
