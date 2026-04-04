# XSkill: Experience Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the agent learn from tool outcomes by surfacing relevant tactical lessons before tool execution, with a feedback loop that strengthens good lessons and prunes bad ones.

**Architecture:** Enhance the existing `_experiences()` function in context.py with dynamic tool mapping from query_log. Add post-execution confidence adjustment in executor.py. Add experience pruning in heartbeat/profiling.py.

**Tech Stack:** Python 3.12, aiosqlite, pytest

**Spec:** `docs/superpowers/specs/2026-04-04-xskill-experience-store-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `odigos/core/context.py` | Smart experience retrieval with dynamic tool mapping |
| `odigos/core/executor.py` | Post-execution confidence adjustment and times_applied counter |
| `odigos/core/heartbeat/profiling.py` | Experience pruning (stale + low-confidence) |
| `tests/test_xskill.py` | Tests for all three components |

---

### Task 1: Tests for smart experience retrieval and feedback loop

**Files:**
- Create: `tests/test_xskill.py`

- [ ] **Step 1: Write tests**

Create `tests/test_xskill.py`:

```python
"""Tests for XSkill experience store: retrieval, feedback, pruning."""
import json
import pytest

from odigos.core.context import _get_likely_tools, _FALLBACK_TOOLS


class TestGetLikelyTools:
    """Dynamic tool mapping from query_log."""

    @pytest.mark.asyncio
    async def test_returns_tools_from_query_log(self, fake_db):
        """Finds tools historically used for a classification type."""
        await fake_db.execute(
            "INSERT INTO query_log (id, conversation_id, classification, tools_used, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("q1", "c1", "document_query", "search_documents,read_file", "2026-04-04T00:00:00"),
        )
        await fake_db.execute(
            "INSERT INTO query_log (id, conversation_id, classification, tools_used, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("q2", "c1", "document_query", "search_documents", "2026-04-04T00:00:00"),
        )
        tools = await _get_likely_tools(fake_db, "document_query")
        assert "search_documents" in tools
        assert "read_file" in tools

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_classification(self, fake_db):
        tools = await _get_likely_tools(fake_db, "nonexistent_type")
        assert tools == []

    @pytest.mark.asyncio
    async def test_handles_json_format_tools_used(self, fake_db):
        """tools_used can be JSON array format."""
        await fake_db.execute(
            "INSERT INTO query_log (id, conversation_id, classification, tools_used, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("q1", "c1", "complex", json.dumps(["search_web", "run_code"]), "2026-04-04T00:00:00"),
        )
        tools = await _get_likely_tools(fake_db, "complex")
        assert "search_web" in tools
        assert "run_code" in tools

    @pytest.mark.asyncio
    async def test_skips_null_and_empty_tools_used(self, fake_db):
        await fake_db.execute(
            "INSERT INTO query_log (id, conversation_id, classification, tools_used, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("q1", "c1", "simple", "", "2026-04-04T00:00:00"),
        )
        await fake_db.execute(
            "INSERT INTO query_log (id, conversation_id, classification, tools_used, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("q2", "c1", "simple", None, "2026-04-04T00:00:00"),
        )
        tools = await _get_likely_tools(fake_db, "simple")
        assert tools == []


class TestFallbackTools:
    def test_standard_has_search_tools(self):
        assert "search_web" in _FALLBACK_TOOLS["standard"]
        assert "search_documents" in _FALLBACK_TOOLS["standard"]

    def test_simple_has_no_tools(self):
        assert _FALLBACK_TOOLS["simple"] == []

    def test_creative_has_gen_tools(self):
        assert "generate_image" in _FALLBACK_TOOLS["creative"]
        assert "generate_music" in _FALLBACK_TOOLS["creative"]


