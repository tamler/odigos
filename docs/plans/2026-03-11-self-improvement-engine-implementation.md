# Self-Improvement Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give Odigos an autonomous self-improvement loop: evaluate past actions, run time-boxed trials on prompt/personality/skill changes, auto-revert failures via deadman switch.

**Architecture:** Plug into the existing heartbeat idle phase. Evaluator scores past actions using fallback model. CheckpointManager keeps known-good state on disk, trial overrides in DB only. EvolutionEngine manages trial lifecycle. Dynamic prompt sections replace static prompt_builder template.

**Tech Stack:** Python 3.12, aiosqlite, existing LLMProvider, existing heartbeat/goal_store infrastructure

**Reference:** Read `docs/plans/2026-03-11-self-improvement-engine-design.md` for full design rationale.

---

### Task 1: Database Migration

**Files:**
- Create: `migrations/015_evolution.sql`

**Step 1: Write the migration**

```sql
-- Checkpoints: snapshots of known-good agent state
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES checkpoints(id),
    label TEXT,
    personality_snapshot TEXT,
    prompt_sections_snapshot TEXT,
    skills_snapshot TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Trials: time-boxed experiments on agent behavior
CREATE TABLE IF NOT EXISTS trials (
    id TEXT PRIMARY KEY,
    checkpoint_id TEXT REFERENCES checkpoints(id),
    hypothesis TEXT NOT NULL,
    target TEXT NOT NULL,
    change_description TEXT,
    status TEXT DEFAULT 'active',
    started_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    min_evaluations INTEGER DEFAULT 5,
    evaluation_count INTEGER DEFAULT 0,
    avg_score REAL,
    baseline_avg_score REAL,
    result_notes TEXT,
    direction_log_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trials_status ON trials(status);

-- Trial overrides: ephemeral changes (deadman switch - never written to disk)
CREATE TABLE IF NOT EXISTS trial_overrides (
    id TEXT PRIMARY KEY,
    trial_id TEXT REFERENCES trials(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL,
    target_name TEXT NOT NULL,
    override_content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trial_overrides_trial ON trial_overrides(trial_id);

-- Evaluations: C.1/C.2 scoring of past actions
CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    message_id TEXT,
    conversation_id TEXT,
    task_type TEXT,
    rubric TEXT,
    scores TEXT,
    overall_score REAL,
    improvement_signal TEXT,
    implicit_feedback REAL,
    trial_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_evaluations_trial ON evaluations(trial_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_created ON evaluations(created_at);

-- Rubric cache: reuse rubrics by task type
CREATE TABLE IF NOT EXISTS rubric_cache (
    task_type TEXT PRIMARY KEY,
    rubric TEXT NOT NULL,
    usage_count INTEGER DEFAULT 1,
    last_used_at TEXT DEFAULT (datetime('now'))
);

-- Failed trials log: prevent retry loops
CREATE TABLE IF NOT EXISTS failed_trials_log (
    id TEXT PRIMARY KEY,
    trial_id TEXT REFERENCES trials(id),
    hypothesis TEXT,
    target TEXT,
    change_description TEXT,
    scores_summary TEXT,
    failure_reason TEXT,
    lessons TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Direction log: agent's evolving self-assessment
CREATE TABLE IF NOT EXISTS direction_log (
    id TEXT PRIMARY KEY,
    analysis TEXT,
    direction TEXT,
    opportunities TEXT,
    hypotheses TEXT,
    confidence REAL,
    based_on_evaluations INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
```

**Step 2: Verify migration applies**

Run: `cd /Users/jacob/Projects/odigos && python -c "import asyncio; from odigos.db import Database; db = Database('data/test_evolution.db'); asyncio.run(db.initialize()); print('Migration OK'); import os; os.remove('data/test_evolution.db')"`
Expected: `Migration OK`

**Step 3: Commit**

```bash
git add migrations/015_evolution.sql
git commit -m "feat: add evolution system database tables"
```

---

### Task 2: Dynamic Prompt Sections — Section Registry

**Files:**
- Create: `odigos/personality/section_registry.py`
- Create: `data/prompt_sections/identity.md`
- Create: `data/prompt_sections/voice.md`
- Create: `data/prompt_sections/meta.md`
- Test: `tests/test_section_registry.py`

**Context:** This replaces the static `_build_identity_section()` and `_build_voice_section()` in `prompt_builder.py` (lines 81-112) with hot-loadable markdown files. Each file has YAML frontmatter for priority and inclusion rules.

**Step 1: Write the failing test**

```python
"""Tests for the prompt section registry."""
import os
import tempfile
from pathlib import Path

import pytest

from odigos.personality.section_registry import SectionRegistry, PromptSection


@pytest.fixture
def sections_dir():
    with tempfile.TemporaryDirectory() as d:
        # Create a test section
        Path(d, "identity.md").write_text(
            "---\npriority: 10\nalways_include: true\n---\nYou are a test agent."
        )
        Path(d, "voice.md").write_text(
            "---\npriority: 20\nalways_include: true\n---\n## Voice\nBe concise."
        )
        Path(d, "optional.md").write_text(
            "---\npriority: 50\nalways_include: false\n---\nOptional context."
        )
        yield d


def test_load_all_sections(sections_dir):
    registry = SectionRegistry(sections_dir)
    sections = registry.load_all()
    assert len(sections) == 3
    # Sorted by priority
    assert sections[0].name == "identity"
    assert sections[1].name == "voice"
    assert sections[2].name == "optional"


def test_section_content_strips_frontmatter(sections_dir):
    registry = SectionRegistry(sections_dir)
    sections = registry.load_all()
    identity = sections[0]
    assert identity.content == "You are a test agent."
    assert "---" not in identity.content


def test_section_properties(sections_dir):
    registry = SectionRegistry(sections_dir)
    sections = registry.load_all()
    assert sections[0].priority == 10
    assert sections[0].always_include is True
    assert sections[2].always_include is False


def test_caching_by_mtime(sections_dir):
    registry = SectionRegistry(sections_dir)
    s1 = registry.load_all()
    s2 = registry.load_all()
    # Same objects if files haven't changed
    assert s1[0].content == s2[0].content


def test_override_merging(sections_dir):
    registry = SectionRegistry(sections_dir)
    overrides = {"identity": "You are an evolved agent."}
    sections = registry.load_all(overrides=overrides)
    identity = [s for s in sections if s.name == "identity"][0]
    assert identity.content == "You are an evolved agent."


def test_missing_dir_returns_empty():
    registry = SectionRegistry("/nonexistent/path")
    assert registry.load_all() == []
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_section_registry.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
"""Registry for dynamic, evolvable prompt sections."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class PromptSection:
    name: str
    content: str
    priority: int = 50
    always_include: bool = True
    max_tokens: int = 0  # 0 = unlimited


class SectionRegistry:
    """Load prompt sections from markdown files with YAML frontmatter.

    Files are cached by mtime and can be overridden by trial overrides.
    """

    def __init__(self, sections_dir: str) -> None:
        self._dir = Path(sections_dir)
        self._cache: dict[str, tuple[float, PromptSection]] = {}

    def load_all(
        self, overrides: dict[str, str] | None = None
    ) -> list[PromptSection]:
        """Load all sections, applying any trial overrides.

        Returns sections sorted by priority (lowest first).
        """
        if not self._dir.exists():
            return []

        sections: list[PromptSection] = []
        for path in sorted(self._dir.glob("*.md")):
            name = path.stem
            section = self._load_one(path)
            if section is None:
                continue
            # Apply trial override if present
            if overrides and name in overrides:
                section = PromptSection(
                    name=section.name,
                    content=overrides[name],
                    priority=section.priority,
                    always_include=section.always_include,
                    max_tokens=section.max_tokens,
                )
            sections.append(section)
        sections.sort(key=lambda s: s.priority)
        return sections

    def _load_one(self, path: Path) -> PromptSection | None:
        """Load a single section file, using cache if mtime unchanged."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None

        cached = self._cache.get(path.name)
        if cached and cached[0] == mtime:
            return cached[1]

        try:
            raw = path.read_text()
        except OSError:
            return None

        frontmatter, content = _parse_frontmatter(raw)
        section = PromptSection(
            name=path.stem,
            content=content.strip(),
            priority=frontmatter.get("priority", 50),
            always_include=frontmatter.get("always_include", True),
            max_tokens=frontmatter.get("max_tokens", 0),
        )
        self._cache[path.name] = (mtime, section)
        return section


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown content."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2]
```

