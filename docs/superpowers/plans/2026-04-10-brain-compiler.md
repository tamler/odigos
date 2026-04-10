# Brain Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Periodically compile the agent's accumulated memories and entities into a structured, interlinked knowledge wiki with concept articles, cross-references, and staleness management — dispatched as a background sub-agent.

**Architecture:** Heartbeat Phase 3f checks if enough new content has accumulated since the last compilation. If yes, it builds a compilation context (current brain state + new memories + entity list + slug list) and dispatches a `brain-compiler` sub-agent. When the sub-agent completes, the next heartbeat cycle applies the JSON manifest of file operations (create/update/archive) to `data/brain/`. brain_maintenance gains a precedence check so it doesn't overwrite compiler-enriched pages.

**Tech Stack:** Python 3.12, existing SubagentManager.dispatch(), existing kv table for state, existing BrainWriter for index regeneration.

**Spec:** `docs/superpowers/specs/2026-04-10-brain-compiler-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `odigos/core/heartbeat/brain_compiler.py` | Trigger: should_compile, dispatch_compilation, check_compilation, build_context |
| `odigos/core/brain_apply.py` | Apply manifest: create/update/archive files, regenerate index, update kv |
| `data/subagents/brain-compiler.md` | 5-pass compiler persona |
| `tests/test_brain_compiler.py` | Trigger logic + context building tests |
| `tests/test_brain_apply.py` | Manifest application tests |

### Modified Files

| File | Change |
|------|--------|
| `odigos/core/heartbeat/orchestrator.py` | Add Phase 3f call |
| `odigos/core/heartbeat/brain_maintenance.py` | Skip overwrite when compiled_at > entity.updated_at |

---

### Task 1: Brain-Compiler Persona

**Files:**
- Create: `data/subagents/brain-compiler.md`

- [ ] **Step 1: Create the persona file**

Create `data/subagents/brain-compiler.md`:

```markdown
---
name: brain-compiler
description: Compiles memories and entities into a structured, interlinked knowledge wiki
model: reasoning
tools: [read_file, write_file]
max_runtime_seconds: 900
workspace_roots:
  - data/brain/
---

# Brain Compiler

You compile the agent's accumulated knowledge into an interlinked wiki.
You receive the current brain state and new memories/entities since the
last compilation. Produce a JSON manifest of file operations.

## Pass 1: Scan & Diff

Read the current brain articles and the new memories. Identify:
- New concepts that span multiple entities or memories (not yet in the brain)
- Existing articles that should be enriched with new facts
- Stale articles whose source facts have been superseded (check memory status and superseded_by fields)

## Pass 2: Concept Extraction

From the new memories, identify cross-cutting themes:
- Patterns that span multiple entities or conversations
- Recurring topics the user cares about
- Ideas or goals that have evolved over time

Each concept gets: name, description, related entities, source memories.
Only create a concept article if it has 3+ supporting facts from different sources.

## Pass 3: Article Generation/Update

For each new concept: generate a wiki article.
For each existing article needing enrichment: produce updated content.

Article structure:

```
---
type: concept
title: {name}
related: [{list of related article slugs}]
sources: [{memory IDs or entity IDs}]
compiled_at: {ISO timestamp}
---

## {Title}

### Overview
1-3 sentence summary.

### Key Facts
- Fact 1 [source: memory:{id}]
- Fact 2 [source: entity:{id}]

### Related Concepts
- [Concept A](../concepts/concept-a.md) — brief note on relationship
- [Entity B](../entities/entity-b.md)

### See Also
- Links to other relevant articles

### Feedback
[Discuss or correct this article](/?c=new&about=concept:{slug})
```

## Pass 4: Cross-Linking

For every article (new or updated):
- Add inline [links](../path.md) where concepts or entities are mentioned
- Ensure bidirectional linking: if A mentions B, B should mention A
- Add a "See Also" section if not already present
- IMPORTANT: If Article A needs a link to Article B, but B isn't being
  updated in this compilation, emit a "minimal update" operation for B
  that ONLY adds the backlink to its "See Also" section.

