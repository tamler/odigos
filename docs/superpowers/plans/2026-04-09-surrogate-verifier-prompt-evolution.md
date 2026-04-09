# Surrogate Skill Verifier + Two-Axis Prompt Evolution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two Group 1 Agent Quality features: (1) an informationally isolated surrogate verifier that validates skill quality at creation time, and (2) a periodic consolidation job that distills user corrections into two personality section files (operational rules + behavioral principles).

**Architecture:** Feature 1 adds `odigos/skills/verifier.py` with a generic `verify(task_description, output_artifacts)` interface and a skill-specific wrapper. Feature 2 adds `odigos/core/consolidation.py` with a `PromptConsolidator` that runs in heartbeat Phase 6 using Mem^p Add/Remove/Update operations. Both features are independent — no shared code, tables, or runtime state.

**Tech Stack:** Python 3.12, aiosqlite, FastAPI, LLMClient (odigos.providers.llm), tiktoken (token counting for compaction)

**Spec:** `docs/superpowers/specs/2026-04-09-surrogate-verifier-prompt-evolution-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `odigos/skills/verifier.py` | SkillVerifier class — scenario generation, skill execution, isolated evaluation |
| `odigos/core/consolidation.py` | PromptConsolidator class — classify corrections, merge into sections, compact |
| `data/prompts/verification_scenarios.md` | Prompt for generating test scenarios from skill description |
| `data/prompts/verification_evaluate.md` | Prompt for evaluating skill output quality |
| `data/prompts/consolidation_merge.md` | Prompt for classifying corrections and producing merge operations |
| `data/prompts/consolidation_compact.md` | Prompt for compacting over-budget sections |
| `data/agent/operational_rules.md` | Empty section file — populated by consolidation |
| `data/agent/behavioral_principles.md` | Empty section file — populated by consolidation |
| `tests/test_skill_verifier.py` | Tests for SkillVerifier |
| `tests/test_consolidation.py` | Tests for PromptConsolidator |
| `migrations/005_verifier_consolidation.sql` | Schema migration for new tables + column |

### Modified Files

| File | Change |
|------|--------|
| `odigos/skills/registry.py` | Add `verification_score`, `verification_at`, `escalation_level` fields to Skill dataclass |
| `odigos/skills/maturity.py` | Gate promotion on `verified == True`, add demotion on failed re-verification |
| `odigos/tools/skill_manage.py` | Call verifier after create/update, return diagnostics on failure |
| `odigos/core/heartbeat/maintenance.py` | Add consolidation step + periodic re-verification in `run_evolution()` |
| `schema.sql` | Add `skill_verifications` table, `consolidation_log` table, `corrections.consolidated_at` column |

---

### Task 1: Database Schema — Migration + Baseline

**Files:**
- Modify: `schema.sql`
- Create: `migrations/005_verifier_consolidation.sql`
- Test: `tests/test_consolidation.py` (schema portion)

- [ ] **Step 1: Write the failing test for new tables**

```python
# tests/test_consolidation.py
"""Tests for prompt consolidation and skill verification schema."""
from __future__ import annotations

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