**Step 4: Create seed prompt section files**

`data/prompt_sections/identity.md`:
```markdown
---
priority: 10
always_include: true
---
You are {name}, a personal AI agent. You serve as a trusted aide — not a servant, not a peer. Speak in first person. When you're not sure about something, say so honestly rather than guessing. When asked, share your perspective with reasoning.
```

`data/prompt_sections/voice.md`:
```markdown
---
priority: 20
always_include: true
---
## Communication style
- Tone: direct, warm, slightly informal
- Verbosity: concise by default, detailed when asked
- Humor: dry, occasional, never forced
- Formality: casual with owner, professional with others
```

`data/prompt_sections/meta.md`:
```markdown
---
priority: 90
always_include: true
---
## Self-improvement
You have an evolution system that tests changes to your behavior. If you notice patterns in how users correct you, or areas where you consistently underperform, you can note these observations — they feed into your self-improvement cycle. Focus on being genuinely helpful rather than performing helpfulness.
```

**Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_section_registry.py -v`
Expected: All 6 tests PASS

**Step 6: Commit**

```bash
git add odigos/personality/section_registry.py tests/test_section_registry.py data/prompt_sections/
git commit -m "feat: add dynamic prompt section registry with hot-reload and override support"
```

---

### Task 3: CheckpointManager — Deadman Switch

**Files:**
- Create: `odigos/core/checkpoint.py`
- Test: `tests/test_checkpoint.py`

**Context:** Known-good state lives on disk. Trial overrides live in DB only. If the process crashes, disk state is all that remains — automatic revert with zero recovery code.

**Step 1: Write the failing test**

```python
"""Tests for the checkpoint manager (deadman switch)."""
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from odigos.core.checkpoint import CheckpointManager
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def sections_dir():
    with tempfile.TemporaryDirectory() as d:
        (open(os.path.join(d, "identity.md"), "w")).write(
            "---\npriority: 10\nalways_include: true\n---\nYou are Odigos."
        )
        (open(os.path.join(d, "voice.md"), "w")).write(
            "---\npriority: 20\nalways_include: true\n---\nBe concise."
        )
        yield d