SLUG REUSE: You receive a list of all existing slugs. ALWAYS check
this list before creating a new concept. If a similar slug exists
(e.g., "testing-patterns" exists, don't create "test-patterns"),
update the existing article instead of creating a duplicate.

## Pass 5: Staleness Check

For existing articles not touched by passes 1-4:
- Check source memory IDs cited in the article. A memory is stale if
  its status is 'superseded'. An article is stale if ALL of its source
  memories are stale.
- Don't archive if the article has 5+ cross-links (high-connectivity = still valuable)
- Don't archive conversation summaries (they're historical records)

## Output

Return ONLY valid JSON. No markdown fences. No commentary.

{"operations": [{"op": "create", "path": "data/brain/concepts/slug.md", "content": "full markdown"}, {"op": "update", "path": "data/brain/entities/slug.md", "content": "full markdown"}, {"op": "archive", "path": "data/brain/concepts/old.md", "reason": "source facts superseded"}], "new_concepts": ["slug1", "slug2"], "updated_articles": ["slug3"], "archived": ["slug4"], "cross_links_added": 12, "summary": "One-line human-readable summary."}

If nothing needs to be compiled, return:
{"operations": [], "new_concepts": [], "updated_articles": [], "archived": [], "cross_links_added": 0, "summary": "No compilation needed."}
```

- [ ] **Step 2: Verify persona loads**

```bash
cd /Users/jacob/Projects/odigos && python3 -c "
from odigos.core.subagent import load_persona
p = load_persona('brain-compiler')
assert p is not None
assert p.model == 'reasoning'
assert 'read_file' in p.tools
print(f'brain-compiler: model={p.model}, tools={p.tools}, timeout={p.max_runtime_seconds}')
print('ok')
"
```

Expected: prints persona info + "ok".

- [ ] **Step 3: Commit**

```bash
git add data/subagents/brain-compiler.md
git commit -m "feat: add brain-compiler persona for 5-pass wiki compilation"
```

---

### Task 2: Manifest Application Module

**Files:**
- Create: `odigos/core/brain_apply.py`
- Create: `tests/test_brain_apply.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_brain_apply.py`:

```python
"""Tests for brain compilation manifest application."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


class TestApplyManifest:
    async def test_create_writes_file(self, tmp_path):
        from odigos.core.brain_apply import apply_compilation

        brain_dir = tmp_path / "brain"
        brain_dir.mkdir()

        manifest = json.dumps({
            "operations": [
                {
                    "op": "create",
                    "path": "concepts/deployment.md",
                    "content": "---\ntype: concept\ntitle: Deployment\n---\n\n# Deployment\n\nOverview here.",
                },
            ],
            "new_concepts": ["deployment"],
            "updated_articles": [],
            "archived": [],
            "cross_links_added": 0,
            "summary": "Created deployment concept.",
        })

        stats = await apply_compilation(manifest, brain_dir=str(brain_dir))
        assert stats["created"] == 1
        assert stats["errors"] == []

        created = brain_dir / "concepts" / "deployment.md"
        assert created.exists()
        assert "Deployment" in created.read_text()

    async def test_update_overwrites_file(self, tmp_path):
        from odigos.core.brain_apply import apply_compilation

        brain_dir = tmp_path / "brain"
        entities_dir = brain_dir / "entities"
        entities_dir.mkdir(parents=True)
        (entities_dir / "rachel.md").write_text("# Rachel\n\nOld content.")

        manifest = json.dumps({
            "operations": [
                {
                    "op": "update",
                    "path": "entities/rachel.md",
                    "content": "---\ntype: entity\ncompiled_at: 2026-04-10T12:00:00Z\n---\n\n# Rachel\n\nEnriched content.",
                },
            ],
            "new_concepts": [],
            "updated_articles": ["rachel"],
            "archived": [],
            "cross_links_added": 0,
            "summary": "Updated rachel.",
        })

        stats = await apply_compilation(manifest, brain_dir=str(brain_dir))
        assert stats["updated"] == 1

        content = (entities_dir / "rachel.md").read_text()
        assert "Enriched content" in content
        assert "Old content" not in content

    async def test_archive_moves_file(self, tmp_path):
        from odigos.core.brain_apply import apply_compilation

        brain_dir = tmp_path / "brain"
        concepts_dir = brain_dir / "concepts"
        concepts_dir.mkdir(parents=True)
        (concepts_dir / "old-topic.md").write_text("# Old Topic\n\nStale.")

        manifest = json.dumps({
            "operations": [
                {
                    "op": "archive",
                    "path": "concepts/old-topic.md",
                    "reason": "All source facts superseded",
                },
            ],
            "new_concepts": [],
            "updated_articles": [],
            "archived": ["old-topic"],
            "cross_links_added": 0,
            "summary": "Archived old-topic.",
        })

        stats = await apply_compilation(manifest, brain_dir=str(brain_dir))
        assert stats["archived"] == 1

        # Original should be gone
        assert not (concepts_dir / "old-topic.md").exists()
        # Archive should exist
        archived = brain_dir / "archive" / "concepts" / "old-topic.md"
        assert archived.exists()
        assert "archived_at" in archived.read_text().lower() or "archive_reason" in archived.read_text().lower()

    async def test_rejects_path_outside_brain(self, tmp_path):
        from odigos.core.brain_apply import apply_compilation

        brain_dir = tmp_path / "brain"
        brain_dir.mkdir()

        manifest = json.dumps({
            "operations": [
                {"op": "create", "path": "../../../etc/passwd", "content": "evil"},
            ],
            "new_concepts": [],
            "updated_articles": [],
            "archived": [],
            "cross_links_added": 0,
            "summary": "Evil.",
        })

        stats = await apply_compilation(manifest, brain_dir=str(brain_dir))
        assert stats["created"] == 0
        assert len(stats["errors"]) == 1
        assert "path" in stats["errors"][0].lower()

    async def test_operations_applied_in_dependency_order(self, tmp_path):
        """Creates come before updates, updates before archives."""
        from odigos.core.brain_apply import apply_compilation

        brain_dir = tmp_path / "brain"
        concepts_dir = brain_dir / "concepts"
        concepts_dir.mkdir(parents=True)
        (concepts_dir / "existing.md").write_text("# Existing\n\nOld.")

        manifest = json.dumps({
            "operations": [
                # Intentionally out of order
                {"op": "archive", "path": "concepts/existing.md", "reason": "stale"},
                {"op": "create", "path": "concepts/new-topic.md", "content": "# New\n\nFresh."},
                {"op": "update", "path": "concepts/new-topic.md", "content": "# New\n\nFresh + link to existing."},
            ],
            "new_concepts": ["new-topic"],
            "updated_articles": ["new-topic"],
            "archived": ["existing"],
            "cross_links_added": 1,
            "summary": "Test ordering.",
        })

        stats = await apply_compilation(manifest, brain_dir=str(brain_dir))
        # All three should succeed because creates come first
        assert stats["created"] == 1
        assert stats["updated"] == 1
        assert stats["archived"] == 1

        # new-topic should have the update content (not the create content)
        content = (concepts_dir / "new-topic.md").read_text()
        assert "link to existing" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_brain_apply.py -x -q`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement brain_apply.py**

Create `odigos/core/brain_apply.py`:

```python
"""Apply a brain compilation manifest to disk.