class TestExperienceFeedback:
    """Executor updates experience confidence after tool execution."""

    @pytest.mark.asyncio
    async def test_success_boosts_confidence(self, fake_db):
        """Tool success increments times_applied and boosts confidence."""
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Try broader terms", 1, 0, 0.8, "sometimes",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )

        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=True, failure_category=None)

        row = await fake_db.fetch_one("SELECT times_applied, confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["times_applied"] == 1
        assert row["confidence"] == pytest.approx(0.85, abs=0.01)

    @pytest.mark.asyncio
    async def test_failure_erodes_confidence(self, fake_db):
        """Retryable failure erodes confidence of positive lessons."""
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Try broader terms", 1, 5, 0.8, "sometimes",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )

        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=False, failure_category="transient")

        row = await fake_db.fetch_one("SELECT confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["confidence"] == pytest.approx(0.7, abs=0.01)

    @pytest.mark.asyncio
    async def test_input_error_does_not_erode(self, fake_db):
        """Input/permission errors don't erode confidence."""
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Try broader terms", 1, 5, 0.8, "sometimes",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )

        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=False, failure_category="input")

        row = await fake_db.fetch_one("SELECT confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["confidence"] == pytest.approx(0.8, abs=0.01)

    @pytest.mark.asyncio
    async def test_failure_does_not_erode_anti_patterns(self, fake_db):
        """Failure anti-patterns (success=0) keep confidence when tool fails again."""
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Avoid narrow queries", 0, 3, 0.9, "always",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )

        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=False, failure_category="transient")

        row = await fake_db.fetch_one("SELECT confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["confidence"] == pytest.approx(0.9, abs=0.01)

    @pytest.mark.asyncio
    async def test_confidence_capped_at_1(self, fake_db):
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Tip", 1, 10, 0.98, "always",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )

        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=True, failure_category=None)

        row = await fake_db.fetch_one("SELECT confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_confidence_floored_at_0(self, fake_db):
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "search_web", "test", "test", "Tip", 1, 0, 0.05, "rare",
             "2026-04-04T00:00:00", "2026-04-04T00:00:00"),
        )

        from odigos.core.executor import _update_experience_feedback
        await _update_experience_feedback(fake_db, "search_web", success=False, failure_category="transient")

        row = await fake_db.fetch_one("SELECT confidence FROM agent_experiences WHERE id = 'e1'")
        assert row["confidence"] >= 0.0


class TestExperiencePruning:
    @pytest.mark.asyncio
    async def test_prunes_stale_unused_experiences(self, fake_db):
        """Experiences never applied after 30 days are pruned."""
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("old", "search_web", "test", "test", "Old tip", 1, 0, 0.5, "sometimes",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fresh", "search_web", "test", "test", "Fresh tip", 1, 0, 0.8, "always",
             "2026-04-03T00:00:00", "2026-04-03T00:00:00"),
        )

        from odigos.core.heartbeat.profiling import prune_stale_experiences
        await prune_stale_experiences(fake_db)

        rows = await fake_db.fetch_all("SELECT id FROM agent_experiences")
        ids = [r["id"] for r in rows]
        assert "old" not in ids
        assert "fresh" in ids

    @pytest.mark.asyncio
    async def test_prunes_low_confidence_experiences(self, fake_db):
        """Experiences with confidence below 0.2 are pruned."""
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("low", "search_web", "test", "test", "Bad tip", 1, 5, 0.1, "rare",
             "2026-04-03T00:00:00", "2026-04-03T00:00:00"),
        )
        await fake_db.execute(
            "INSERT INTO agent_experiences "
            "(id, tool_name, situation, outcome, lesson, success, times_applied, confidence, applicability, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("high", "search_web", "test", "test", "Good tip", 1, 10, 0.9, "always",
             "2026-04-03T00:00:00", "2026-04-03T00:00:00"),
        )

        from odigos.core.heartbeat.profiling import prune_stale_experiences
        await prune_stale_experiences(fake_db)

        rows = await fake_db.fetch_all("SELECT id FROM agent_experiences")
        ids = [r["id"] for r in rows]
        assert "low" not in ids
        assert "high" in ids
```

- [ ] **Step 2: Create the `fake_db` fixture**

The tests need an in-memory SQLite database with the required tables. Add a `conftest.py` fixture if one doesn't exist, or add to the existing one:

```python
# tests/conftest.py (add or create)
import pytest
import aiosqlite

class FakeDB:
    """Minimal async database wrapper for tests."""
    def __init__(self, conn):
        self._conn = conn
        self._conn.row_factory = aiosqlite.Row

    async def execute(self, sql, params=()):
        await self._conn.execute(sql, params)
        await self._conn.commit()

    async def fetch_all(self, sql, params=()):
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchall()

    async def fetch_one(self, sql, params=()):
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchone()