@pytest.mark.asyncio
async def test_create_checkpoint(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    cp_id = await mgr.create_checkpoint(label="initial")
    assert cp_id is not None
    row = await db.fetch_one("SELECT * FROM checkpoints WHERE id = ?", (cp_id,))
    assert row["label"] == "initial"
    snapshot = json.loads(row["prompt_sections_snapshot"])
    assert "identity" in snapshot
    assert "voice" in snapshot


@pytest.mark.asyncio
async def test_get_working_sections_no_trial(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    sections = await mgr.get_working_sections()
    names = [s.name for s in sections]
    assert "identity" in names
    assert "voice" in names


@pytest.mark.asyncio
async def test_get_working_sections_with_active_override(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    # Create a trial with override
    trial_id = str(uuid.uuid4())
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    await db.execute(
        "INSERT INTO trials (id, checkpoint_id, hypothesis, target, expires_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (trial_id, "none", "test hypothesis", "prompt_section", expires, "active"),
    )
    override_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO trial_overrides (id, trial_id, target_type, target_name, override_content) "
        "VALUES (?, ?, ?, ?, ?)",
        (override_id, trial_id, "prompt_section", "identity", "You are an evolved agent."),
    )
    sections = await mgr.get_working_sections()
    identity = [s for s in sections if s.name == "identity"][0]
    assert identity.content == "You are an evolved agent."


@pytest.mark.asyncio
async def test_expired_override_ignored(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    # Create an expired trial
    trial_id = str(uuid.uuid4())
    expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await db.execute(
        "INSERT INTO trials (id, checkpoint_id, hypothesis, target, expires_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (trial_id, "none", "expired hypothesis", "prompt_section", expired, "active"),
    )
    override_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO trial_overrides (id, trial_id, target_type, target_name, override_content) "
        "VALUES (?, ?, ?, ?, ?)",
        (override_id, trial_id, "prompt_section", "identity", "Should not appear."),
    )
    sections = await mgr.get_working_sections()
    identity = [s for s in sections if s.name == "identity"][0]
    assert identity.content == "You are Odigos."


@pytest.mark.asyncio
async def test_promote_trial_writes_to_disk(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    cp_id = await mgr.create_checkpoint(label="before-trial")
    trial_id = str(uuid.uuid4())
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    await db.execute(
        "INSERT INTO trials (id, checkpoint_id, hypothesis, target, expires_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (trial_id, cp_id, "improve identity", "prompt_section", expires, "active"),
    )
    override_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO trial_overrides (id, trial_id, target_type, target_name, override_content) "
        "VALUES (?, ?, ?, ?, ?)",
        (override_id, trial_id, "prompt_section", "identity", "You are an evolved agent."),
    )
    await mgr.promote_trial(trial_id)
    # Verify written to disk
    content = open(os.path.join(sections_dir, "identity.md")).read()
    assert "You are an evolved agent." in content
    # Verify overrides deleted
    row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM trial_overrides WHERE trial_id = ?", (trial_id,)
    )
    assert row["cnt"] == 0
    # Verify trial status
    trial = await db.fetch_one("SELECT status FROM trials WHERE id = ?", (trial_id,))
    assert trial["status"] == "promoted"


@pytest.mark.asyncio
async def test_revert_trial_deletes_overrides(db, sections_dir):
    mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    trial_id = str(uuid.uuid4())
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    await db.execute(
        "INSERT INTO trials (id, checkpoint_id, hypothesis, target, expires_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (trial_id, "none", "bad hypothesis", "prompt_section", expires, "active"),
    )
    override_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO trial_overrides (id, trial_id, target_type, target_name, override_content) "
        "VALUES (?, ?, ?, ?, ?)",
        (override_id, trial_id, "prompt_section", "identity", "Bad content."),
    )
    await mgr.revert_trial(trial_id, reason="worse_than_baseline")
    # Overrides gone
    row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM trial_overrides WHERE trial_id = ?", (trial_id,)
    )
    assert row["cnt"] == 0
    # Trial status updated
    trial = await db.fetch_one("SELECT status FROM trials WHERE id = ?", (trial_id,))
    assert trial["status"] == "reverted"
    # Disk unchanged
    content = open(os.path.join(sections_dir, "identity.md")).read()
    assert "You are Odigos." in content
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_checkpoint.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
"""CheckpointManager: deadman switch for agent evolution.

Known-good state lives on disk. Trial overrides live in DB only.
If the process crashes, disk state is all that remains.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from odigos.personality.section_registry import SectionRegistry

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)


class CheckpointManager:

    def __init__(
        self,
        db: Database,
        sections_dir: str,
        personality_path: str = "data/personality.yaml",
        skills_dir: str = "skills",
    ) -> None:
        self.db = db
        self._sections_dir = sections_dir
        self._personality_path = personality_path
        self._skills_dir = skills_dir
        self._section_registry = SectionRegistry(sections_dir)

    async def create_checkpoint(self, label: str = "", parent_id: str | None = None) -> str:
        """Snapshot current disk state into a checkpoint record."""
        cp_id = str(uuid.uuid4())

        # Snapshot personality
        personality_snapshot = ""
        p_path = Path(self._personality_path)
        if p_path.exists():
            personality_snapshot = p_path.read_text()

        # Snapshot prompt sections
        sections_snapshot = {}
        s_dir = Path(self._sections_dir)
        if s_dir.exists():
            for f in s_dir.glob("*.md"):
                sections_snapshot[f.stem] = f.read_text()

        # Snapshot skills
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
                personality_snapshot,
                json.dumps(sections_snapshot),
                json.dumps(skills_snapshot),
            ),
        )
        return cp_id

    async def get_working_sections(self) -> list:
        """Load sections from disk, merging any active non-expired trial overrides."""
        overrides = await self._get_active_overrides()
        return self._section_registry.load_all(overrides=overrides)

    async def _get_active_overrides(self) -> dict[str, str]:
        """Get overrides from active, non-expired trials."""
        now = datetime.now(timezone.utc).isoformat()
        rows = await self.db.fetch_all(
            "SELECT o.target_name, o.override_content "
            "FROM trial_overrides o "
            "JOIN trials t ON o.trial_id = t.id "
            "WHERE t.status = 'active' AND t.expires_at > ?",
            (now,),
        )
        return {row["target_name"]: row["override_content"] for row in rows}

    async def promote_trial(self, trial_id: str) -> str:
        """Write trial overrides to disk, creating a new checkpoint."""
        # Get overrides
        overrides = await self.db.fetch_all(
            "SELECT target_type, target_name, override_content "
            "FROM trial_overrides WHERE trial_id = ?",
            (trial_id,),
        )

        # Create checkpoint of current state before writing
        cp_id = await self.create_checkpoint(label=f"pre-promote-{trial_id[:8]}")

        # Write overrides to disk
        for row in overrides:
            if row["target_type"] == "prompt_section":
                path = Path(self._sections_dir) / f"{row['target_name']}.md"
                # Preserve frontmatter if file exists
                existing = ""
                if path.exists():
                    existing = path.read_text()
                frontmatter = _extract_frontmatter(existing)
                path.write_text(f"{frontmatter}{row['override_content']}")

        # Clean up: delete overrides, update trial status
        await self.db.execute(
            "DELETE FROM trial_overrides WHERE trial_id = ?", (trial_id,)
        )
        await self.db.execute(
            "UPDATE trials SET status = 'promoted', result_notes = 'Promoted to known-good' "
            "WHERE id = ?",
            (trial_id,),
        )
        logger.info("Promoted trial %s, new checkpoint %s", trial_id[:8], cp_id[:8])
        return cp_id

    async def revert_trial(self, trial_id: str, reason: str = "") -> None:
        """Delete trial overrides (disk unchanged = automatic revert)."""
        await self.db.execute(
            "DELETE FROM trial_overrides WHERE trial_id = ?", (trial_id,)
        )
        await self.db.execute(
            "UPDATE trials SET status = 'reverted', result_notes = ? WHERE id = ?",
            (reason, trial_id),
        )
        logger.info("Reverted trial %s: %s", trial_id[:8], reason)

    async def get_active_trial(self) -> dict | None:
        """Get the currently active trial, if any."""
        now = datetime.now(timezone.utc).isoformat()
        return await self.db.fetch_one(
            "SELECT * FROM trials WHERE status = 'active' AND expires_at > ? "
            "ORDER BY started_at DESC LIMIT 1",
            (now,),
        )

    async def expire_stale_trials(self) -> int:
        """Expire any trials past their time cap. Returns count expired."""
        now = datetime.now(timezone.utc).isoformat()
        stale = await self.db.fetch_all(
            "SELECT id FROM trials WHERE status = 'active' AND expires_at <= ?",
            (now,),
        )
        for row in stale:
            await self.revert_trial(row["id"], reason="expired")
        return len(stale)


def _extract_frontmatter(text: str) -> str:
    """Extract YAML frontmatter block (including delimiters) from text."""
    if not text.startswith("---"):
        return "---\npriority: 50\nalways_include: true\n---\n"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "---\npriority: 50\nalways_include: true\n---\n"
    return f"---{parts[1]}---\n"
```

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_checkpoint.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add odigos/core/checkpoint.py tests/test_checkpoint.py
git commit -m "feat: add CheckpointManager with deadman switch for trial overrides"
```

---

### Task 4: Evaluator — Implicit Feedback + C.1/C.2 Scoring

**Files:**
- Create: `odigos/core/evaluator.py`
- Test: `tests/test_evaluator.py`

**Context:** The evaluator has two jobs: (1) infer feedback from user behavior after a response, and (2) score past actions using the LLM via C.1 rubric generation and C.2 scoring. Uses the fallback model to minimize cost. Stores results in the `evaluations` table.

**Step 1: Write the failing test**

```python
"""Tests for the evaluator (implicit feedback + C.1/C.2 scoring)."""
import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.evaluator import Evaluator, infer_implicit_feedback
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.fallback_model = "test-fallback"
    return provider


def _insert_message(db, conv_id, role, content, ts_offset_minutes=0):
    """Helper to insert a message with controlled timestamp."""
    msg_id = str(uuid.uuid4())
    ts = (datetime.now(timezone.utc) + timedelta(minutes=ts_offset_minutes)).isoformat()
    return msg_id, db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (msg_id, conv_id, role, content, ts),
    )


# --- Implicit feedback inference tests ---

@pytest.mark.asyncio
async def test_feedback_correction_is_negative(db):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "test")
    )
    _, coro = _insert_message(db, conv_id, "user", "What is Python?", -2)
    await coro
    asst_id, coro = _insert_message(db, conv_id, "assistant", "Python is a snake.", -1)
    await coro
    _, coro = _insert_message(db, conv_id, "user", "No, I meant the programming language.", 0)
    await coro

    score = await infer_implicit_feedback(db, asst_id, conv_id)
    assert score < 0  # Correction = negative


@pytest.mark.asyncio
async def test_feedback_acknowledgment_is_positive(db):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "test")
    )
    _, coro = _insert_message(db, conv_id, "user", "Explain decorators", -2)
    await coro
    asst_id, coro = _insert_message(db, conv_id, "assistant", "Decorators wrap functions...", -1)
    await coro
    _, coro = _insert_message(db, conv_id, "user", "Thanks, that makes sense!", 0)
    await coro

    score = await infer_implicit_feedback(db, asst_id, conv_id)
    assert score > 0  # Acknowledgment = positive


# --- C.1/C.2 scoring tests ---

@pytest.mark.asyncio
async def test_evaluate_action_stores_result(db, mock_provider):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "test")
    )
    msg_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
        (msg_id, conv_id, "assistant", "Here is some code..."),
    )
    # Mock LLM returns rubric then score
    mock_provider.complete = AsyncMock(side_effect=[
        # C.1 rubric response
        AsyncMock(content=json.dumps({
            "task_type": "code_generation",
            "criteria": [{"name": "correctness", "weight": 1.0, "description": "code works"}],
            "notes": "test",
        })),
        # C.2 score response
        AsyncMock(content=json.dumps({
            "scores": [{"criterion": "correctness", "score": 8, "observation": "looks good"}],
            "overall": 8.0,
            "improvement_signal": None,
        })),
    ])

    evaluator = Evaluator(db=db, provider=mock_provider)
    result = await evaluator.evaluate_action(msg_id, conv_id)

    assert result is not None
    assert result["overall_score"] == 8.0
    # Verify stored in DB
    row = await db.fetch_one("SELECT * FROM evaluations WHERE message_id = ?", (msg_id,))
    assert row is not None
    assert row["overall_score"] == 8.0


@pytest.mark.asyncio
async def test_get_unscored_messages(db, mock_provider):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "test")
    )
    # Insert 3 assistant messages
    for i in range(3):
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), conv_id, "assistant", f"Response {i}"),
        )
    evaluator = Evaluator(db=db, provider=mock_provider)
    unscored = await evaluator.get_unscored_messages(limit=5)
    assert len(unscored) == 3
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_evaluator.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
"""Evaluator: implicit feedback inference + C.1/C.2 LLM-based scoring.