Reads a JSON manifest from the brain-compiler sub-agent and applies
create/update/archive operations to data/brain/. Operations are applied
in dependency order: creates first, then updates, then archives.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


async def apply_compilation(
    manifest_json: str,
    brain_dir: str = "data/brain",
) -> dict:
    """Apply a brain compilation manifest to disk.

    Args:
        manifest_json: JSON string with operations, summary, etc.
        brain_dir: Root directory for brain files.

    Returns:
        {created: int, updated: int, archived: int, errors: list[str], summary: str}
    """
    try:
        manifest = json.loads(manifest_json)
    except (json.JSONDecodeError, TypeError) as exc:
        return {"created": 0, "updated": 0, "archived": 0,
                "errors": [f"Invalid manifest JSON: {exc}"], "summary": ""}

    operations = manifest.get("operations", [])
    summary = manifest.get("summary", "")

    if not operations:
        return {"created": 0, "updated": 0, "archived": 0,
                "errors": [], "summary": summary}

    brain = Path(brain_dir)

    # Sort operations by dependency order: create → update → archive
    creates = [op for op in operations if op.get("op") == "create"]
    updates = [op for op in operations if op.get("op") == "update"]
    archives = [op for op in operations if op.get("op") == "archive"]
    ordered = creates + updates + archives

    stats = {"created": 0, "updated": 0, "archived": 0, "errors": [], "summary": summary}

    for op in ordered:
        op_type = op.get("op")
        rel_path = op.get("path", "")

        # Path validation
        if not rel_path or ".." in rel_path:
            stats["errors"].append(f"Rejected invalid path: {rel_path}")
            continue
        full_path = (brain / rel_path).resolve()
        if not str(full_path).startswith(str(brain.resolve())):
            stats["errors"].append(f"Rejected path traversal: {rel_path}")
            continue

        try:
            if op_type == "create":
                content = op.get("content", "")
                if not content:
                    stats["errors"].append(f"Empty content for create: {rel_path}")
                    continue
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
                stats["created"] += 1

            elif op_type == "update":
                content = op.get("content", "")
                if not content:
                    stats["errors"].append(f"Empty content for update: {rel_path}")
                    continue
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
                stats["updated"] += 1

            elif op_type == "archive":
                if not full_path.exists():
                    stats["errors"].append(f"Archive target not found: {rel_path}")
                    continue
                archive_path = brain / "archive" / rel_path
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                # Read original, prepend archive metadata
                original = full_path.read_text(encoding="utf-8")
                reason = op.get("reason", "unknown")
                now = datetime.now(timezone.utc).isoformat()
                if original.startswith("---"):
                    # Insert archive fields into existing frontmatter
                    parts = original.split("---", 2)
                    if len(parts) >= 3:
                        original = (
                            f"---\narchived_at: {now}\n"
                            f"archive_reason: {reason}\n"
                            f"{parts[1]}---{parts[2]}"
                        )
                else:
                    original = (
                        f"---\narchived_at: {now}\n"
                        f"archive_reason: {reason}\n---\n\n{original}"
                    )
                archive_path.write_text(original, encoding="utf-8")
                full_path.unlink()
                stats["archived"] += 1

            else:
                stats["errors"].append(f"Unknown operation type: {op_type}")

        except Exception as exc:
            stats["errors"].append(f"{op_type} failed for {rel_path}: {exc}")
            logger.warning("Brain apply %s failed for %s: %s", op_type, rel_path, exc)

    # Regenerate index.md
    try:
        _regenerate_index(brain)
    except Exception as exc:
        stats["errors"].append(f"Index regeneration failed: {exc}")

    # Append to log.md
    try:
        _append_log(brain, summary, stats)
    except Exception as exc:
        logger.debug("Log append failed: %s", exc)

    return stats