class TestSchema:
    async def test_skill_verifications_table_exists(self, db):
        row_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO skill_verifications (id, skill_name, overall_score, model_used) "
            "VALUES (?, ?, ?, ?)",
            (row_id, "legal-draft", 0.85, "test/model"),
        )
        row = await db.fetch_one(
            "SELECT * FROM skill_verifications WHERE id = ?", (row_id,)
        )
        assert row is not None
        assert row["skill_name"] == "legal-draft"
        assert row["overall_score"] == 0.85

    async def test_consolidation_log_table_exists(self, db):
        row_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO consolidation_log (id, axis, corrections_processed, rules_before, rules_after) "
            "VALUES (?, ?, ?, ?, ?)",
            (row_id, "operational", 5, 3, 6),
        )
        row = await db.fetch_one(
            "SELECT * FROM consolidation_log WHERE id = ?", (row_id,)
        )
        assert row is not None
        assert row["axis"] == "operational"
        assert row["corrections_processed"] == 5

    async def test_corrections_consolidated_at_column(self, db):
        conv_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (conv_id, "test"),
        )
        corr_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO corrections (id, conversation_id, correction, category) "
            "VALUES (?, ?, ?, ?)",
            (corr_id, conv_id, "Fix this", "accuracy"),
        )
        # consolidated_at should exist and default to NULL
        row = await db.fetch_one(
            "SELECT consolidated_at FROM corrections WHERE id = ?", (corr_id,)
        )
        assert row is not None
        assert row["consolidated_at"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_consolidation.py -x -q`
Expected: FAIL — tables/column don't exist yet.

- [ ] **Step 3: Add tables to schema.sql**

Add to the end of `schema.sql`:

```sql
-- Skill verification history
CREATE TABLE IF NOT EXISTS skill_verifications (
    id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    scenarios_json TEXT,
    results_json TEXT,
    overall_score REAL,
    escalation_level INTEGER DEFAULT 0,
    diagnostics TEXT,
    model_used TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_skill_verifications_skill
    ON skill_verifications(skill_name);

-- Consolidation audit log
CREATE TABLE IF NOT EXISTS consolidation_log (
    id TEXT PRIMARY KEY,
    axis TEXT NOT NULL,
    corrections_processed INTEGER,
    operations_json TEXT,
    rules_before INTEGER,
    rules_after INTEGER,
    compacted INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
```

Also add `consolidated_at` to the existing `corrections` table definition in `schema.sql` (add it after the `applied_count` column):

```sql
    consolidated_at TEXT,
```

- [ ] **Step 4: Create migration file**

Create `migrations/005_verifier_consolidation.sql`:

```sql
-- Add consolidated_at to corrections (for existing DBs)
ALTER TABLE corrections ADD COLUMN consolidated_at TEXT;

-- Mark pre-existing corrections as pre-migration (cold start safety)
UPDATE corrections SET consolidated_at = 'pre-migration'
WHERE created_at < datetime('now', '-30 days');

-- Skill verification history
CREATE TABLE IF NOT EXISTS skill_verifications (
    id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    scenarios_json TEXT,
    results_json TEXT,
    overall_score REAL,
    escalation_level INTEGER DEFAULT 0,
    diagnostics TEXT,
    model_used TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_skill_verifications_skill
    ON skill_verifications(skill_name);

-- Consolidation audit log
CREATE TABLE IF NOT EXISTS consolidation_log (
    id TEXT PRIMARY KEY,
    axis TEXT NOT NULL,
    corrections_processed INTEGER,
    operations_json TEXT,
    rules_before INTEGER,
    rules_after INTEGER,
    compacted INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_consolidation.py -x -q`
Expected: PASS (3 tests)

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q`
Expected: All existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add schema.sql migrations/005_verifier_consolidation.sql tests/test_consolidation.py
git commit -m "feat: add schema for skill verifications and consolidation log"
```

---

### Task 2: Skill Registry — Add Verification Fields

**Files:**
- Modify: `odigos/skills/registry.py:14-31`
- Test: `tests/test_skill_maturity.py` (extend `_make_skill` helper)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skill_maturity.py`:

```python
def test_skill_has_verification_fields():
    skill = _make_skill()
    assert skill.verification_score == 0.0
    assert skill.verification_at == ""
    assert skill.escalation_level == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_skill_maturity.py::test_skill_has_verification_fields -v`
Expected: FAIL — `Skill` has no attribute `verification_score`.

- [ ] **Step 3: Add fields to Skill dataclass**

In `odigos/skills/registry.py`, add three new fields after `last_used_at: str = ""` (line 31):

```python
    verification_score: float = 0.0
    verification_at: str = ""
    escalation_level: int = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_skill_maturity.py -v`
Expected: All tests PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add odigos/skills/registry.py tests/test_skill_maturity.py
git commit -m "feat: add verification_score, verification_at, escalation_level to Skill"
```

---

### Task 3: Maturity Gates — Verification Required for Promotion + Demotion

**Files:**
- Modify: `odigos/skills/maturity.py`
- Modify: `tests/test_skill_maturity.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_skill_maturity.py`:

```python
def test_progenitor_to_committed_requires_verified():
    """Promotion blocked if skill is not verified."""
    skill = _make_skill(
        maturity="progenitor",
        usage_count=COMMIT_MIN_USES,
        avg_score=COMMIT_MIN_SCORE,
    )
    skill.verified = False
    result = evaluate_maturity(skill)
    assert result is None  # blocked


def test_progenitor_to_committed_with_verified():
    """Promotion succeeds when verified == True."""
    skill = _make_skill(
        maturity="progenitor",
        usage_count=COMMIT_MIN_USES,
        avg_score=COMMIT_MIN_SCORE,
    )
    skill.verified = True
    result = evaluate_maturity(skill)
    assert result == "committed"


def test_committed_to_mature_requires_verification_score():
    """Promotion to mature requires verification_score >= 0.7."""
    skill = _make_skill(
        maturity="committed",
        usage_count=MATURE_MIN_USES,
        avg_score=MATURE_MIN_SCORE,
    )
    skill.verified = True
    skill.verification_score = 0.65  # too low
    result = evaluate_maturity(skill)
    assert result is None  # blocked


def test_committed_to_mature_with_verification_score():
    """Promotion to mature succeeds with verification_score >= 0.7."""
    skill = _make_skill(
        maturity="committed",
        usage_count=MATURE_MIN_USES,
        avg_score=MATURE_MIN_SCORE,
    )
    skill.verified = True
    skill.verification_score = 0.75
    result = evaluate_maturity(skill)
    assert result == "mature"


def test_demotion_on_failed_reverification():
    """Committed/mature skill demoted to progenitor on failed re-verification."""
    from odigos.skills.maturity import demote_on_failed_verification

    skill = _make_skill(
        maturity="committed",
        usage_count=10,
        avg_score=0.65,
    )
    skill.verification_score = 0.45
    skill.escalation_level = 1
    result = demote_on_failed_verification(skill)
    assert result == "progenitor"


def test_no_demotion_if_verification_passing():
    from odigos.skills.maturity import demote_on_failed_verification

    skill = _make_skill(
        maturity="committed",
        usage_count=10,
        avg_score=0.65,
    )
    skill.verification_score = 0.7
    skill.escalation_level = 0
    result = demote_on_failed_verification(skill)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_skill_maturity.py -k "verified or verification or demotion_on_failed" -v`
Expected: FAIL — existing `evaluate_maturity` doesn't check `verified`, and `demote_on_failed_verification` doesn't exist.

- [ ] **Step 3: Update maturity.py**

In `odigos/skills/maturity.py`, add a constant after `APOPTOSIS_FAIL_RATIO`:

```python
VERIFICATION_DEMOTION_SCORE = 0.5
MATURE_VERIFICATION_SCORE = 0.7
```

Update the progenitor -> committed promotion block (around line 56-63):

```python
    # Promotion: progenitor -> committed
    if current == "progenitor":
        if (
            uses >= COMMIT_MIN_USES
            and score >= COMMIT_MIN_SCORE
            and skill.verified
        ):
            logger.info(
                "Skill '%s' promoted: progenitor -> committed "
                "(uses=%d, score=%.2f, verified=%s)",
                skill.name, uses, score, skill.verified,
            )
            return "committed"
```

Update the committed -> mature promotion block (around line 65-73):

```python
    # Promotion: committed -> mature
    if current == "committed":
        if (
            uses >= MATURE_MIN_USES
            and score >= MATURE_MIN_SCORE
            and skill.verified
            and skill.verification_score >= MATURE_VERIFICATION_SCORE
        ):
            logger.info(
                "Skill '%s' promoted: committed -> mature "
                "(uses=%d, score=%.2f, vscore=%.2f)",
                skill.name, uses, score, skill.verification_score,
            )
            return "mature"
```

Add a new function after `update_skill_stats`:

```python
def demote_on_failed_verification(skill) -> str | None:
    """Demote skill to progenitor if re-verification failed after escalation.

    Returns 'progenitor' if demotion triggered, None otherwise.
    """
    if skill.builtin:
        return None
    if skill.maturity not in ("committed", "mature"):
        return None
    if (
        skill.escalation_level >= 1
        and skill.verification_score < VERIFICATION_DEMOTION_SCORE
    ):
        logger.info(
            "Skill '%s' demoted to progenitor: failed re-verification "
            "(vscore=%.2f, escalation=%d)",
            skill.name, skill.verification_score, skill.escalation_level,
        )
        return "progenitor"
    return None
```

- [ ] **Step 4: Fix the existing test_progenitor_to_committed test**

The existing `test_progenitor_to_committed` test doesn't set `verified=True`, so it will now fail. Update the `_make_skill` helper to accept a `verified` parameter, and update the existing test:

In `_make_skill`, add `verified: bool = True` parameter and pass it to the `Skill` constructor:

```python
def _make_skill(
    name: str = "test-skill",
    maturity: str = "progenitor",
    usage_count: int = 0,
    success_count: int = 0,
    failure_count: int = 0,
    avg_score: float = 0.0,
    builtin: bool = False,
    verified: bool = True,
) -> Skill:
    return Skill(
        name=name,
        description="A test skill",
        tools=[],
        complexity="standard",
        system_prompt="Do the thing.",
        builtin=builtin,
        verified=verified,
        maturity=maturity,
        usage_count=usage_count,
        success_count=success_count,
        failure_count=failure_count,
        avg_score=avg_score,
    )
```

And update `test_committed_to_mature` to also set `verification_score`:

```python
def test_committed_to_mature():
    skill = _make_skill(
        maturity="committed",
        usage_count=MATURE_MIN_USES,
        avg_score=MATURE_MIN_SCORE,
    )
    skill.verification_score = 0.75
    result = evaluate_maturity(skill)
    assert result == "mature"
```

- [ ] **Step 5: Run all maturity tests**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_skill_maturity.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add odigos/skills/maturity.py tests/test_skill_maturity.py
git commit -m "feat: gate maturity promotion on verification, add demotion on failed re-verification"
```

---

### Task 4: Verification Prompts

**Files:**
- Create: `data/prompts/verification_scenarios.md`
- Create: `data/prompts/verification_evaluate.md`

- [ ] **Step 1: Create verification_scenarios.md**

```markdown
You are a quality assurance specialist. Your job is to generate realistic test scenarios for evaluating whether a skill performs well.

You will receive a skill name and description. Generate test scenarios that a user might send when this skill is active.

## Rules

- Generate exactly {scenario_count} scenarios
- Include at least 1 edge case (ambiguous request, missing context, or unusual requirement)
- Scenarios should be realistic user messages, not meta-instructions
- Do NOT reference the skill by name in the scenarios -- write them as a user naturally would
- Each scenario should test a different aspect of the skill's capabilities

{escalation_instructions}

## Output Format

Return valid JSON only, no markdown fences:

```
{{"scenarios": ["scenario 1 text", "scenario 2 text", ...]}}
```

## Skill

**Name:** {skill_name}
**Description:** {skill_description}
```

- [ ] **Step 2: Create verification_evaluate.md**

```markdown
You are an independent quality evaluator. You will receive a task description and a response that was generated for a specific scenario. Evaluate the response quality.

IMPORTANT: You have NOT seen the instructions that produced this response. Judge it purely on whether it fulfills the task description for the given scenario.

## Evaluation Criteria

1. **Relevance** -- Does the response address the scenario?
2. **Completeness** -- Does it cover what the task description promises?
3. **Quality** -- Is the output well-structured and useful?
4. **No hallucination** -- Does it avoid making up facts or capabilities it doesn't have?

## Scoring

- Score each criterion 0.0 to 1.0
- Overall score is the average of all criteria
- Generate 3-5 specific assertions (pass/fail) that test concrete quality aspects

{escalation_instructions}

## Output Format

Return valid JSON only, no markdown fences:

```
{{
  "assertions": [
    {{"text": "Response addresses the user's specific request", "passed": true}},
    {{"text": "Output includes structured formatting", "passed": true}},
    {{"text": "No fabricated references or citations", "passed": true}}
  ],
  "scores": {{
    "relevance": 0.9,
    "completeness": 0.8,
    "quality": 0.85,
    "no_hallucination": 1.0
  }},
  "overall_score": 0.89,
  "diagnostics": "Optional failure explanation -- only if overall_score < 0.6"
}}
```

## Task Description

{task_description}

## Scenario

{scenario}

## Response to Evaluate

{response}
```

- [ ] **Step 3: Commit**

```bash
git add data/prompts/verification_scenarios.md data/prompts/verification_evaluate.md
git commit -m "feat: add verification prompts for scenario generation and evaluation"
```

---

### Task 5: SkillVerifier — Core Module

**Files:**
- Create: `odigos/skills/verifier.py`
- Create: `tests/test_skill_verifier.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_skill_verifier.py
"""Tests for the surrogate skill verifier."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from odigos.skills.verifier import (
    ScenarioResult,
    SkillVerifier,
    VerificationResult,
)


def _make_llm_response(content: str):
    """Create a mock LLMResponse with the given content."""
    from odigos.providers.base import LLMResponse

    return LLMResponse(
        content=content,
        model="test/model",
        tokens_in=100,
        tokens_out=200,
        cost_usd=0.001,
    )


class TestVerify:
    async def test_verify_passing_artifacts(self):
        """verify() returns passed=True when evaluation scores are high."""
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(json.dumps({
                "assertions": [
                    {"text": "Addresses request", "passed": True},
                    {"text": "Well structured", "passed": True},
                ],
                "scores": {
                    "relevance": 0.9,
                    "completeness": 0.85,
                    "quality": 0.9,
                    "no_hallucination": 1.0,
                },
                "overall_score": 0.91,
                "diagnostics": None,
            }))
        )

        verifier = SkillVerifier(llm_client=mock_llm, prompts_dir="data/prompts")
        result = await verifier.verify(
            task_description="Generate legal documents",
            output_artifacts=["Here is your NDA draft..."],
            escalation_level=0,
        )

        assert result.passed is True
        assert result.overall_score >= 0.6
        assert result.diagnostics is None
        assert len(result.scenario_results) == 1

    async def test_verify_failing_artifacts(self):
        """verify() returns passed=False with diagnostics when scores are low."""
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(json.dumps({
                "assertions": [
                    {"text": "Addresses request", "passed": False},
                    {"text": "Well structured", "passed": False},
                ],
                "scores": {
                    "relevance": 0.3,
                    "completeness": 0.2,
                    "quality": 0.3,
                    "no_hallucination": 0.5,
                },
                "overall_score": 0.33,
                "diagnostics": "Response does not address the legal document request at all.",
            }))
        )

        verifier = SkillVerifier(llm_client=mock_llm, prompts_dir="data/prompts")
        result = await verifier.verify(
            task_description="Generate legal documents",
            output_artifacts=["I like pizza."],
            escalation_level=0,
        )

        assert result.passed is False
        assert result.overall_score < 0.6
        assert result.diagnostics is not None

    async def test_verify_averages_multiple_artifacts(self):
        """verify() averages scores across multiple output artifacts."""
        call_count = 0

        async def mock_complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                score = 0.9
            else:
                score = 0.5
            return _make_llm_response(json.dumps({
                "assertions": [{"text": "Check", "passed": score > 0.6}],
                "scores": {"relevance": score, "completeness": score,
                           "quality": score, "no_hallucination": score},
                "overall_score": score,
                "diagnostics": None if score > 0.6 else "Low quality.",
            }))

        mock_llm = AsyncMock()
        mock_llm.complete = mock_complete

        verifier = SkillVerifier(llm_client=mock_llm, prompts_dir="data/prompts")
        result = await verifier.verify(
            task_description="Write poems",
            output_artifacts=["Great poem", "Bad poem"],
            escalation_level=0,
        )

        assert len(result.scenario_results) == 2
        assert 0.6 <= result.overall_score <= 0.8  # average of 0.9 and 0.5


class TestVerifySkill:
    async def test_verify_skill_generates_scenarios_and_evaluates(self):
        """verify_skill() generates scenarios, runs them, evaluates results."""
        scenarios_response = json.dumps({
            "scenarios": ["Draft an NDA for two parties", "Create a privacy policy"]
        })
        eval_response = json.dumps({
            "assertions": [{"text": "Addresses request", "passed": True}],
            "scores": {"relevance": 0.9, "completeness": 0.85,
                       "quality": 0.9, "no_hallucination": 1.0},
            "overall_score": 0.91,
            "diagnostics": None,
        })
        skill_response = "Here is your legal document..."

        call_sequence = []

        async def mock_complete(**kwargs):
            msgs = kwargs.get("messages", [])
            system_content = msgs[0]["content"] if msgs else ""
            if "test scenarios" in system_content.lower() or "quality assurance" in system_content.lower():
                call_sequence.append("scenarios")
                return _make_llm_response(scenarios_response)
            elif "independent quality evaluator" in system_content.lower():
                call_sequence.append("evaluate")
                return _make_llm_response(eval_response)
            else:
                call_sequence.append("skill_exec")
                return _make_llm_response(skill_response)

        mock_llm = AsyncMock()
        mock_llm.complete = mock_complete

        mock_registry = MagicMock()
        from odigos.skills.registry import Skill
        mock_registry.get.return_value = Skill(
            name="legal-draft",
            description="Generate legal documents -- NDAs, terms of service, privacy policies",
            tools=[],
            complexity="standard",
            system_prompt="You are an expert legal document drafter...",
        )

        verifier = SkillVerifier(
            llm_client=mock_llm,
            prompts_dir="data/prompts",
            skill_registry=mock_registry,
        )
        result = await verifier.verify_skill("legal-draft")

        assert result.passed is True
        assert "scenarios" in call_sequence
        assert "evaluate" in call_sequence
        assert "skill_exec" in call_sequence

    async def test_verify_skill_returns_diagnostics_on_failure(self):
        """verify_skill() returns diagnostics when skill produces poor output."""
        scenarios_response = json.dumps({
            "scenarios": ["Draft a simple NDA"]
        })
        eval_response = json.dumps({
            "assertions": [{"text": "Addresses request", "passed": False}],
            "scores": {"relevance": 0.2, "completeness": 0.1,
                       "quality": 0.2, "no_hallucination": 0.5},
            "overall_score": 0.25,
            "diagnostics": "Response is completely off-topic.",
        })

        async def mock_complete(**kwargs):
            msgs = kwargs.get("messages", [])
            system_content = msgs[0]["content"] if msgs else ""
            if "test scenarios" in system_content.lower() or "quality assurance" in system_content.lower():
                return _make_llm_response(scenarios_response)
            elif "independent quality evaluator" in system_content.lower():
                return _make_llm_response(eval_response)
            else:
                return _make_llm_response("I don't know what to do.")

        mock_llm = AsyncMock()
        mock_llm.complete = mock_complete

        mock_registry = MagicMock()
        from odigos.skills.registry import Skill
        mock_registry.get.return_value = Skill(
            name="bad-skill",
            description="Do something useful",
            tools=[],
            complexity="standard",
            system_prompt="You are confused...",
        )

        verifier = SkillVerifier(
            llm_client=mock_llm,
            prompts_dir="data/prompts",
            skill_registry=mock_registry,
        )
        result = await verifier.verify_skill("bad-skill")

        assert result.passed is False
        assert result.diagnostics is not None
        assert "off-topic" in result.diagnostics.lower()


class TestEscalation:
    async def test_escalation_raises_threshold(self):
        """Higher escalation levels require higher scores to pass."""
        eval_response = json.dumps({
            "assertions": [{"text": "Check", "passed": True}],
            "scores": {"relevance": 0.7, "completeness": 0.7,
                       "quality": 0.7, "no_hallucination": 0.7},
            "overall_score": 0.7,
            "diagnostics": None,
        })
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=_make_llm_response(eval_response))

        verifier = SkillVerifier(llm_client=mock_llm, prompts_dir="data/prompts")

        # Level 0: 0.7 passes (threshold 0.6)
        result_0 = await verifier.verify(
            task_description="Test", output_artifacts=["Output"],
            escalation_level=0,
        )
        assert result_0.passed is True

        # Level 1: 0.7 passes (threshold 0.7)
        result_1 = await verifier.verify(
            task_description="Test", output_artifacts=["Output"],
            escalation_level=1,
        )
        assert result_1.passed is True

        # Level 2: 0.7 fails (threshold 0.8)
        result_2 = await verifier.verify(
            task_description="Test", output_artifacts=["Output"],
            escalation_level=2,
        )
        assert result_2.passed is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_skill_verifier.py -x -q`
Expected: FAIL — `odigos.skills.verifier` doesn't exist.

- [ ] **Step 3: Implement verifier.py**

Create `odigos/skills/verifier.py`:

```python
"""Surrogate skill verifier — informationally isolated quality validation."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

PASS_THRESHOLDS = {0: 0.6, 1: 0.7, 2: 0.8}
DEFAULT_SCENARIO_COUNT = 3
ESCALATED_SCENARIO_COUNT = 5


@dataclass
class ScenarioResult:
    scenario: str
    response: str
    assertions: list[str] = field(default_factory=list)
    passed: list[bool] = field(default_factory=list)
    score: float = 0.0


@dataclass
class VerificationResult:
    passed: bool
    overall_score: float
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    diagnostics: str | None = None
    escalation_level: int = 0


class SkillVerifier:
    """Validates skill quality using an informationally isolated LLM session."""

    def __init__(
        self,
        llm_client,
        prompts_dir: str = "data/prompts",
        skill_registry: "SkillRegistry | None" = None,
        db=None,
    ) -> None:
        self._llm = llm_client
        self._prompts_dir = Path(prompts_dir)
        self._registry = skill_registry
        self._db = db

    async def verify(
        self,
        task_description: str,
        output_artifacts: list[str],
        escalation_level: int = 0,
    ) -> VerificationResult:
        """Verify output quality against task description.

        Generic interface — works for skills, code gen, or any task.
        """
        threshold = PASS_THRESHOLDS.get(escalation_level, 0.8)
        evaluate_prompt = self._load_prompt("verification_evaluate.md")

        escalation_instructions = ""
        if escalation_level >= 1:
            escalation_instructions = (
                "ESCALATED REVIEW (level {level}): Apply stricter criteria. "
                "Minor issues that would normally pass should now fail. "
                "Threshold for passing is {threshold:.1f}."
            ).format(level=escalation_level, threshold=threshold)

        scenario_results = []
        total_score = 0.0

        for i, artifact in enumerate(output_artifacts):
            scenario_label = f"Artifact {i + 1}"
            filled = evaluate_prompt.format(
                task_description=task_description,
                scenario=scenario_label,
                response=artifact[:4000],
                escalation_instructions=escalation_instructions,
            )

            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": filled},
                ],
                temperature=0.2,
                max_tokens=1000,
            )

            parsed = self._parse_evaluation(response.content)
            sr = ScenarioResult(
                scenario=scenario_label,
                response=artifact[:500],
                assertions=[a["text"] for a in parsed.get("assertions", [])],
                passed=[a["passed"] for a in parsed.get("assertions", [])],
                score=parsed.get("overall_score", 0.0),
            )
            scenario_results.append(sr)
            total_score += sr.score

        overall = total_score / max(len(output_artifacts), 1)
        diagnostics_parts = [
            sr.scenario + ": " + (parsed.get("diagnostics") or "")
            for sr, parsed in zip(scenario_results, [{}] * len(scenario_results))
            if sr.score < threshold
        ]
        # Collect diagnostics from the last evaluation if failing
        last_diag = parsed.get("diagnostics") if overall < threshold else None

        return VerificationResult(
            passed=overall >= threshold,
            overall_score=round(overall, 3),
            scenario_results=scenario_results,
            diagnostics=last_diag,
            escalation_level=escalation_level,
        )

    async def verify_skill(self, skill_name: str) -> VerificationResult:
        """Skill-specific wrapper. Generates scenarios, runs through skill, evaluates."""
        if not self._registry:
            raise ValueError("skill_registry required for verify_skill()")

        skill = self._registry.get(skill_name)
        if not skill:
            raise ValueError(f"Skill not found: {skill_name}")

        # Step 1: Generate scenarios (isolated — no system_prompt)
        scenarios = await self._generate_scenarios(
            skill.name, skill.description, skill.escalation_level
        )

        # Step 2: Run each scenario through the skill
        artifacts = []
        for scenario in scenarios:
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": skill.system_prompt},
                    {"role": "user", "content": scenario},
                ],
                temperature=0.7,
                max_tokens=2000,
            )
            artifacts.append(response.content)

        # Step 3: Evaluate (isolated — no system_prompt)
        result = await self.verify(
            task_description=skill.description,
            output_artifacts=artifacts,
            escalation_level=skill.escalation_level,
        )

        # Patch scenario labels with actual scenario text
        for i, sr in enumerate(result.scenario_results):
            if i < len(scenarios):
                sr.scenario = scenarios[i]

        # Step 4: Store verification record
        if self._db:
            import uuid
            await self._db.execute(
                "INSERT INTO skill_verifications "
                "(id, skill_name, scenarios_json, results_json, overall_score, "
                "escalation_level, diagnostics, model_used) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    skill_name,
                    json.dumps(scenarios),
                    json.dumps([
                        {"scenario": sr.scenario, "score": sr.score,
                         "assertions": sr.assertions, "passed": sr.passed}
                        for sr in result.scenario_results
                    ]),
                    result.overall_score,
                    result.escalation_level,
                    result.diagnostics,
                    getattr(self._llm, "default_model", "unknown"),
                ),
            )

        return result

    async def _generate_scenarios(
        self, skill_name: str, skill_description: str, escalation_level: int,
    ) -> list[str]:
        """Generate test scenarios from skill description (isolated session)."""
        prompt_template = self._load_prompt("verification_scenarios.md")
        count = ESCALATED_SCENARIO_COUNT if escalation_level >= 1 else DEFAULT_SCENARIO_COUNT

        escalation_instructions = ""
        if escalation_level >= 1:
            escalation_instructions = (
                "ESCALATED (level {level}): Generate harder scenarios. Include "
                "ambiguous requests, contradictory requirements, and edge cases "
                "with missing context."
            ).format(level=escalation_level)

        filled = prompt_template.format(
            skill_name=skill_name,
            skill_description=skill_description,
            scenario_count=count,
            escalation_instructions=escalation_instructions,
        )

        response = await self._llm.complete(
            messages=[{"role": "system", "content": filled}],
            temperature=0.7,
            max_tokens=1000,
        )

        parsed = self._parse_json(response.content)
        scenarios = parsed.get("scenarios", [])
        if not scenarios:
            logger.warning("Failed to parse scenarios for skill '%s'", skill_name)
            scenarios = [f"Use the {skill_name} skill for a typical task"]
        return scenarios[:count]

    def _load_prompt(self, filename: str) -> str:
        path = self._prompts_dir / filename
        if path.exists():
            return path.read_text()
        logger.warning("Prompt file not found: %s", path)
        return ""

    @staticmethod
    def _parse_evaluation(content: str) -> dict:
        """Parse evaluation JSON from LLM response."""
        return SkillVerifier._parse_json(content)

    @staticmethod
    def _parse_json(content: str) -> dict:
        """Parse JSON from LLM response, handling markdown fences."""
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # skip ```json
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from LLM response: %s", text[:200])
            return {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_skill_verifier.py -v`
Expected: All PASS.

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add odigos/skills/verifier.py tests/test_skill_verifier.py
git commit -m "feat: add SkillVerifier with isolated evaluation and escalation"
```

---

### Task 6: Wire Verifier into Skill Tools

**Files:**
- Modify: `odigos/tools/skill_manage.py`

- [ ] **Step 1: Update CreateSkillTool to accept and call verifier**

In `odigos/tools/skill_manage.py`, update `CreateSkillTool.__init__`:

```python
def __init__(
    self,
    skill_registry: SkillRegistry,
    tool_registry: ToolRegistry | None = None,
    verifier=None,
) -> None:
    self._registry = skill_registry
    self._tool_registry = tool_registry
    self._verifier = verifier
```

At the end of `CreateSkillTool.execute()`, after the success message is built (before the final `return`), add verification:

```python
        # Run verification if verifier is available
        if self._verifier:
            try:
                vresult = await self._verifier.verify_skill(name)
                skill.verified = vresult.passed
                skill.verification_score = vresult.overall_score
                from datetime import datetime, timezone
                skill.verification_at = datetime.now(timezone.utc).isoformat()
                self._registry.save(name)
                if vresult.passed:
                    msg += f" Verification passed (score: {vresult.overall_score:.2f})."
                else:
                    msg += (
                        f" Verification FAILED (score: {vresult.overall_score:.2f}). "
                        f"Diagnostics: {vresult.diagnostics or 'No details.'} "
                        "Consider revising the instructions."
                    )
            except Exception:
                logger.debug("Verification failed for skill '%s'", name, exc_info=True)

        return ToolResult(success=True, data=msg)
```

- [ ] **Step 2: Update UpdateSkillTool similarly**

In `UpdateSkillTool.__init__`, add `verifier=None` parameter. At the end of `execute()`, before the final return, add the same verification block (copy from CreateSkillTool but referencing the updated skill).

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q`
Expected: All pass. (Existing tests don't pass a verifier, so `self._verifier` is None and verification is skipped.)

- [ ] **Step 4: Commit**

```bash
git add odigos/tools/skill_manage.py
git commit -m "feat: wire verifier into CreateSkillTool and UpdateSkillTool"
```

---

### Task 7: Consolidation Prompts + Empty Section Files

**Files:**
- Create: `data/prompts/consolidation_merge.md`
- Create: `data/prompts/consolidation_compact.md`
- Create: `data/agent/operational_rules.md`
- Create: `data/agent/behavioral_principles.md`

- [ ] **Step 1: Create consolidation_merge.md**

```markdown
You are a prompt evolution specialist. You consolidate user corrections into concise behavioral rules.

## Input

You will receive:
1. The current rules in a section (may be empty)
2. A batch of new corrections from user feedback

## Your Job

For each correction, decide:
- **Axis classification**: Is this correction operational (concrete "do X not Y" — categories: accuracy, tool_choice) or behavioral (identity pattern — categories: tone, preference, behavior) or knowledge (factual — e.g., "the deadline is Friday not Thursday")?
- **Operation**: What change to the rules section?
  - ADD: New rule not covered by existing content
  - UPDATE: An existing rule needs revision based on this correction
  - REMOVE: An existing rule is contradicted by this correction
  - KEEP: No change needed (correction already covered)

## Contradiction Resolution

If two corrections in this batch contradict each other, apply the most recent one (corrections are ordered by date, newest last).
If an incoming correction contradicts an existing rule, UPDATE or REMOVE the existing rule.
If contradictions are significant, set "conflict": true on the operation.

## Knowledge Corrections

Corrections classified as "knowledge" (purely factual, not generalizable into a rule) should be marked with axis "knowledge" and op "SKIP". They will remain in vector search only.

## Output Format

Return valid JSON only, no markdown fences:

```
{{
  "classifications": [
    {{"correction_id": "id1", "axis": "operational"}},
    {{"correction_id": "id2", "axis": "behavioral"}},
    {{"correction_id": "id3", "axis": "knowledge"}}
  ],
  "operations": [
    {{"op": "ADD", "rule": "Always verify dates before comparison", "source_correction_id": "id1"}},
    {{"op": "UPDATE", "old_rule": "Search broadly", "new_rule": "Search broadly first, narrow after reviewing", "source_correction_id": "id2"}},
    {{"op": "REMOVE", "rule": "Use formal tone", "reason": "User prefers casual", "source_correction_id": "id4"}},
    {{"op": "SKIP", "source_correction_id": "id3", "reason": "Factual correction, not a rule"}}
  ],
  "updated_section": "- Rule 1\n- Rule 2\n- Rule 3"
}}
```

## Current Rules

{current_rules}

## New Corrections (ordered by date, newest last)

{corrections_block}
```

- [ ] **Step 2: Create consolidation_compact.md**

```markdown
You are a prompt optimization specialist. A rules section has exceeded its token budget. Compact it while preserving all meaningful signal.

## Rules for Compaction

- Merge overlapping rules into single statements
- Remove rules subsumed by more general principles
- Preserve tool-specific rules (they stay specific)
- Keep the total output under {max_tokens} tokens
- Output rules as a markdown bullet list (one rule per line, starting with "- ")
- Do NOT add commentary or explanation — output only the compacted rules

## Current Rules

{current_rules}

## Output

Return only the compacted rules as a markdown bullet list, no JSON wrapper:
```

- [ ] **Step 3: Create empty section files**

Create `data/agent/operational_rules.md`:

```markdown
---
priority: 25
always_include: true
---
```

Create `data/agent/behavioral_principles.md`:

```markdown
---
priority: 15
always_include: true
---
```

- [ ] **Step 4: Commit**

```bash
git add data/prompts/consolidation_merge.md data/prompts/consolidation_compact.md \
       data/agent/operational_rules.md data/agent/behavioral_principles.md
git commit -m "feat: add consolidation prompts and empty section files"
```

---

### Task 8: PromptConsolidator — Core Module

**Files:**
- Create: `odigos/core/consolidation.py`
- Extend: `tests/test_consolidation.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_consolidation.py`:

```python
import json
from unittest.mock import AsyncMock

from odigos.core.consolidation import ConsolidationOp, PromptConsolidator
from odigos.providers.base import LLMResponse


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, model="test/model",
        tokens_in=100, tokens_out=200, cost_usd=0.001,
    )


async def _seed_corrections(db, count: int = 5) -> list[str]:
    """Insert test corrections, return their IDs."""
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conv_id, "test"),
    )
    ids = []
    categories = ["accuracy", "tone", "preference", "tool_choice", "behavior"]
    for i in range(count):
        cid = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO corrections "
            "(id, conversation_id, original_response, correction, context, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cid, conv_id, f"Original {i}", f"Correction {i}",
             f"Context {i}", categories[i % len(categories)]),
        )
        ids.append(cid)
    return ids


class TestConsolidation:
    async def test_skips_when_fewer_than_min_batch(self, db):
        """consolidate() skips when fewer than 3 unconsolidated corrections."""
        await _seed_corrections(db, count=2)
        mock_llm = AsyncMock()
        consolidator = PromptConsolidator(
            db=db, llm_client=mock_llm,
            prompts_dir="data/prompts", sections_dir="data/agent",
        )
        stats = await consolidator.consolidate()
        assert stats["corrections_processed"] == 0
        mock_llm.complete.assert_not_called()

    async def test_processes_batch_and_marks_consolidated(self, db):
        """consolidate() processes corrections and marks them consolidated."""
        ids = await _seed_corrections(db, count=5)

        merge_response = json.dumps({
            "classifications": [
                {"correction_id": ids[0], "axis": "operational"},
                {"correction_id": ids[1], "axis": "behavioral"},
                {"correction_id": ids[2], "axis": "behavioral"},
                {"correction_id": ids[3], "axis": "operational"},
                {"correction_id": ids[4], "axis": "knowledge"},
            ],
            "operations": [
                {"op": "ADD", "rule": "Rule from correction 0",
                 "source_correction_id": ids[0]},
                {"op": "ADD", "rule": "Rule from correction 1",
                 "source_correction_id": ids[1]},
            ],
            "updated_section": "- Rule from correction 0\n- Rule from correction 1",
        })

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(merge_response)
        )

        consolidator = PromptConsolidator(
            db=db, llm_client=mock_llm,
            prompts_dir="data/prompts", sections_dir="data/agent",
        )
        stats = await consolidator.consolidate()

        assert stats["corrections_processed"] == 5

        # All corrections should be marked as consolidated
        rows = await db.fetch_all(
            "SELECT consolidated_at FROM corrections WHERE consolidated_at IS NOT NULL"
        )
        assert len(rows) == 5

    async def test_knowledge_corrections_marked_skipped(self, db):
        """Knowledge corrections get consolidated_at='skipped'."""
        ids = await _seed_corrections(db, count=3)

        merge_response = json.dumps({
            "classifications": [
                {"correction_id": ids[0], "axis": "knowledge"},
                {"correction_id": ids[1], "axis": "operational"},
                {"correction_id": ids[2], "axis": "behavioral"},
            ],
            "operations": [
                {"op": "SKIP", "source_correction_id": ids[0],
                 "reason": "Factual"},
                {"op": "ADD", "rule": "Operational rule",
                 "source_correction_id": ids[1]},
                {"op": "ADD", "rule": "Behavioral rule",
                 "source_correction_id": ids[2]},
            ],
            "updated_section": "- Operational rule",
        })

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(merge_response)
        )

        consolidator = PromptConsolidator(
            db=db, llm_client=mock_llm,
            prompts_dir="data/prompts", sections_dir="data/agent",
        )
        await consolidator.consolidate()

        row = await db.fetch_one(
            "SELECT consolidated_at FROM corrections WHERE id = ?", (ids[0],)
        )
        assert row["consolidated_at"] == "skipped"

    async def test_consolidation_log_written(self, db):
        """consolidate() writes an entry to consolidation_log."""
        await _seed_corrections(db, count=3)

        merge_response = json.dumps({
            "classifications": [
                {"correction_id": "x", "axis": "operational"},
            ] * 3,
            "operations": [
                {"op": "ADD", "rule": "Test rule", "source_correction_id": "x"},
            ],
            "updated_section": "- Test rule",
        })

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(merge_response)
        )

        consolidator = PromptConsolidator(
            db=db, llm_client=mock_llm,
            prompts_dir="data/prompts", sections_dir="data/agent",
        )
        await consolidator.consolidate()

        rows = await db.fetch_all("SELECT * FROM consolidation_log")
        assert len(rows) >= 1
        assert rows[0]["corrections_processed"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_consolidation.py::TestConsolidation -x -q`
Expected: FAIL — `odigos.core.consolidation` doesn't exist.

- [ ] **Step 3: Implement consolidation.py**

Create `odigos/core/consolidation.py`:

```python
"""Two-axis prompt evolution — consolidate corrections into personality sections."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import tiktoken

logger = logging.getLogger(__name__)

_ENCODER = None


def _count_tokens(text: str) -> int:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return len(_ENCODER.encode(text))


@dataclass
class ConsolidationOp:
    op: str
    rule: str = ""
    old_rule: str | None = None
    reason: str | None = None
    source_correction_id: str | None = None
    conflict: bool = False


class PromptConsolidator:
    """Distills raw corrections into personality section files."""

    OPERATIONAL_FILENAME = "operational_rules.md"
    BEHAVIORAL_FILENAME = "behavioral_principles.md"
    MIN_BATCH_SIZE = 3
    MAX_SECTION_TOKENS = 300

    def __init__(
        self, db, llm_client, prompts_dir: str = "data/prompts",
        sections_dir: str = "data/agent",
    ) -> None:
        self._db = db
        self._llm = llm_client
        self._prompts_dir = Path(prompts_dir)
        self._sections_dir = Path(sections_dir)

    async def consolidate(self) -> dict:
        """Run one consolidation pass. Returns stats dict."""
        corrections = await self._load_unconsolidated()
        if len(corrections) < self.MIN_BATCH_SIZE:
            return {"corrections_processed": 0}

        # Classify and merge
        merge_result = await self._classify_and_merge(corrections)
        classifications = merge_result.get("classifications", [])
        operations = merge_result.get("operations", [])
        updated_section = merge_result.get("updated_section", "")

        # Separate knowledge corrections
        knowledge_ids = {
            c["correction_id"]
            for c in classifications
            if c.get("axis") == "knowledge"
        }

        # Mark knowledge corrections as skipped
        now = datetime.now(timezone.utc).isoformat()
        for cid in knowledge_ids:
            await self._db.execute(
                "UPDATE corrections SET consolidated_at = 'skipped' WHERE id = ?",
                (cid,),
            )

        # Write updated sections if there are non-knowledge operations
        non_skip_ops = [o for o in operations if o.get("op") != "SKIP"]
        if non_skip_ops and updated_section:
            # Determine which axes got operations
            op_axes = set()
            for c in classifications:
                if c.get("axis") in ("operational", "behavioral"):
                    op_axes.add(c["axis"])

            for axis in op_axes:
                filename = (
                    self.OPERATIONAL_FILENAME
                    if axis == "operational"
                    else self.BEHAVIORAL_FILENAME
                )
                await self._write_section(filename, updated_section)

        # Mark all non-knowledge corrections as consolidated
        non_knowledge_ids = [
            c["id"] for c in corrections if c["id"] not in knowledge_ids
        ]
        for cid in non_knowledge_ids:
            await self._db.execute(
                "UPDATE corrections SET consolidated_at = ? WHERE id = ?",
                (now, cid),
            )

        # Compaction check
        for filename in (self.OPERATIONAL_FILENAME, self.BEHAVIORAL_FILENAME):
            content = self._read_section_content(filename)
            if content and _count_tokens(content) > self.MAX_SECTION_TOKENS:
                compacted = await self._compact(content)
                if compacted:
                    await self._write_section(filename, compacted)

        # Log
        rules_after = len([
            line for line in updated_section.split("\n")
            if line.strip().startswith("- ")
        ]) if updated_section else 0

        log_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO consolidation_log "
            "(id, axis, corrections_processed, operations_json, "
            "rules_before, rules_after) VALUES (?, ?, ?, ?, ?, ?)",
            (
                log_id,
                "mixed",
                len(corrections),
                json.dumps(operations),
                0,  # could count existing rules but not critical
                rules_after,
            ),
        )

        return {
            "corrections_processed": len(corrections),
            "operations": len(non_skip_ops),
            "knowledge_skipped": len(knowledge_ids),
        }

    async def _load_unconsolidated(self) -> list[dict]:
        """Load corrections where consolidated_at IS NULL."""
        rows = await self._db.fetch_all(
            "SELECT id, correction, context, category, original_response, created_at "
            "FROM corrections WHERE consolidated_at IS NULL "
            "ORDER BY created_at ASC",
        )
        return [dict(r) for r in rows]

    async def _classify_and_merge(self, corrections: list[dict]) -> dict:
        """LLM call to classify corrections and produce merge operations."""
        prompt_template = self._load_prompt("consolidation_merge.md")

        # Build corrections block
        lines = []
        for c in corrections:
            lines.append(
                f"- ID: {c['id']} | Category: {c['category']} | "
                f"Context: {c['context']} | "
                f"Original: {c['original_response'][:200]} | "
                f"Correction: {c['correction']}"
            )
        corrections_block = "\n".join(lines)

        # Load current rules from both sections
        op_rules = self._read_section_content(self.OPERATIONAL_FILENAME)
        beh_rules = self._read_section_content(self.BEHAVIORAL_FILENAME)
        current_rules = ""
        if op_rules:
            current_rules += f"### Operational Rules\n{op_rules}\n\n"
        if beh_rules:
            current_rules += f"### Behavioral Principles\n{beh_rules}\n\n"
        if not current_rules:
            current_rules = "(empty — no rules yet)"

        filled = prompt_template.format(
            current_rules=current_rules,
            corrections_block=corrections_block,
        )

        response = await self._llm.complete(
            messages=[{"role": "system", "content": filled}],
            temperature=0.3,
            max_tokens=2000,
        )

        return self._parse_json(response.content)

    async def _compact(self, content: str) -> str | None:
        """Compact a section that exceeds token budget."""
        prompt_template = self._load_prompt("consolidation_compact.md")
        filled = prompt_template.format(
            current_rules=content,
            max_tokens=self.MAX_SECTION_TOKENS,
        )

        response = await self._llm.complete(
            messages=[{"role": "system", "content": filled}],
            temperature=0.2,
            max_tokens=1000,
        )

        compacted = response.content.strip()
        if _count_tokens(compacted) <= self.MAX_SECTION_TOKENS:
            return compacted
        logger.warning("Compaction still over budget (%d tokens)", _count_tokens(compacted))
        return compacted  # still write it, better than nothing

    def _read_section_content(self, filename: str) -> str:
        """Read section file content, stripping YAML frontmatter."""
        path = self._sections_dir / filename
        if not path.exists():
            return ""
        text = path.read_text()
        # Strip frontmatter
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return text.strip()

    async def _write_section(self, filename: str, content: str) -> None:
        """Write section file preserving YAML frontmatter."""
        path = self._sections_dir / filename
        if path.exists():
            text = path.read_text()
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    path.write_text(f"---{frontmatter}---\n\n{content}\n")
                    return
        # Fallback: write with default frontmatter
        priority = 25 if "operational" in filename else 15
        path.write_text(
            f"---\npriority: {priority}\nalways_include: true\n---\n\n{content}\n"
        )

    def _load_prompt(self, filename: str) -> str:
        path = self._prompts_dir / filename
        if path.exists():
            return path.read_text()
        logger.warning("Prompt file not found: %s", path)
        return ""

    @staticmethod
    def _parse_json(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse consolidation JSON: %s", text[:200])
            return {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_consolidation.py -v`
Expected: All PASS.

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add odigos/core/consolidation.py tests/test_consolidation.py
git commit -m "feat: add PromptConsolidator with classify, merge, compact lifecycle"
```

---

### Task 9: Wire into Heartbeat Phase 6

**Files:**
- Modify: `odigos/core/heartbeat/maintenance.py`

- [ ] **Step 1: Add consolidation + re-verification to run_evolution**

In `odigos/core/heartbeat/maintenance.py`, update `run_evolution()`. After the `rollup_domain_performance` call and before the strategist block, add:

```python
        # Consolidate corrections into prompt sections
        if hasattr(hb, "consolidator") and hb.consolidator:
            try:
                stats = await hb.consolidator.consolidate()
                if stats.get("corrections_processed", 0) > 0:
                    logger.info(
                        "Consolidation: processed %d corrections, %d ops, %d knowledge skipped",
                        stats["corrections_processed"],
                        stats.get("operations", 0),
                        stats.get("knowledge_skipped", 0),
                    )
            except Exception:
                logger.debug("Consolidation failed", exc_info=True)

        # Re-verify one skill per cycle if score diverges
        if hasattr(hb, "skill_verifier") and hb.skill_verifier and hb.skill_registry:
            try:
                await _reverify_one_skill(hb)
            except Exception:
                logger.debug("Skill re-verification failed", exc_info=True)
```

Add the `_reverify_one_skill` helper function:

```python
async def _reverify_one_skill(hb) -> None:
    """Re-verify at most one committed/mature skill whose real-world score diverges."""
    from odigos.skills.maturity import demote_on_failed_verification

    for skill in hb.skill_registry.list():
        if skill.builtin or skill.maturity not in ("committed", "mature"):
            continue
        if not skill.verified or skill.verification_score == 0.0:
            continue
        # Check divergence: real-world score dropped 0.15+ below verification score
        if skill.avg_score < skill.verification_score - 0.15:
            logger.info(
                "Re-verifying skill '%s' (avg=%.2f vs vscore=%.2f)",
                skill.name, skill.avg_score, skill.verification_score,
            )
            skill.escalation_level += 1
            result = await hb.skill_verifier.verify_skill(skill.name)
            skill.verification_score = result.overall_score
            from datetime import datetime, timezone
            skill.verification_at = datetime.now(timezone.utc).isoformat()
            skill.verified = result.passed

            # Check for demotion
            demotion = demote_on_failed_verification(skill)
            if demotion:
                skill.maturity = demotion
                skill.escalation_level = 0

            hb.skill_registry.save(skill.name)
            return  # max 1 per cycle
```

- [ ] **Step 2: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q`
Expected: All pass. (Heartbeat tests don't exercise evolution with real consolidator/verifier.)

- [ ] **Step 3: Commit**

```bash
git add odigos/core/heartbeat/maintenance.py
git commit -m "feat: wire consolidation and re-verification into heartbeat Phase 6"
```

---

### Task 10: Bootstrap Wiring

**Files:**
- Modify: Bootstrap / initialization code where Heartbeat is constructed

- [ ] **Step 1: Find and update bootstrap**

Search for where the `Heartbeat` class is instantiated and the `EvolutionEngine` is wired in. Add `consolidator` and `skill_verifier` attributes:

```python
from odigos.core.consolidation import PromptConsolidator
from odigos.skills.verifier import SkillVerifier

# After llm_client and db are created:
consolidator = PromptConsolidator(
    db=db,
    llm_client=llm_client,
    prompts_dir="data/prompts",
    sections_dir="data/agent",
)

skill_verifier = SkillVerifier(
    llm_client=llm_client,
    prompts_dir="data/prompts",
    skill_registry=skill_registry,
    db=db,
)

# Set on heartbeat:
heartbeat.consolidator = consolidator
heartbeat.skill_verifier = skill_verifier

# Pass verifier to skill tools:
create_skill_tool = CreateSkillTool(skill_registry, tool_registry, verifier=skill_verifier)
update_skill_tool = UpdateSkillTool(skill_registry, tool_registry, verifier=skill_verifier)
```

Note: The exact file depends on how the bootstrap is structured. Look in `odigos/bootstrap.py` or `odigos/main.py` for where `Heartbeat` is constructed. The key attributes to set are `hb.consolidator` and `hb.skill_verifier`.

- [ ] **Step 2: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 3: Smoke test with make up**

Run: `cd /Users/jacob/Projects/odigos && make build && make up && make logs`
Expected: Container starts without import errors. Check logs for any startup exceptions.

- [ ] **Step 4: Commit**

```bash
git add odigos/bootstrap.py  # or wherever the wiring lives
git commit -m "feat: wire SkillVerifier and PromptConsolidator into bootstrap"
```

---

### Task 11: Integration Test — Full Verification Flow

**Files:**
- Extend: `tests/test_skill_verifier.py`

- [ ] **Step 1: Write integration test**

Add to `tests/test_skill_verifier.py`:

```python
class TestIntegrationWithDB:
    async def test_verify_skill_stores_verification_record(self, tmp_db_path):
        """Full flow: verify_skill stores a record in skill_verifications table."""
        from odigos.db import Database

        db = Database(tmp_db_path, migrations_dir="migrations")
        await db.initialize()

        try:
            scenarios_response = json.dumps({
                "scenarios": ["Write a haiku about coding"]
            })
            eval_response = json.dumps({
                "assertions": [{"text": "Is a haiku", "passed": True}],
                "scores": {"relevance": 0.9, "completeness": 0.9,
                           "quality": 0.9, "no_hallucination": 1.0},
                "overall_score": 0.93,
                "diagnostics": None,
            })

            async def mock_complete(**kwargs):
                msgs = kwargs.get("messages", [])
                content = msgs[0]["content"] if msgs else ""
                if "quality assurance" in content.lower():
                    return _make_llm_response(scenarios_response)
                elif "independent quality evaluator" in content.lower():
                    return _make_llm_response(eval_response)
                else:
                    return _make_llm_response("Code flows like streams\nBugs hide in the deepest lines\nTests reveal the truth")

            mock_llm = AsyncMock()
            mock_llm.complete = mock_complete
            mock_llm.default_model = "test/model"

            from odigos.skills.registry import Skill, SkillRegistry
            registry = SkillRegistry()
            registry._skills["haiku"] = Skill(
                name="haiku",
                description="Write haiku poems on any topic",
                tools=[],
                complexity="light",
                system_prompt="You are a haiku master. Write haikus.",
            )

            verifier = SkillVerifier(
                llm_client=mock_llm,
                prompts_dir="data/prompts",
                skill_registry=registry,
                db=db,
            )

            result = await verifier.verify_skill("haiku")

            assert result.passed is True
            assert result.overall_score > 0.6

            # Check DB record
            row = await db.fetch_one(
                "SELECT * FROM skill_verifications WHERE skill_name = 'haiku'"
            )
            assert row is not None
            assert row["overall_score"] > 0.6
            assert row["model_used"] == "test/model"
        finally:
            await db.close()
```

- [ ] **Step 2: Run test**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_skill_verifier.py::TestIntegrationWithDB -v`
Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_skill_verifier.py
git commit -m "test: add integration test for verification with real DB"
```

---

### Task 12: Integration Test — Full Consolidation Flow

**Files:**
- Extend: `tests/test_consolidation.py`

- [ ] **Step 1: Write integration test**

Add to `tests/test_consolidation.py`:

```python
import tempfile
import shutil
from pathlib import Path


class TestConsolidationIntegration:
    async def test_full_consolidation_writes_section_file(self, db):
        """Full flow: corrections consolidated into a real section file."""
        ids = await _seed_corrections(db, count=4)

        # Create temp sections dir
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write initial empty section files
            op_path = Path(tmpdir) / "operational_rules.md"
            op_path.write_text("---\npriority: 25\nalways_include: true\n---\n")

            beh_path = Path(tmpdir) / "behavioral_principles.md"
            beh_path.write_text("---\npriority: 15\nalways_include: true\n---\n")

            merge_response = json.dumps({
                "classifications": [
                    {"correction_id": ids[0], "axis": "operational"},
                    {"correction_id": ids[1], "axis": "behavioral"},
                    {"correction_id": ids[2], "axis": "operational"},
                    {"correction_id": ids[3], "axis": "knowledge"},
                ],
                "operations": [
                    {"op": "ADD", "rule": "Always verify dates",
                     "source_correction_id": ids[0]},
                    {"op": "ADD", "rule": "Prefer concise responses",
                     "source_correction_id": ids[1]},
                    {"op": "ADD", "rule": "Search broadly first",
                     "source_correction_id": ids[2]},
                    {"op": "SKIP", "source_correction_id": ids[3],
                     "reason": "Factual"},
                ],
                "updated_section": "- Always verify dates\n- Search broadly first",
            })

            mock_llm = AsyncMock()
            mock_llm.complete = AsyncMock(
                return_value=_make_llm_response(merge_response)
            )

            consolidator = PromptConsolidator(
                db=db, llm_client=mock_llm,
                prompts_dir="data/prompts", sections_dir=tmpdir,
            )
            stats = await consolidator.consolidate()

            assert stats["corrections_processed"] == 4
            assert stats["knowledge_skipped"] == 1

            # Verify section file was written
            content = op_path.read_text()
            assert "priority: 25" in content  # frontmatter preserved
            assert "Always verify dates" in content or "Search broadly" in content

            # Verify knowledge correction marked as skipped
            row = await db.fetch_one(
                "SELECT consolidated_at FROM corrections WHERE id = ?",
                (ids[3],),
            )
            assert row["consolidated_at"] == "skipped"

            # Verify non-knowledge corrections marked with timestamp
            for cid in ids[:3]:
                row = await db.fetch_one(
                    "SELECT consolidated_at FROM corrections WHERE id = ?",
                    (cid,),
                )
                assert row["consolidated_at"] is not None
                assert row["consolidated_at"] != "skipped"
```

- [ ] **Step 2: Run test**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/test_consolidation.py::TestConsolidationIntegration -v`
Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_consolidation.py
git commit -m "test: add integration test for full consolidation flow with section file writes"
```

---

### Task 13: Final — Full Suite + Smoke Test

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 2: Lint check**

Run: `cd /Users/jacob/Projects/odigos && ruff check odigos/skills/verifier.py odigos/core/consolidation.py`
Expected: No errors.

- [ ] **Step 3: Docker build + smoke test**

Run: `cd /Users/jacob/Projects/odigos && make build && make up && sleep 5 && make logs`
Expected: Clean startup, no import errors, heartbeat running.

- [ ] **Step 4: Final commit (if any lint fixes needed)**

```bash
git add -A && git commit -m "fix: lint and cleanup for verifier + consolidation"
```