Uses the fallback model for all evaluation calls to minimize cost.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Keywords suggesting user is correcting the agent
_CORRECTION_MARKERS = [
    "no,", "no ", "actually", "i meant", "that's wrong", "not what i",
    "incorrect", "you misunderstood", "try again", "that's not",
]

# Keywords suggesting user is acknowledging/thanking
_POSITIVE_MARKERS = [
    "thanks", "thank you", "perfect", "great", "awesome", "that works",
    "makes sense", "got it", "exactly", "nice", "good job", "helpful",
]


async def infer_implicit_feedback(
    db: Database, assistant_message_id: str, conversation_id: str
) -> float:
    """Infer user satisfaction from behavior after a response.

    Returns -1.0 to 1.0. Negative = dissatisfied, positive = satisfied.
    """
    # Get the assistant message timestamp
    asst_msg = await db.fetch_one(
        "SELECT timestamp FROM messages WHERE id = ?", (assistant_message_id,)
    )
    if not asst_msg:
        return 0.0

    # Get the next user message after this response
    next_user = await db.fetch_one(
        "SELECT content, timestamp FROM messages "
        "WHERE conversation_id = ? AND role = 'user' AND timestamp > ? "
        "ORDER BY timestamp ASC LIMIT 1",
        (conversation_id, asst_msg["timestamp"]),
    )

    if next_user is None:
        # No follow-up — mild negative (abandoned)
        return -0.2

    content_lower = next_user["content"].lower().strip()

    # Check for correction signals
    for marker in _CORRECTION_MARKERS:
        if content_lower.startswith(marker) or marker in content_lower[:50]:
            return -0.7

    # Check for positive signals
    for marker in _POSITIVE_MARKERS:
        if marker in content_lower:
            return 0.5

    # Neutral — user continued conversation
    return 0.2


class Evaluator:
    """Scores past agent actions via rubric generation (C.1) and scoring (C.2)."""

    def __init__(self, db: Database, provider: LLMProvider) -> None:
        self.db = db
        self.provider = provider

    async def get_unscored_messages(self, limit: int = 5) -> list[dict]:
        """Find assistant messages that haven't been evaluated yet."""
        rows = await self.db.fetch_all(
            "SELECT m.id, m.conversation_id, m.content, m.timestamp "
            "FROM messages m "
            "LEFT JOIN evaluations e ON m.id = e.message_id "
            "WHERE m.role = 'assistant' AND e.id IS NULL "
            "ORDER BY m.timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    async def evaluate_action(
        self,
        message_id: str,
        conversation_id: str,
        trial_id: str | None = None,
    ) -> dict | None:
        """Run C.1 (rubric) + C.2 (score) on a past action. Returns evaluation dict."""
        # Get the assistant message and preceding user message
        asst_msg = await self.db.fetch_one(
            "SELECT content, timestamp FROM messages WHERE id = ?", (message_id,)
        )
        if not asst_msg:
            return None

        user_msg = await self.db.fetch_one(
            "SELECT content FROM messages "
            "WHERE conversation_id = ? AND role = 'user' AND timestamp < ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (conversation_id, asst_msg["timestamp"]),
        )
        user_content = user_msg["content"] if user_msg else "(no user message)"

        # Infer implicit feedback
        feedback = await infer_implicit_feedback(self.db, message_id, conversation_id)

        # C.1: Generate or retrieve rubric
        rubric = await self._get_or_generate_rubric(user_content, asst_msg["content"], feedback)
        if rubric is None:
            return None

        # C.2: Score against rubric
        scores = await self._score_against_rubric(rubric, user_content, asst_msg["content"], feedback)
        if scores is None:
            return None

        # Store evaluation
        eval_id = str(uuid.uuid4())
        task_type = rubric.get("task_type", "unknown")
        overall = scores.get("overall", 0.0)

        await self.db.execute(
            "INSERT INTO evaluations (id, message_id, conversation_id, task_type, "
            "rubric, scores, overall_score, improvement_signal, implicit_feedback, trial_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eval_id,
                message_id,
                conversation_id,
                task_type,
                json.dumps(rubric),
                json.dumps(scores),
                overall,
                scores.get("improvement_signal"),
                feedback,
                trial_id,
            ),
        )

        # Cache rubric by task type
        await self._cache_rubric(task_type, rubric)

        return {
            "eval_id": eval_id,
            "task_type": task_type,
            "overall_score": overall,
            "implicit_feedback": feedback,
            "improvement_signal": scores.get("improvement_signal"),
        }

    async def _get_or_generate_rubric(
        self, user_content: str, assistant_content: str, feedback: float
    ) -> dict | None:
        """Check rubric cache first, then generate via C.1."""
        # Try cache (simplified: check if we've scored this task type before)
        # Full rubric caching is deferred — always generate for now

        prompt = (
            "You are evaluating an AI assistant's response. "
            "Generate a scoring rubric for this type of interaction.\n\n"
            f"User message: {user_content[:500]}\n"
            f"Assistant response: {assistant_content[:500]}\n"
            f"User reaction signal: {feedback:.1f} (-1=negative, +1=positive)\n\n"
            "Return ONLY a JSON object:\n"
            '{"task_type": "category", "criteria": [{"name": "...", "weight": 0.0-1.0, '
            '"description": "what good looks like"}], "notes": "..."}'
        )
        try:
            response = await self.provider.complete(
                [{"role": "user", "content": prompt}],
                model=getattr(self.provider, "fallback_model", None),
                max_tokens=300,
                temperature=0.2,
            )
            return _parse_json(response.content)
        except Exception:
            logger.warning("C.1 rubric generation failed", exc_info=True)
            return None

    async def _score_against_rubric(
        self, rubric: dict, user_content: str, assistant_content: str, feedback: float
    ) -> dict | None:
        """C.2: Score the interaction against the rubric."""
        prompt = (
            "Score this AI assistant interaction against the rubric.\n\n"
            f"Rubric: {json.dumps(rubric)}\n\n"
            f"User message: {user_content[:500]}\n"
            f"Assistant response: {assistant_content[:500]}\n"
            f"User reaction signal: {feedback:.1f}\n\n"
            "Return ONLY a JSON object:\n"
            '{"scores": [{"criterion": "name", "score": 0-10, "observation": "..."}], '
            '"overall": 0-10, "improvement_signal": "what would have been better" or null}'
        )
        try:
            response = await self.provider.complete(
                [{"role": "user", "content": prompt}],
                model=getattr(self.provider, "fallback_model", None),
                max_tokens=300,
                temperature=0.2,
            )
            return _parse_json(response.content)
        except Exception:
            logger.warning("C.2 scoring failed", exc_info=True)
            return None

    async def _cache_rubric(self, task_type: str, rubric: dict) -> None:
        """Store/update rubric in cache."""
        try:
            existing = await self.db.fetch_one(
                "SELECT task_type FROM rubric_cache WHERE task_type = ?", (task_type,)
            )
            if existing:
                await self.db.execute(
                    "UPDATE rubric_cache SET usage_count = usage_count + 1, "
                    "last_used_at = datetime('now') WHERE task_type = ?",
                    (task_type,),
                )
            else:
                await self.db.execute(
                    "INSERT INTO rubric_cache (task_type, rubric) VALUES (?, ?)",
                    (task_type, json.dumps(rubric)),
                )
        except Exception:
            pass  # Cache is best-effort