def _regenerate_index(brain: Path) -> None:
    """Rebuild data/brain/index.md from the directory listing."""
    sections: list[str] = ["# Brain Index\n"]

    for subdir_name, label in [
        ("entities", "Entities"),
        ("concepts", "Concepts"),
        ("topics", "Topics"),
        ("conversations", "Conversations"),
        ("synthesis", "Synthesis"),
    ]:
        subdir = brain / subdir_name
        if not subdir.exists():
            continue
        files = sorted(subdir.glob("*.md"))
        if not files:
            continue
        sections.append(f"\n## {label} ({len(files)})\n")
        for f in files:
            name = f.stem.replace("-", " ").title()
            sections.append(f"- [{name}]({subdir_name}/{f.name})")

    (brain / "index.md").write_text("\n".join(sections) + "\n", encoding="utf-8")


def _append_log(brain: Path, summary: str, stats: dict) -> None:
    """Append a compilation entry to data/brain/log.md."""
    now = datetime.now(timezone.utc).isoformat()
    entry = (
        f"\n## {now} — Brain compilation\n"
        f"{summary}\n"
        f"Created: {stats['created']}, Updated: {stats['updated']}, "
        f"Archived: {stats['archived']}"
    )
    if stats["errors"]:
        entry += f", Errors: {len(stats['errors'])}"
    entry += "\n\n---\n"

    log_path = brain / "log.md"
    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        log_path.write_text(existing + entry, encoding="utf-8")
    else:
        log_path.write_text(f"# Brain Compilation Log\n{entry}", encoding="utf-8")
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_brain_apply.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add odigos/core/brain_apply.py tests/test_brain_apply.py
git commit -m "feat: add brain_apply module for manifest-based wiki file operations"
```

---

### Task 3: Compilation Trigger + Heartbeat Integration

**Files:**
- Create: `odigos/core/heartbeat/brain_compiler.py`
- Create: `tests/test_brain_compiler.py`
- Modify: `odigos/core/heartbeat/orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_brain_compiler.py`:

```python
"""Tests for brain compilation trigger logic."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
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


async def _set_kv(db, key, value):
    await db.execute(
        "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
        (key, value),
    )


async def _seed_memories(db, count: int, created_after: str | None = None) -> None:
    for i in range(count):
        mem_id = str(uuid.uuid4())
        created = created_after or datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO memories (id, content, memory_type, source_type, source_id, "
            "confidence, created_at, updated_at) "
            "VALUES (?, ?, 'fact', 'conversation', 'c1', 0.8, ?, ?)",
            (mem_id, f"Fact {i}", created, created),
        )


async def _seed_entity(db) -> str:
    eid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO entities (id, type, name) VALUES (?, 'person', 'TestEntity')",
        (eid,),
    )
    return eid


class TestShouldCompile:
    async def test_returns_true_on_first_compile_with_entities(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        await _seed_entity(db)
        assert await should_compile(db) is True

    async def test_returns_false_when_no_entities(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        assert await should_compile(db) is False

    async def test_returns_false_when_pending_task_exists(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        await _seed_entity(db)
        await _set_kv(db, "brain_compile_task", "some-task-id")
        assert await should_compile(db) is False

    async def test_returns_true_when_enough_new_memories(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await _set_kv(db, "brain_last_compiled", past)
        await _seed_memories(db, 12)
        assert await should_compile(db) is True

    async def test_returns_false_when_too_few_memories(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        past = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        await _set_kv(db, "brain_last_compiled", past)
        await _seed_memories(db, 3)
        assert await should_compile(db) is False

    async def test_returns_true_on_24h_fallback(self, db):
        from odigos.core.heartbeat.brain_compiler import should_compile

        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        await _set_kv(db, "brain_last_compiled", old)
        await _seed_memories(db, 1)
        assert await should_compile(db) is True


class TestBuildContext:
    async def test_context_includes_memories_and_slugs(self, db, tmp_path):
        from odigos.core.heartbeat.brain_compiler import build_compilation_context

        await _seed_memories(db, 5)
        await _seed_entity(db)

        # Create a fake brain dir with one entity file
        brain_dir = tmp_path / "brain" / "entities"
        brain_dir.mkdir(parents=True)
        (brain_dir / "test-entity.md").write_text("# Test Entity\n\nSome facts.")

        ctx = await build_compilation_context(db, brain_dir=str(tmp_path / "brain"))
        assert "existing_slugs" in ctx
        assert "test-entity" in ctx["existing_slugs"]
        assert len(ctx["new_memories"]) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_brain_compiler.py -x -q`
Expected: FAIL.

- [ ] **Step 3: Implement brain_compiler.py**

Create `odigos/core/heartbeat/brain_compiler.py`:

```python
"""Heartbeat Phase 3f: brain compilation trigger and lifecycle.