@pytest.fixture
async def fake_db():
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        db = FakeDB(conn)
        # Create tables needed by XSkill tests
        await conn.execute("""
            CREATE TABLE query_log (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                classification TEXT,
                tools_used TEXT,
                created_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE agent_experiences (
                id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                situation TEXT NOT NULL,
                outcome TEXT NOT NULL,
                lesson TEXT NOT NULL,
                success INTEGER DEFAULT 1,
                times_applied INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0.8,
                applicability TEXT DEFAULT 'sometimes',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await conn.commit()
        yield db
```

Check if `tests/conftest.py` exists first — if it does, add the fixture to it. If not, create it.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_xskill.py -v`
Expected: FAIL — functions don't exist yet

- [ ] **Step 4: Commit test file**

```bash
git add tests/test_xskill.py tests/conftest.py
git commit -m "test(xskill): add tests for experience retrieval, feedback, pruning"
```

---

### Task 2: Implement smart experience retrieval in context.py

**Files:**
- Modify: `odigos/core/context.py`

- [ ] **Step 1: Add `_get_likely_tools` function and `_FALLBACK_TOOLS` constant**

Add near the top of `context.py` (after imports, before the `ContextAssembler` class):

```python
import json as _json

_FALLBACK_TOOLS = {
    "simple": [],
    "standard": ["search_web", "search_documents"],
    "document_query": ["search_documents", "read_file"],
    "complex": ["search_web", "search_documents", "run_code"],
    "planning": ["decompose_query"],
    "code": ["run_code", "create_file"],
    "creative": ["generate_image", "generate_music"],
    "email": ["check_email", "send_email", "search_email"],
}

_CLASS_CATEGORIES = {
    "standard": ["search"],
    "document_query": ["search", "analysis"],
    "complex": ["search", "code"],
    "creative": ["create", "media"],
    "email": ["communication"],
    "code": ["code"],
}


async def _get_likely_tools(db, classification: str) -> list[str]:
    """Get tools historically used for this classification type from query_log."""
    rows = await db.fetch_all(
        "SELECT tools_used, COUNT(*) as cnt FROM query_log "
        "WHERE classification = ? AND tools_used IS NOT NULL AND tools_used != '' "
        "GROUP BY tools_used ORDER BY cnt DESC LIMIT 5",
        (classification,),
    )
    tools: set[str] = set()
    for row in rows:
        raw = row["tools_used"]
        if raw.startswith("["):
            tools.update(_json.loads(raw))
        else:
            tools.update(t.strip() for t in raw.split(",") if t.strip())
    return list(tools)
```

- [ ] **Step 2: Replace the `_experiences()` inner function**

In `context.py`, find the `_experiences()` function inside `build()` (around lines 235-251). Replace it with:

```python
        async def _experiences():
            if not self.db or skip_experiences:
                return ""
            try:
                classification_type = (
                    query_analysis.classification if query_analysis else "standard"
                )

                # Tier 1: Dynamic lookup from query_log history
                tool_names = await _get_likely_tools(self.db, classification_type)

                # Tier 2: Static fallback map
                if not tool_names:
                    tool_names = _FALLBACK_TOOLS.get(classification_type, [])

                # Tier 3: Category-based fallback from tool registry
                if not tool_names:
                    cats = _CLASS_CATEGORIES.get(classification_type, [])
                    if cats and self.tool_registry:
                        tool_names = [
                            t.name for t in self.tool_registry.list()
                            if t.category in cats
                        ]

                if tool_names:
                    placeholders = ",".join("?" * len(tool_names))
                    exp_rows = await self.db.fetch_all(
                        f"SELECT tool_name, lesson, success, confidence "
                        f"FROM agent_experiences "
                        f"WHERE tool_name IN ({placeholders}) "
                        f"ORDER BY confidence DESC, updated_at DESC LIMIT 5",
                        tool_names,
                    )
                else:
                    exp_rows = await self.db.fetch_all(
                        "SELECT tool_name, lesson, success, confidence "
                        "FROM agent_experiences "
                        "WHERE confidence >= 0.7 OR success = 0 "
                        "ORDER BY confidence DESC, updated_at DESC LIMIT 5"
                    )

                if not exp_rows:
                    return ""

                lines = ["## Tactical experience (learned from past interactions)"]
                for row in exp_rows:
                    prefix = "Warning" if not row["success"] else "Tip"
                    lines.append(f"- [{prefix}] {row['tool_name']}: {row['lesson']}")
                return "\n".join(lines)
            except Exception:
                logger.debug("Could not load experiences", exc_info=True)
            return ""
```

Note: `self.tool_registry` may not exist on `ContextAssembler`. Check if it's available — if not, skip the Tier 3 fallback for now (the first two tiers handle 95% of cases).

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "from odigos.core.context import _get_likely_tools, _FALLBACK_TOOLS; print('OK')"`

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_xskill.py::TestGetLikelyTools tests/test_xskill.py::TestFallbackTools -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/core/context.py
git commit -m "feat(xskill): smart experience retrieval with dynamic tool mapping"
```

---

### Task 3: Implement feedback loop in executor.py

**Files:**
- Modify: `odigos/core/executor.py`

- [ ] **Step 1: Add `_update_experience_feedback` function**

Add as a module-level async function in `executor.py` (after imports, near the other module-level functions like `_coerce_and_validate`):

```python
async def _update_experience_feedback(
    db, tool_name: str, success: bool, failure_category: str | None,
) -> None:
    """Update experience confidence based on tool execution outcome."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        if success:
            await db.execute(
                "UPDATE agent_experiences "
                "SET times_applied = times_applied + 1, "
                "    confidence = MIN(confidence + 0.05, 1.0), "
                "    updated_at = ? "
                "WHERE tool_name = ?",
                (now, tool_name),
            )
        elif failure_category not in ("input", "permission"):
            await db.execute(
                "UPDATE agent_experiences "
                "SET confidence = MAX(confidence - 0.1, 0.0), "
                "    updated_at = ? "
                "WHERE tool_name = ? AND success = 1",
                (now, tool_name),
            )
    except Exception:
        logger.debug("Experience feedback update failed", exc_info=True)
```

- [ ] **Step 2: Integrate into `_execute_tool`**

In the `_execute_tool` method, add the feedback call after result processing but before the final return. Find the section around line 707 where successful results are returned:

```python
            # Experience feedback (non-blocking, best-effort)
            if self.db:
                await _update_experience_feedback(
                    self.db, tool_call.name,
                    success=result.success if result else False,
                    failure_category=category,
                )

            if result.success:
                display = tool.format_for_context(result)
                ...
```

Place the feedback call BEFORE the `if result.success:` return block but AFTER the error logging, so it runs for both success and failure paths.

- [ ] **Step 3: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_xskill.py::TestExperienceFeedback -v`
Expected: All PASS

- [ ] **Step 4: Run all existing tests to verify no breakage**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_executor_validation.py tests/test_xskill.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/core/executor.py
git commit -m "feat(xskill): executor feedback loop for experience confidence"
```

---

### Task 4: Implement experience pruning in profiling.py

**Files:**
- Modify: `odigos/core/heartbeat/profiling.py`

- [ ] **Step 1: Add `prune_stale_experiences` function**

Add as a module-level async function in `profiling.py` (after imports):

```python
async def prune_stale_experiences(db) -> int:
    """Remove stale and low-confidence experiences.

    Prunes:
    - Never-applied experiences older than 30 days
    - Experiences with confidence below 0.2
    Returns number of rows deleted.
    """
    cursor = await db.execute(
        "DELETE FROM agent_experiences "
        "WHERE (times_applied = 0 AND created_at < datetime('now', '-30 days')) "
        "OR confidence < 0.2"
    )
    return cursor.rowcount if hasattr(cursor, 'rowcount') else 0
```

- [ ] **Step 2: Call it at the end of `extract_experiences()`**

Find the end of `extract_experiences()` (after the insertion loop completes, around line 279). Add:

```python
    # Prune stale and low-confidence experiences
    pruned = await prune_stale_experiences(hb.db)
    if pruned:
        logger.info("Pruned %d stale/low-confidence experiences", pruned)
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_xskill.py::TestExperiencePruning -v`
Expected: All PASS

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_xskill.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add odigos/core/heartbeat/profiling.py
git commit -m "feat(xskill): prune stale and low-confidence experiences"
```

---

### Task 5: Integration verification

- [ ] **Step 1: Run all tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 2: Verify imports**

Run:
```bash
python3 -c "
from odigos.core.context import _get_likely_tools, _FALLBACK_TOOLS
from odigos.core.executor import _update_experience_feedback
from odigos.core.heartbeat.profiling import prune_stale_experiences
print('All XSkill imports OK')
"
```

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "fix: xskill integration cleanup"
```