def _parse_json(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown code blocks."""
    import re
    # Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try extracting from code block
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    # Try finding JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, TypeError):
            pass
    return None
```

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_evaluator.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add odigos/core/evaluator.py tests/test_evaluator.py
git commit -m "feat: add Evaluator with implicit feedback inference and C.1/C.2 scoring"
```

---

### Task 5: EvolutionEngine — Trial Lifecycle + Direction Log

**Files:**
- Create: `odigos/core/evolution.py`
- Test: `tests/test_evolution.py`

**Context:** The EvolutionEngine orchestrates the full self-improvement cycle. It creates trials from hypotheses, monitors active trials, promotes/reverts based on evaluation scores, and maintains the failed-trial log and direction log. This is the coordinator that ties evaluator + checkpoint together.

**Step 1: Write the failing test**

```python
"""Tests for the EvolutionEngine."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from odigos.core.evolution import EvolutionEngine
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def mock_checkpoint():
    mgr = AsyncMock()
    mgr.create_checkpoint = AsyncMock(return_value="cp-123")
    mgr.get_active_trial = AsyncMock(return_value=None)
    mgr.promote_trial = AsyncMock(return_value="cp-456")
    mgr.revert_trial = AsyncMock()
    mgr.expire_stale_trials = AsyncMock(return_value=0)
    return mgr


@pytest.fixture
def mock_evaluator():
    ev = AsyncMock()
    ev.get_unscored_messages = AsyncMock(return_value=[])
    ev.evaluate_action = AsyncMock(return_value={
        "eval_id": "eval-1",
        "task_type": "general",
        "overall_score": 7.0,
        "implicit_feedback": 0.3,
        "improvement_signal": None,
    })
    return ev


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.fallback_model = "test-fallback"
    return provider


@pytest.mark.asyncio
async def test_create_trial(db, mock_checkpoint, mock_evaluator, mock_provider):
    engine = EvolutionEngine(
        db=db, checkpoint_manager=mock_checkpoint,
        evaluator=mock_evaluator, provider=mock_provider,
    )
    trial_id = await engine.create_trial(
        hypothesis="Be more concise in coding responses",
        target="prompt_section",
        change_description="Shortened voice section",
        overrides={"voice": "Be extremely concise. No fluff."},
    )
    assert trial_id is not None
    trial = await db.fetch_one("SELECT * FROM trials WHERE id = ?", (trial_id,))
    assert trial["status"] == "active"
    assert trial["hypothesis"] == "Be more concise in coding responses"
    # Verify override was written
    override = await db.fetch_one(
        "SELECT * FROM trial_overrides WHERE trial_id = ?", (trial_id,)
    )
    assert override["target_name"] == "voice"


@pytest.mark.asyncio
async def test_check_trial_promotes_when_better(db, mock_checkpoint, mock_evaluator, mock_provider):
    engine = EvolutionEngine(
        db=db, checkpoint_manager=mock_checkpoint,
        evaluator=mock_evaluator, provider=mock_provider,
    )
    # Create a trial
    trial_id = await engine.create_trial(
        hypothesis="test", target="prompt_section",
        change_description="test change",
        overrides={"voice": "new voice"},
    )
    # Simulate evaluations showing improvement
    await db.execute(
        "UPDATE trials SET evaluation_count = 6, avg_score = 8.5, "
        "baseline_avg_score = 7.0 WHERE id = ?",
        (trial_id,),
    )
    mock_checkpoint.get_active_trial = AsyncMock(return_value=dict(
        await db.fetch_one("SELECT * FROM trials WHERE id = ?", (trial_id,))
    ))
    await engine.check_active_trial()
    mock_checkpoint.promote_trial.assert_called_once_with(trial_id)


@pytest.mark.asyncio
async def test_check_trial_reverts_when_worse(db, mock_checkpoint, mock_evaluator, mock_provider):
    engine = EvolutionEngine(
        db=db, checkpoint_manager=mock_checkpoint,
        evaluator=mock_evaluator, provider=mock_provider,
    )
    trial_id = await engine.create_trial(
        hypothesis="test", target="prompt_section",
        change_description="bad change",
        overrides={"voice": "bad voice"},
    )
    await db.execute(
        "UPDATE trials SET evaluation_count = 6, avg_score = 5.0, "
        "baseline_avg_score = 7.0 WHERE id = ?",
        (trial_id,),
    )
    mock_checkpoint.get_active_trial = AsyncMock(return_value=dict(
        await db.fetch_one("SELECT * FROM trials WHERE id = ?", (trial_id,))
    ))
    await engine.check_active_trial()
    mock_checkpoint.revert_trial.assert_called_once()
    # Verify failed trial logged
    row = await db.fetch_one("SELECT * FROM failed_trials_log WHERE trial_id = ?", (trial_id,))
    assert row is not None
    assert row["failure_reason"] == "worse_than_baseline"


@pytest.mark.asyncio
async def test_log_direction(db, mock_checkpoint, mock_evaluator, mock_provider):
    engine = EvolutionEngine(
        db=db, checkpoint_manager=mock_checkpoint,
        evaluator=mock_evaluator, provider=mock_provider,
    )
    await engine.log_direction(
        analysis="Scoring well on code tasks, weak on research",
        direction="Focus on improving research depth",
        opportunities=[{"area": "research", "potential": "high"}],
        hypotheses=[],
        confidence=0.7,
        based_on_evaluations=25,
    )
    row = await db.fetch_one("SELECT * FROM direction_log ORDER BY created_at DESC LIMIT 1")
    assert row is not None
    assert "research" in row["direction"]


@pytest.mark.asyncio
async def test_get_failed_trials(db, mock_checkpoint, mock_evaluator, mock_provider):
    engine = EvolutionEngine(
        db=db, checkpoint_manager=mock_checkpoint,
        evaluator=mock_evaluator, provider=mock_provider,
    )
    # Insert a failed trial log entry
    await db.execute(
        "INSERT INTO failed_trials_log (id, trial_id, hypothesis, target, failure_reason, lessons) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "t-1", "be concise", "prompt_section", "worse_than_baseline",
         "Users prefer detailed responses for technical topics"),
    )
    failed = await engine.get_failed_trials(limit=10)
    assert len(failed) == 1
    assert failed[0]["hypothesis"] == "be concise"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_evolution.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