Checks if enough new content has accumulated since the last compilation.
If yes, dispatches a brain-compiler sub-agent. On the next cycle, checks
if the sub-agent completed and applies the manifest to disk.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.heartbeat.orchestrator import Heartbeat

logger = logging.getLogger(__name__)

MEMORY_THRESHOLD = 10
ENTITY_THRESHOLD = 5
FALLBACK_HOURS = 24
MAX_MEMORIES_IN_CONTEXT = 50
MAX_CONTEXT_CHARS = 6000
BRAIN_DIR = "data/brain"


async def should_compile(db) -> bool:
    """Check if brain compilation should be triggered."""
    # Check for pending task
    pending = await db.fetch_one(
        "SELECT value FROM kv WHERE key = 'brain_compile_task'"
    )
    if pending and pending["value"]:
        return False

    last_compiled = await db.fetch_one(
        "SELECT value FROM kv WHERE key = 'brain_last_compiled'"
    )
    last_ts = last_compiled["value"] if last_compiled else None

    # First compile: need at least 1 entity
    if not last_ts:
        entity_count = await db.fetch_one(
            "SELECT COUNT(*) as c FROM entities WHERE status = 'active'"
        )
        return (entity_count["c"] if entity_count else 0) > 0

    # Count new memories since last compile
    mem_count = await db.fetch_one(
        "SELECT COUNT(*) as c FROM memories WHERE created_at > ? AND status = 'active'",
        (last_ts,),
    )
    new_memories = mem_count["c"] if mem_count else 0

    # Count new/updated entities since last compile
    ent_count = await db.fetch_one(
        "SELECT COUNT(*) as c FROM entities WHERE updated_at > ?",
        (last_ts,),
    )
    new_entities = ent_count["c"] if ent_count else 0

    if new_memories >= MEMORY_THRESHOLD or new_entities >= ENTITY_THRESHOLD:
        return True

    # 24h fallback
    try:
        compiled_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        if compiled_dt.tzinfo is None:
            compiled_dt = compiled_dt.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - compiled_dt).total_seconds() / 3600
        if age_hours >= FALLBACK_HOURS and new_memories >= 1:
            return True
    except (ValueError, AttributeError):
        pass

    return False