"""EvolutionEngine: orchestrates the self-improvement trial lifecycle.

Creates trials, monitors evaluation scores, promotes or reverts,
maintains failed-trial log and direction log.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.checkpoint import CheckpointManager
    from odigos.core.evaluator import Evaluator
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Trial resolution thresholds
PROMOTE_THRESHOLD = 0.5   # avg_score must exceed baseline by this much
REVERT_THRESHOLD = -0.3   # avg_score below baseline by this much triggers early revert
DEFAULT_TRIAL_HOURS = 48
DEFAULT_MIN_EVALS = 5


class EvolutionEngine:

    def __init__(
        self,
        db: Database,
        checkpoint_manager: CheckpointManager,
        evaluator: Evaluator,
        provider: LLMProvider,
    ) -> None:
        self.db = db
        self.checkpoint = checkpoint_manager
        self.evaluator = evaluator
        self.provider = provider

    # --- Trial creation ---

    async def create_trial(
        self,
        hypothesis: str,
        target: str,
        change_description: str,
        overrides: dict[str, str],
        trial_hours: int = DEFAULT_TRIAL_HOURS,
        min_evaluations: int = DEFAULT_MIN_EVALS,
        direction_log_id: str | None = None,
    ) -> str:
        """Create a new trial with DB-only overrides."""
        # Only one active trial at a time
        active = await self.checkpoint.get_active_trial()
        if active:
            logger.warning("Cannot create trial: trial %s already active", active["id"][:8])
            return active["id"]

        # Snapshot current state
        cp_id = await self.checkpoint.create_checkpoint(label=f"pre-trial")

        # Get baseline score
        baseline = await self._get_baseline_score()

        trial_id = str(uuid.uuid4())
        expires = (datetime.now(timezone.utc) + timedelta(hours=trial_hours)).isoformat()

        await self.db.execute(
            "INSERT INTO trials (id, checkpoint_id, hypothesis, target, "
            "change_description, expires_at, min_evaluations, "
            "baseline_avg_score, direction_log_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trial_id, cp_id, hypothesis, target,
                change_description, expires, min_evaluations,
                baseline, direction_log_id,
            ),
        )

        # Write overrides to DB
        for name, content in overrides.items():
            await self.db.execute(
                "INSERT INTO trial_overrides (id, trial_id, target_type, target_name, "
                "override_content) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), trial_id, target, name, content),
            )

        logger.info(
            "Created trial %s: %s (expires %s)",
            trial_id[:8], hypothesis[:50], expires,
        )
        return trial_id

    # --- Trial monitoring ---

    async def check_active_trial(self) -> str | None:
        """Check if the active trial should be promoted, reverted, or continue.

        Returns: 'promoted', 'reverted', 'expired', 'continue', or None if no trial.
        """
        # First expire any stale trials
        await self.checkpoint.expire_stale_trials()

        trial = await self.checkpoint.get_active_trial()
        if trial is None:
            return None

        trial_id = trial["id"]
        eval_count = trial["evaluation_count"] or 0
        min_evals = trial["min_evaluations"] or DEFAULT_MIN_EVALS

        if eval_count < min_evals:
            return "continue"

        avg = trial["avg_score"] or 0.0
        baseline = trial["baseline_avg_score"] or 0.0
        delta = avg - baseline

        if delta >= PROMOTE_THRESHOLD:
            await self.checkpoint.promote_trial(trial_id)
            logger.info(
                "Promoted trial %s: score %.1f vs baseline %.1f (+%.1f)",
                trial_id[:8], avg, baseline, delta,
            )
            return "promoted"

        if delta <= REVERT_THRESHOLD:
            await self._revert_with_log(trial, reason="worse_than_baseline")
            return "reverted"

        # Within thresholds — continue until time cap (expire_stale_trials handles expiry)
        return "continue"

    # --- Scoring ---

    async def score_past_actions(self, limit: int = 3) -> int:
        """Score unreviewed actions. Returns count scored."""
        trial = await self.checkpoint.get_active_trial()
        trial_id = trial["id"] if trial else None

        unscored = await self.evaluator.get_unscored_messages(limit=limit)
        scored = 0

        for msg in unscored:
            result = await self.evaluator.evaluate_action(
                msg["id"], msg["conversation_id"], trial_id=trial_id,
            )
            if result:
                scored += 1
                # Update trial running average if active
                if trial_id:
                    await self._update_trial_score(trial_id, result["overall_score"])

        return scored

    async def _update_trial_score(self, trial_id: str, new_score: float) -> None:
        """Update the running average score for a trial."""
        trial = await self.db.fetch_one(
            "SELECT evaluation_count, avg_score FROM trials WHERE id = ?", (trial_id,)
        )
        if not trial:
            return
        count = (trial["evaluation_count"] or 0) + 1
        old_avg = trial["avg_score"] or 0.0
        new_avg = old_avg + (new_score - old_avg) / count
        await self.db.execute(
            "UPDATE trials SET evaluation_count = ?, avg_score = ? WHERE id = ?",
            (count, new_avg, trial_id),
        )

    async def _get_baseline_score(self, lookback: int = 20) -> float:
        """Get average score from recent evaluations (before any trial)."""
        row = await self.db.fetch_one(
            "SELECT AVG(overall_score) as avg FROM evaluations "
            "WHERE trial_id IS NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (lookback,),
        )
        return row["avg"] if row and row["avg"] else 5.0  # Default to middle

    # --- Failed trial log ---

    async def _revert_with_log(self, trial: dict, reason: str) -> None:
        """Revert a trial and log the failure."""
        trial_id = trial["id"]

        # Generate lessons learned from the failure
        lessons = await self._generate_lessons(trial)

        await self.db.execute(
            "INSERT INTO failed_trials_log (id, trial_id, hypothesis, target, "
            "change_description, scores_summary, failure_reason, lessons) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                trial_id,
                trial["hypothesis"],
                trial["target"],
                trial.get("change_description"),
                json.dumps({"avg": trial.get("avg_score"), "baseline": trial.get("baseline_avg_score")}),
                reason,
                lessons,
            ),
        )
        await self.checkpoint.revert_trial(trial_id, reason=reason)
        logger.info("Reverted trial %s: %s", trial_id[:8], reason)

    async def _generate_lessons(self, trial: dict) -> str:
        """Ask the LLM what to learn from a failed trial."""
        try:
            response = await self.provider.complete(
                [{"role": "user", "content": (
                    f"A self-improvement trial failed.\n"
                    f"Hypothesis: {trial['hypothesis']}\n"
                    f"Change: {trial.get('change_description', 'N/A')}\n"
                    f"Score: {trial.get('avg_score', 'N/A')} vs baseline: {trial.get('baseline_avg_score', 'N/A')}\n\n"
                    "In 1-2 sentences, what should be learned from this failure? "
                    "What does it suggest about what to try differently?"
                )}],
                model=getattr(self.provider, "fallback_model", None),
                max_tokens=150,
                temperature=0.3,
            )
            return response.content.strip()
        except Exception:
            return "Lesson generation failed."

    async def get_failed_trials(self, limit: int = 20) -> list[dict]:
        """Get recent failed trials for the strategist."""
        rows = await self.db.fetch_all(
            "SELECT * FROM failed_trials_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    # --- Direction log ---

    async def log_direction(
        self,
        analysis: str,
        direction: str,
        opportunities: list[dict],
        hypotheses: list[dict],
        confidence: float,
        based_on_evaluations: int,
    ) -> str:
        """Append to the direction log."""
        entry_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO direction_log (id, analysis, direction, opportunities, "
            "hypotheses, confidence, based_on_evaluations) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id,
                analysis,
                direction,
                json.dumps(opportunities),
                json.dumps(hypotheses),
                confidence,
                based_on_evaluations,
            ),
        )
        return entry_id

    async def get_recent_directions(self, limit: int = 3) -> list[dict]:
        """Get recent direction log entries."""
        rows = await self.db.fetch_all(
            "SELECT * FROM direction_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
```

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_evolution.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add odigos/core/evolution.py tests/test_evolution.py
git commit -m "feat: add EvolutionEngine with trial lifecycle, failed-trial log, direction log"
```

---

### Task 6: Wire into Prompt Builder + Context Assembler

**Files:**
- Modify: `odigos/personality/prompt_builder.py` (lines 25-78)
- Modify: `odigos/core/context.py` (lines 51-94)

**Context:** Replace the static `build_system_prompt()` with dynamic section loading. The ContextAssembler needs to use CheckpointManager to get working sections (with trial overrides merged). Keep backward compatibility — if no prompt sections directory exists, fall back to the existing personality-based builder.

**Step 1: Write the failing test**

Create `tests/test_prompt_builder_dynamic.py`:

```python
"""Test that prompt builder uses dynamic sections when available."""
import os
import tempfile

import pytest

from odigos.personality.prompt_builder import build_system_prompt
from odigos.personality.loader import Personality
from odigos.personality.section_registry import SectionRegistry, PromptSection


def test_build_with_dynamic_sections():
    sections = [
        PromptSection(name="identity", content="You are Odigos.", priority=10),
        PromptSection(name="voice", content="Be concise.", priority=20),
    ]
    result = build_system_prompt(
        personality=Personality(),
        sections=sections,
        memory_context="User likes Python.",
        corrections_context="",
    )
    assert "You are Odigos." in result
    assert "Be concise." in result
    assert "User likes Python." in result


def test_build_without_sections_falls_back():
    """When no sections provided, uses personality-based builder."""
    result = build_system_prompt(
        personality=Personality(name="TestBot"),
        sections=None,
        memory_context="",
    )
    assert "TestBot" in result
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_prompt_builder_dynamic.py -v`
Expected: FAIL (build_system_prompt doesn't accept `sections` parameter)

**Step 3: Update prompt_builder.py**

Update `build_system_prompt` in `odigos/personality/prompt_builder.py` to accept optional dynamic sections. When sections are provided, use them instead of the static identity/voice builders:

```python
def build_system_prompt(
    personality: Personality,
    memory_context: str = "",
    tool_context: str = "",
    skill_catalog: str = "",
    corrections_context: str = "",
    sections: list | None = None,
) -> str:
    """Compose the system prompt from structured sections.

    If `sections` is provided (list of PromptSection), uses dynamic sections.
    Otherwise falls back to personality-based static sections.
    """
    parts = []

    if sections:
        # Dynamic mode: sections loaded from files + trial overrides
        for section in sorted(sections, key=lambda s: s.priority):
            if section.always_include:
                content = section.content.replace("{name}", personality.name)
                parts.append(content)
    else:
        # Legacy fallback: build from personality dataclass
        parts.append(_build_identity_section(personality))
        parts.append(_build_voice_section(personality))

    # Always-included context sections
    if memory_context:
        parts.append(memory_context)
    if tool_context:
        parts.append(tool_context)
    if skill_catalog:
        parts.append(skill_catalog)

    parts.append(SKILL_CREATION_INSTRUCTION)

    if corrections_context:
        parts.append(corrections_context)

    parts.append(CORRECTION_DETECTION_INSTRUCTION)
    parts.append(ENTITY_EXTRACTION_INSTRUCTION)

    return "\n\n".join(parts)
```

**Step 4: Update context.py**

Update `ContextAssembler.__init__` to accept an optional `checkpoint_manager` and use it in `build()`:

In `__init__` (around line 30), add parameter:
```python
checkpoint_manager: CheckpointManager | None = None,
```

In `build()` (around line 88), replace the `build_system_prompt` call:

```python
# Load dynamic prompt sections if checkpoint manager available
sections = None
if self.checkpoint_manager:
    sections = await self.checkpoint_manager.get_working_sections()

system_prompt = build_system_prompt(
    personality=personality,
    memory_context=memory_context,
    tool_context=tool_context,
    skill_catalog=skill_catalog,
    corrections_context=corrections_context,
    sections=sections,
)
```

**Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_prompt_builder_dynamic.py tests/test_section_registry.py -v`
Expected: All PASS

Run full test suite to check nothing broke:
Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x --timeout=30`
Expected: All existing tests still PASS

**Step 6: Commit**

```bash
git add odigos/personality/prompt_builder.py odigos/core/context.py tests/test_prompt_builder_dynamic.py
git commit -m "feat: wire dynamic prompt sections into prompt builder and context assembler"
```

---

### Task 7: Wire into Heartbeat — Phase 5

**Files:**
- Modify: `odigos/core/heartbeat.py` (lines 79-101)
- Modify: `odigos/main.py` (lines 432-444)

**Context:** Add Phase 5 (self-improvement cycle) to the heartbeat tick. This is the entry point that ties everything together. It runs after idle-think, scoring past actions and managing trials.

**Step 1: Write the failing test**

Create `tests/test_heartbeat_evolution.py`:

```python
"""Test that heartbeat Phase 5 runs the evolution cycle."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_tick_runs_evolution_when_idle():
    """Phase 5 should run when no other work was done."""
    from odigos.core.heartbeat import Heartbeat

    heartbeat = Heartbeat.__new__(Heartbeat)
    heartbeat.db = AsyncMock()
    heartbeat.agent = AsyncMock()
    heartbeat.channel_registry = MagicMock()
    heartbeat.goal_store = AsyncMock()
    heartbeat.provider = AsyncMock()
    heartbeat._interval = 30
    heartbeat._max_todos_per_tick = 3
    heartbeat._idle_think_interval = 900
    heartbeat._task = None
    heartbeat.tracer = None
    heartbeat.subagent_manager = None
    heartbeat._last_idle = 0
    heartbeat.paused = False
    heartbeat.evolution_engine = AsyncMock()
    heartbeat.evolution_engine.score_past_actions = AsyncMock(return_value=2)
    heartbeat.evolution_engine.check_active_trial = AsyncMock(return_value=None)

    # Mock the other phases to do no work
    heartbeat._fire_reminders = AsyncMock(return_value=False)
    heartbeat._work_todos = AsyncMock(return_value=False)
    heartbeat._deliver_subagent_results = AsyncMock(return_value=False)
    heartbeat._idle_think = AsyncMock()

    await heartbeat._tick()

    heartbeat.evolution_engine.score_past_actions.assert_called_once()
    heartbeat.evolution_engine.check_active_trial.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_heartbeat_evolution.py -v`
Expected: FAIL (Heartbeat doesn't have `evolution_engine` attribute)

**Step 3: Update heartbeat.py**

Add `evolution_engine` parameter to `Heartbeat.__init__` (after `subagent_manager` param, around line 40):

```python
evolution_engine: EvolutionEngine | None = None,
```

Store it: `self.evolution_engine = evolution_engine`

Add to `_tick()` method, after Phase 4 (around line 96):

```python
# Phase 5: Self-improvement cycle (runs when idle, like idle-think)
if not did_work and self.evolution_engine:
    await self._run_evolution()
```

Add the new method:

```python
async def _run_evolution(self) -> None:
    """Phase 5: Score past actions and manage active trials."""
    try:
        # 5a: Score unreviewed actions (adaptive count)
        scored = await self.evolution_engine.score_past_actions(limit=3)
        if scored:
            logger.debug("Evolution: scored %d past actions", scored)

        # 5b: Check active trial status
        result = await self.evolution_engine.check_active_trial()
        if result and result != "continue":
            logger.info("Evolution: trial %s", result)
    except Exception:
        logger.debug("Evolution cycle failed", exc_info=True)
```

**Step 4: Update main.py**

After the agent initialization (around line 406) and before heartbeat creation (line 432), add:

```python
# Initialize evolution engine
from odigos.core.checkpoint import CheckpointManager
from odigos.core.evaluator import Evaluator
from odigos.core.evolution import EvolutionEngine

checkpoint_manager = CheckpointManager(
    db=_db,
    sections_dir="data/prompt_sections",
    personality_path=settings.personality.path,
    skills_dir=settings.skills.path,
)
evaluator = Evaluator(db=_db, provider=_router)
evolution_engine = EvolutionEngine(
    db=_db,
    checkpoint_manager=checkpoint_manager,
    evaluator=evaluator,
    provider=_router,
)
logger.info("Evolution engine initialized")
```

Then pass `evolution_engine` to the Heartbeat constructor:

```python
_heartbeat = Heartbeat(
    ...existing params...,
    evolution_engine=evolution_engine,
)
```

And pass `checkpoint_manager` to the Agent's ContextAssembler:

In the Agent initialization (line 390), add checkpoint_manager. Since Agent passes it through to ContextAssembler, update the Agent constructor call to include it. The simplest path: pass checkpoint_manager directly to the context_assembler after Agent creation:

```python
agent.context_assembler.checkpoint_manager = checkpoint_manager
```

**Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_heartbeat_evolution.py -v`
Expected: PASS