async def build_compilation_context(db, brain_dir: str = BRAIN_DIR) -> dict:
    """Build the input context for the brain-compiler sub-agent.

    Returns a dict with keys: current_articles, new_memories, new_entities,
    existing_slugs, current_index.
    """
    brain = Path(brain_dir)
    last_compiled = await db.fetch_one(
        "SELECT value FROM kv WHERE key = 'brain_last_compiled'"
    )
    last_ts = last_compiled["value"] if last_compiled else "1970-01-01T00:00:00Z"

    # Current brain article summaries
    current_articles: list[str] = []
    for subdir in ["entities", "concepts"]:
        path = brain / subdir
        if not path.exists():
            continue
        for f in sorted(path.glob("*.md")):
            first_line = f.read_text(encoding="utf-8").split("\n")[0][:100]
            current_articles.append(f"{subdir}/{f.name}: {first_line}")

    # Existing slugs (all filenames without extension)
    existing_slugs: list[str] = []
    for subdir in ["entities", "concepts", "archive/entities", "archive/concepts"]:
        path = brain / subdir
        if not path.exists():
            continue
        for f in path.glob("*.md"):
            existing_slugs.append(f.stem)

    # New memories — prioritize high-confidence, fact/preference types first
    rows = await db.fetch_all(
        "SELECT id, content, memory_type, keywords_json, context_description, "
        "confidence, status, superseded_by "
        "FROM memories WHERE created_at > ? AND status = 'active' "
        "ORDER BY "
        "  CASE WHEN memory_type IN ('fact', 'preference') THEN 0 ELSE 1 END, "
        "  confidence DESC "
        "LIMIT ?",
        (last_ts, MAX_MEMORIES_IN_CONTEXT),
    )
    new_memories: list[dict] = []
    total_chars = 0
    for row in rows:
        content = (row["context_description"] or row["content"] or "")
        # Truncate general/summary to 100 chars
        if row["memory_type"] in ("general", "summary"):
            content = content[:100]
        else:
            content = content[:200]
        if total_chars + len(content) > MAX_CONTEXT_CHARS:
            break
        new_memories.append({
            "id": row["id"],
            "type": row["memory_type"],
            "content": content,
            "keywords": row["keywords_json"] or "[]",
            "confidence": row["confidence"],
            "status": row["status"],
            "superseded_by": row["superseded_by"],
        })
        total_chars += len(content)

    # New/updated entities
    ent_rows = await db.fetch_all(
        "SELECT id, name, type, summary FROM entities WHERE updated_at > ? LIMIT 20",
        (last_ts,),
    )
    new_entities = [
        {"id": r["id"], "name": r["name"], "type": r["type"],
         "summary": (r["summary"] or "")[:200]}
        for r in ent_rows
    ]

    # Current index
    index_path = brain / "index.md"
    current_index = ""
    if index_path.exists():
        current_index = index_path.read_text(encoding="utf-8")[:2000]

    return {
        "current_articles": current_articles,
        "new_memories": new_memories,
        "new_entities": new_entities,
        "existing_slugs": existing_slugs,
        "current_index": current_index,
    }