Run full suite:
Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x --timeout=30`
Expected: All PASS

**Step 6: Commit**

```bash
git add odigos/core/heartbeat.py odigos/main.py tests/test_heartbeat_evolution.py
git commit -m "feat: wire evolution engine into heartbeat Phase 5 and main initialization"
```

---

### Task 8: Integration Test — Full Evolution Cycle

**Files:**
- Create: `tests/test_evolution_integration.py`

**Context:** End-to-end test that verifies the full cycle: create checkpoint → create trial → score actions → promote/revert. Uses an in-memory DB and mocked LLM.

**Step 1: Write the test**

```python
"""Integration test: full evolution cycle."""
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.checkpoint import CheckpointManager
from odigos.core.evaluator import Evaluator
from odigos.core.evolution import EvolutionEngine
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def sections_dir():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "identity.md"), "w").write(
            "---\npriority: 10\nalways_include: true\n---\nYou are Odigos."
        )
        open(os.path.join(d, "voice.md"), "w").write(
            "---\npriority: 20\nalways_include: true\n---\nBe concise."
        )
        yield d


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.fallback_model = "test-model"
    # C.1 rubric, C.2 score, lessons — cycle through these
    provider.complete = AsyncMock(side_effect=[
        AsyncMock(content=json.dumps({
            "task_type": "general",
            "criteria": [{"name": "quality", "weight": 1.0, "description": "good"}],
            "notes": "test",
        })),
        AsyncMock(content=json.dumps({
            "scores": [{"criterion": "quality", "score": 9, "observation": "excellent"}],
            "overall": 9.0,
            "improvement_signal": None,
        })),
    ])
    return provider


@pytest.mark.asyncio
async def test_full_cycle_promote(db, sections_dir, mock_provider):
    """Trial that performs well gets promoted and changes persist to disk."""
    # Setup
    checkpoint_mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    evaluator = Evaluator(db=db, provider=mock_provider)
    engine = EvolutionEngine(
        db=db, checkpoint_manager=checkpoint_mgr,
        evaluator=evaluator, provider=mock_provider,
    )

    # Seed some baseline evaluations
    for i in range(5):
        await db.execute(
            "INSERT INTO evaluations (id, overall_score, created_at) VALUES (?, ?, datetime('now'))",
            (str(uuid.uuid4()), 6.0),
        )

    # Create a conversation with messages to score
    conv_id = str(uuid.uuid4())
    await db.execute("INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "test"))
    user_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, conv_id, "user", "Help me write Python", datetime.now(timezone.utc).isoformat()),
    )
    asst_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (asst_id, conv_id, "assistant", "Here is the code...",
         (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()),
    )
    # Add positive follow-up
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), conv_id, "user", "Thanks, perfect!",
         (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()),
    )

    # Create trial
    trial_id = await engine.create_trial(
        hypothesis="Improved voice for coding",
        target="prompt_section",
        change_description="More technical voice",
        overrides={"voice": "Be precise and technical."},
    )

    # Verify override is active
    sections = await checkpoint_mgr.get_working_sections()
    voice = [s for s in sections if s.name == "voice"][0]
    assert voice.content == "Be precise and technical."

    # Score the action
    scored = await engine.score_past_actions(limit=1)
    assert scored == 1

    # Simulate enough good evaluations to trigger promotion
    await db.execute(
        "UPDATE trials SET evaluation_count = 6, avg_score = 8.5 WHERE id = ?",
        (trial_id,),
    )

    # Check trial — should promote
    result = await engine.check_active_trial()
    assert result == "promoted"

    # Verify written to disk
    voice_content = open(os.path.join(sections_dir, "voice.md")).read()
    assert "Be precise and technical." in voice_content

    # Verify no more overrides
    overrides = await db.fetch_all("SELECT * FROM trial_overrides WHERE trial_id = ?", (trial_id,))
    assert len(overrides) == 0


@pytest.mark.asyncio
async def test_full_cycle_revert(db, sections_dir, mock_provider):
    """Trial that performs poorly gets reverted, disk unchanged."""
    checkpoint_mgr = CheckpointManager(db=db, sections_dir=sections_dir, personality_path="")
    evaluator = Evaluator(db=db, provider=mock_provider)
    engine = EvolutionEngine(
        db=db, checkpoint_manager=checkpoint_mgr,
        evaluator=evaluator, provider=mock_provider,
    )

    # Add lessons generation mock
    mock_provider.complete = AsyncMock(return_value=AsyncMock(
        content="The change was too aggressive for this context."
    ))

    original_voice = open(os.path.join(sections_dir, "voice.md")).read()

    trial_id = await engine.create_trial(
        hypothesis="Be extremely terse",
        target="prompt_section",
        change_description="Minimal responses",
        overrides={"voice": "One word answers only."},
    )

    # Simulate bad evaluations
    await db.execute(
        "UPDATE trials SET evaluation_count = 6, avg_score = 3.0, "
        "baseline_avg_score = 6.0 WHERE id = ?",
        (trial_id,),
    )

    result = await engine.check_active_trial()
    assert result == "reverted"

    # Disk unchanged
    current_voice = open(os.path.join(sections_dir, "voice.md")).read()
    assert current_voice == original_voice

    # Failed trial logged
    failed = await engine.get_failed_trials()
    assert len(failed) == 1
    assert failed[0]["hypothesis"] == "Be extremely terse"
```

**Step 2: Run the test**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_evolution_integration.py -v`
Expected: All 2 tests PASS

**Step 3: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x --timeout=30`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/test_evolution_integration.py
git commit -m "test: add integration tests for full evolution promote/revert cycle"
```

---

### Task 9: Final Verification + Cleanup

**Step 1: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS including new evolution tests

**Step 2: Verify no import errors in new modules**

Run: `cd /Users/jacob/Projects/odigos && python -c "from odigos.core.evaluator import Evaluator; from odigos.core.evolution import EvolutionEngine; from odigos.core.checkpoint import CheckpointManager; from odigos.personality.section_registry import SectionRegistry; print('All imports OK')"`
Expected: `All imports OK`

**Step 3: Verify migration applies cleanly**

Run: `cd /Users/jacob/Projects/odigos && python -c "import asyncio; from odigos.db import Database; db = Database('data/test_final.db'); asyncio.run(db.initialize()); print('All migrations OK'); import os; os.remove('data/test_final.db')"`
Expected: `All migrations OK`

**Step 4: Verify prompt section files exist**

Run: `ls -la data/prompt_sections/`
Expected: `identity.md`, `voice.md`, `meta.md` present

**Step 5: Commit any remaining changes**

```bash
git add -A
git commit -m "chore: self-improvement engine Phase 1 complete"
```