async def dispatch_compilation(hb: "Heartbeat") -> str | None:
    """Dispatch the brain-compiler sub-agent.

    Returns the task_id if dispatched, None otherwise.
    """
    if not getattr(hb, "subagent_manager", None):
        return None

    context = await build_compilation_context(hb.db, brain_dir=BRAIN_DIR)

    # Format as the sub-agent's input
    input_text = json.dumps(context, indent=2, default=str)

    task_description = (
        f"Compile the brain wiki. "
        f"{len(context['new_memories'])} new memories, "
        f"{len(context['new_entities'])} new/updated entities, "
        f"{len(context['existing_slugs'])} existing slugs."
    )

    try:
        result = await hb.subagent_manager.dispatch(
            task=task_description,
            persona="brain-compiler",
            input_artifact=input_text,
            concurrency_key="heavy",
        )
        # Store task_id for polling
        await hb.db.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES ('brain_compile_task', ?)",
            (result.task_id,),
        )
        logger.info("Brain compilation dispatched: task=%s", result.task_id[:8])
        return result.task_id
    except Exception:
        logger.warning("Brain compilation dispatch failed", exc_info=True)
        return None


async def check_compilation(hb: "Heartbeat") -> bool:
    """Check if a pending brain compilation has completed and apply the result.

    Returns True if a compilation was applied.
    """
    row = await hb.db.fetch_one(
        "SELECT value FROM kv WHERE key = 'brain_compile_task'"
    )
    if not row or not row["value"]:
        return False

    task_id = row["value"]
    task_row = await hb.db.fetch_one(
        "SELECT status, result_json, error FROM tasks WHERE id = ?",
        (task_id,),
    )

    if not task_row:
        # Task disappeared — clear the kv
        await hb.db.execute("DELETE FROM kv WHERE key = 'brain_compile_task'")
        return False

    if task_row["status"] == "done":
        from odigos.core.brain_apply import apply_compilation

        result_json = task_row["result_json"] or "{}"
        # Extract the result text from the sub-agent wrapper
        try:
            result_obj = json.loads(result_json)
            manifest = result_obj.get("result", result_json)
        except (json.JSONDecodeError, TypeError):
            manifest = result_json

        stats = await apply_compilation(manifest, brain_dir=BRAIN_DIR)

        # Update last_compiled timestamp
        now = datetime.now(timezone.utc).isoformat()
        await hb.db.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES ('brain_last_compiled', ?)",
            (now,),
        )

        # Clear the pending task
        await hb.db.execute("DELETE FROM kv WHERE key = 'brain_compile_task'")

        # Notification
        summary = stats.get("summary", "Brain compiled.")
        try:
            if hasattr(hb, "notifier") and hb.notifier:
                await hb.notifier.create(
                    type="status",
                    title="Brain compiled",
                    body=f"{summary} (created: {stats['created']}, updated: {stats['updated']}, archived: {stats['archived']})",
                )
        except Exception:
            logger.debug("Notification failed", exc_info=True)

        logger.info(
            "Brain compilation applied: created=%d, updated=%d, archived=%d, errors=%d",
            stats["created"], stats["updated"], stats["archived"], len(stats.get("errors", [])),
        )
        return True

    elif task_row["status"] == "failed":
        await hb.db.execute("DELETE FROM kv WHERE key = 'brain_compile_task'")
        logger.warning("Brain compilation failed: %s", task_row.get("error", "unknown"))
        return False

    # Still running — do nothing
    return False
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_brain_compiler.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Wire into orchestrator**

In `odigos/core/heartbeat/orchestrator.py`, find Phase 3e (brain_maintenance). After it, add Phase 3f:

```python
# Phase 3f: Brain compilation (sub-agent dispatch)
try:
    from odigos.core.heartbeat import brain_compiler
    applied = await brain_compiler.check_compilation(self)
    if not applied and await brain_compiler.should_compile(self.db):
        await brain_compiler.dispatch_compilation(self)
except Exception:
    logger.debug("Brain compiler phase failed", exc_info=True)
```

- [ ] **Step 6: Run full test suite for regressions**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_brain_compiler.py tests/test_brain_apply.py tests/test_subagent.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add odigos/core/heartbeat/brain_compiler.py odigos/core/heartbeat/orchestrator.py tests/test_brain_compiler.py
git commit -m "feat: brain compilation trigger with should_compile, dispatch, check lifecycle"
```

---

### Task 4: brain_maintenance Precedence Check

**Files:**
- Modify: `odigos/core/heartbeat/brain_maintenance.py`

- [ ] **Step 1: Read the current entity page writing logic**

```bash
grep -n "write_entity_page\|compiled_at" odigos/core/heartbeat/brain_maintenance.py
grep -n "write_entity_page" odigos/memory/brain_writer.py
```

- [ ] **Step 2: Add compiled_at check**

Find the block in `brain_maintenance.py` where `writer.write_entity_page()` is called. Before the call, add a check:

```python
# Check if the compiler has enriched this entity page — don't overwrite
entity_slug = entity["name"].lower().replace(" ", "-")
entity_page = Path(BRAIN_DIR) / "entities" / f"{entity_slug}.md"
if entity_page.exists():
    page_content = entity_page.read_text(encoding="utf-8")
    if "compiled_at:" in page_content:
        # Parse the compiled_at timestamp
        import re
        match = re.search(r"compiled_at:\s*(\S+)", page_content)
        if match:
            try:
                compiled_at = datetime.fromisoformat(
                    match.group(1).replace("Z", "+00:00")
                )
                entity_updated = datetime.fromisoformat(
                    entity.get("updated_at", "1970-01-01").replace("Z", "+00:00")
                )
                if compiled_at.tzinfo is None:
                    compiled_at = compiled_at.replace(tzinfo=timezone.utc)
                if entity_updated.tzinfo is None:
                    entity_updated = entity_updated.replace(tzinfo=timezone.utc)
                if compiled_at > entity_updated:
                    logger.debug(
                        "Skipping entity page %s: compiler version is newer",
                        entity_slug,
                    )
                    continue  # Skip this entity — compiler version takes precedence
            except (ValueError, AttributeError):
                pass  # Can't parse, proceed with normal write
```

Add the necessary imports at the top of the file if not already present:

```python
from datetime import datetime, timezone
from pathlib import Path
import re
```

And define `BRAIN_DIR`:

```python
BRAIN_DIR = "data/brain"
```

- [ ] **Step 3: Run existing brain_maintenance tests for regressions**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q -k "brain"`
Expected: no new failures.

- [ ] **Step 4: Commit**

```bash
git add odigos/core/heartbeat/brain_maintenance.py
git commit -m "fix(brain): skip entity page overwrite when compiler version is newer"
```

---

### Task 5: Final Smoke Test

- [ ] **Step 1: Run all brain-related tests**

```bash
cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_brain_compiler.py tests/test_brain_apply.py -v
```

Expected: all pass.

- [ ] **Step 2: Import smoke test**

```bash
cd /Users/jacob/Projects/odigos && python3 -c "
from odigos.core.subagent import load_persona
from odigos.core.heartbeat.brain_compiler import should_compile, build_compilation_context, check_compilation
from odigos.core.brain_apply import apply_compilation

p = load_persona('brain-compiler')
assert p is not None
assert p.model == 'reasoning'
print(f'brain-compiler persona: {p.name}, model={p.model}')
print('all imports ok')
"
```

Expected: prints persona info + "all imports ok".

- [ ] **Step 3: Broader regression check**

```bash
cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_subagent.py tests/test_subagent_worker.py tests/test_subagent_tools.py tests/test_marp_tool.py tests/test_skill_framing.py -q
```

Expected: all pass.

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A && git commit -m "fix: polish and cleanup for brain compiler"
```
