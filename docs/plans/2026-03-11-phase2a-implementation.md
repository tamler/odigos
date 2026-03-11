# Phase 2a: Strategist, Agent Registry, Evolution Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the strategist brain to the evolution engine, build the agent registry for multi-agent awareness, create evolution dashboard UI, and auto-generate conversation titles.

**Architecture:** The strategist runs in heartbeat Phase 5 after scoring, analyzing evaluation trends and generating trial hypotheses or specialization proposals. The agent registry tracks known peers with role/description metadata. New API endpoints expose evolution data to the dashboard. Auto-titles fire after the first assistant response via the fallback LLM model.

**Tech Stack:** Python 3.12, aiosqlite, FastAPI, React + shadcn/ui, existing LLMProvider/heartbeat infrastructure

**Reference:** Read `docs/plans/2026-03-11-phase2-evolution-agents-dashboard-design.md` for full design rationale.

---

### Task 1: Database Migration — Agent Registry + Strategist Tables

**Files:**
- Create: `migrations/016_phase2a.sql`

**Step 1: Write the migration**

```sql
-- Agent registry: known peers on the mesh
CREATE TABLE IF NOT EXISTS agent_registry (
    agent_name TEXT PRIMARY KEY,
    role TEXT,
    description TEXT,
    specialty TEXT,
    netbird_ip TEXT,
    ws_port INTEGER DEFAULT 8001,
    status TEXT DEFAULT 'offline',
    last_seen TEXT,
    capabilities TEXT,
    evolution_score REAL,
    allow_external_evaluation INTEGER DEFAULT 0,
    parent TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Strategist run history
CREATE TABLE IF NOT EXISTS strategist_runs (
    id TEXT PRIMARY KEY,
    evaluations_analyzed INTEGER,
    hypotheses_generated TEXT,
    specialization_proposals TEXT,
    direction_log_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Specialization proposals awaiting user approval
CREATE TABLE IF NOT EXISTS specialization_proposals (
    id TEXT PRIMARY KEY,
    proposed_by TEXT,
    role TEXT NOT NULL,
    specialty TEXT,
    description TEXT NOT NULL,
    rationale TEXT,
    seed_knowledge TEXT,
    status TEXT DEFAULT 'pending',
    approved_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON specialization_proposals(status);

-- Add evaluator_agent column to evaluations table for cross-agent eval tracking
ALTER TABLE evaluations ADD COLUMN evaluator_agent TEXT;
```

**Step 2: Verify migration applies**

Run: `cd /Users/jacob/Projects/odigos && python3 -c "import asyncio; from odigos.db import Database; asyncio.run(Database(':memory:', migrations_dir='migrations').initialize()); print('Migration OK')"`
Expected: `Migration OK`

**Step 3: Commit**

```bash
git add migrations/016_phase2a.sql
git commit -m "feat: add agent registry, strategist, and specialization proposal tables

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Config Changes — Agent Identity

**Files:**
- Modify: `odigos/config.py:8-11` (AgentConfig)
- Modify: `odigos/config.py:101-105` (PeerConfig)

**Step 1: Write the failing test**

Create `tests/test_config_agent_identity.py`:

```python
"""Test agent identity config fields."""
from odigos.config import AgentConfig, PeerConfig, Settings


def test_agent_config_has_identity_fields():
    cfg = AgentConfig(name="TestBot", role="specialist", description="A test bot", parent="Odigos")
    assert cfg.role == "specialist"
    assert cfg.description == "A test bot"
    assert cfg.parent == "Odigos"
    assert cfg.allow_external_evaluation is False


def test_agent_config_defaults():
    cfg = AgentConfig()
    assert cfg.role == "personal_assistant"
    assert cfg.description == ""
    assert cfg.parent is None
    assert cfg.allow_external_evaluation is False


def test_peer_config_has_netbird_fields():
    peer = PeerConfig(name="Archie", netbird_ip="100.64.0.2", ws_port=8001, api_key="secret")
    assert peer.netbird_ip == "100.64.0.2"
    assert peer.ws_port == 8001
    # url should still work for backward compat
    peer_legacy = PeerConfig(name="Legacy", url="http://old-peer:8000")
    assert peer_legacy.url == "http://old-peer:8000"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_config_agent_identity.py -v`
Expected: FAIL (AgentConfig doesn't have `role` field)

**Step 3: Update config.py**

Update `AgentConfig` (lines 8-11):

```python
class AgentConfig(BaseModel):
    name: str = "Odigos"
    role: str = "personal_assistant"
    description: str = ""
    parent: str | None = None
    allow_external_evaluation: bool = False
    max_tool_turns: int = 25
    run_timeout_seconds: int = 300
```

Update `PeerConfig` (lines 101-105):

```python
class PeerConfig(BaseModel):
    """Configuration for a trusted peer agent."""
    name: str
    url: str = ""
    netbird_ip: str = ""
    ws_port: int = 8001
    api_key: str = ""
```

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_config_agent_identity.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add odigos/config.py tests/test_config_agent_identity.py
git commit -m "feat: add agent identity fields (role, description, parent) and NetBird peer config

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Strategist Module

**Files:**
- Create: `odigos/core/strategist.py`
- Test: `tests/test_strategist.py`

**Context:** The strategist reads evaluations, failed trials, and direction log, then asks the LLM to propose improvement hypotheses. It runs in heartbeat Phase 5 when enough new evaluations have accumulated (>=10 since last run).

**Step 1: Write the failing test**

```python
"""Tests for the Strategist module."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.strategist import Strategist
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


@pytest.fixture
def mock_evolution():
    ev = AsyncMock()
    ev.get_failed_trials = AsyncMock(return_value=[])
    ev.get_recent_directions = AsyncMock(return_value=[])
    ev.create_trial = AsyncMock(return_value="trial-123")
    ev.log_direction = AsyncMock(return_value="dir-123")
    return ev


@pytest.mark.asyncio
async def test_should_run_checks_evaluation_count(db, mock_provider, mock_evolution):
    strategist = Strategist(
        db=db, provider=mock_provider, evolution_engine=mock_evolution,
        agent_description="Test agent", agent_tools=["search", "code_execute"],
    )
    # No evaluations — should not run
    assert await strategist.should_run() is False

    # Add 10 evaluations
    for i in range(10):
        await db.execute(
            "INSERT INTO evaluations (id, overall_score, created_at) VALUES (?, ?, datetime('now'))",
            (str(uuid.uuid4()), 7.0),
        )
    assert await strategist.should_run() is True


@pytest.mark.asyncio
async def test_analyze_generates_hypotheses(db, mock_provider, mock_evolution):
    strategist = Strategist(
        db=db, provider=mock_provider, evolution_engine=mock_evolution,
        agent_description="Test agent", agent_tools=["search"],
    )
    # Seed evaluations
    for i in range(10):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, implicit_feedback, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "research", 5.0 + (i % 3), 0.2),
        )

    # Mock LLM returns hypotheses
    mock_provider.complete = AsyncMock(return_value=AsyncMock(content=json.dumps({
        "analysis": "Research tasks scoring below average",
        "direction": "Improve research thoroughness",
        "hypotheses": [
            {
                "type": "trial_hypothesis",
                "hypothesis": "Add more detail to research responses",
                "target": "prompt_section",
                "target_name": "voice",
                "change": "When researching, provide comprehensive summaries with sources.",
                "confidence": 0.8,
            }
        ],
        "specialization_proposals": [],
    })))

    result = await strategist.analyze()
    assert result is not None
    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0]["confidence"] == 0.8

    # Verify strategist run was recorded
    run = await db.fetch_one("SELECT * FROM strategist_runs ORDER BY created_at DESC LIMIT 1")
    assert run is not None


@pytest.mark.asyncio
async def test_auto_creates_trial_above_threshold(db, mock_provider, mock_evolution):
    strategist = Strategist(
        db=db, provider=mock_provider, evolution_engine=mock_evolution,
        agent_description="Test agent", agent_tools=["search"],
    )
    # Seed evaluations
    for i in range(10):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, created_at) VALUES (?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "general", 6.0),
        )

    mock_provider.complete = AsyncMock(return_value=AsyncMock(content=json.dumps({
        "analysis": "Responses could be more concise",
        "direction": "Improve conciseness",
        "hypotheses": [
            {
                "type": "trial_hypothesis",
                "hypothesis": "Be more concise",
                "target": "prompt_section",
                "target_name": "voice",
                "change": "Keep responses brief and direct.",
                "confidence": 0.8,
            }
        ],
        "specialization_proposals": [],
    })))

    result = await strategist.analyze()
    # Should auto-create trial since confidence > 0.7
    mock_evolution.create_trial.assert_called_once()


@pytest.mark.asyncio
async def test_specialization_proposal_stored(db, mock_provider, mock_evolution):
    strategist = Strategist(
        db=db, provider=mock_provider, evolution_engine=mock_evolution,
        agent_description="Test agent", agent_tools=["search"],
    )
    for i in range(10):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, created_at) VALUES (?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "coding", 4.0),
        )

    mock_provider.complete = AsyncMock(return_value=AsyncMock(content=json.dumps({
        "analysis": "Coding tasks consistently low",
        "direction": "Consider delegation",
        "hypotheses": [],
        "specialization_proposals": [
            {
                "role": "backend_dev",
                "specialty": "coding",
                "description": "Python backend specialist",
                "rationale": "Coding scores consistently below 5.0",
            }
        ],
    })))

    await strategist.analyze()
    proposal = await db.fetch_one("SELECT * FROM specialization_proposals WHERE status = 'pending'")
    assert proposal is not None
    assert proposal["role"] == "backend_dev"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_strategist.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
"""Strategist: analyzes evaluation trends and proposes improvement hypotheses.

Runs periodically in heartbeat Phase 5 when enough new evaluations accumulate.
Generates two types of output:
- trial_hypothesis: self-improvement proposals (auto-created if confidence > 0.7)
- specialization_proposal: new agent suggestions (stored for user approval)
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.core.evolution import EvolutionEngine
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

AUTO_TRIAL_CONFIDENCE = 0.7
MIN_EVALS_TO_RUN = 10


class Strategist:

    def __init__(
        self,
        db: Database,
        provider: LLMProvider,
        evolution_engine: EvolutionEngine,
        agent_description: str = "",
        agent_tools: list[str] | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.evolution = evolution_engine
        self._agent_description = agent_description
        self._agent_tools = agent_tools or []
        self._last_eval_count: int = 0

    async def should_run(self) -> bool:
        """Check if enough new evaluations have accumulated since last run."""
        row = await self.db.fetch_one(
            "SELECT COUNT(*) as cnt FROM evaluations"
        )
        total = row["cnt"] if row else 0
        return (total - self._last_eval_count) >= MIN_EVALS_TO_RUN

    async def analyze(self) -> dict | None:
        """Run the full strategist cycle: analyze, hypothesize, act."""
        # Gather context
        recent_evals = await self._get_evaluation_summary()
        failed_trials = await self.evolution.get_failed_trials(limit=10)
        directions = await self.evolution.get_recent_directions(limit=3)

        # Build prompt
        prompt = self._build_prompt(recent_evals, failed_trials, directions)

        # Ask LLM
        try:
            response = await self.provider.complete(
                [{"role": "user", "content": prompt}],
                model=getattr(self.provider, "fallback_model", None),
                max_tokens=800,
                temperature=0.4,
            )
            result = _parse_json(response.content)
            if result is None:
                logger.warning("Strategist: failed to parse LLM response")
                return None
        except Exception:
            logger.warning("Strategist: LLM call failed", exc_info=True)
            return None

        # Record the run
        run_id = str(uuid.uuid4())
        row = await self.db.fetch_one("SELECT COUNT(*) as cnt FROM evaluations")
        self._last_eval_count = row["cnt"] if row else 0

        # Log direction
        direction_id = await self.evolution.log_direction(
            analysis=result.get("analysis", ""),
            direction=result.get("direction", ""),
            opportunities=[],
            hypotheses=result.get("hypotheses", []),
            confidence=0.5,
            based_on_evaluations=self._last_eval_count,
        )

        await self.db.execute(
            "INSERT INTO strategist_runs (id, evaluations_analyzed, hypotheses_generated, "
            "specialization_proposals, direction_log_id) VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                self._last_eval_count,
                json.dumps(result.get("hypotheses", [])),
                json.dumps(result.get("specialization_proposals", [])),
                direction_id,
            ),
        )

        # Act on hypotheses
        for h in result.get("hypotheses", []):
            if h.get("type") == "trial_hypothesis" and h.get("confidence", 0) >= AUTO_TRIAL_CONFIDENCE:
                target_name = h.get("target_name", "voice")
                await self.evolution.create_trial(
                    hypothesis=h["hypothesis"],
                    target=h.get("target", "prompt_section"),
                    change_description=h.get("change", ""),
                    overrides={target_name: h.get("change", "")},
                    direction_log_id=direction_id,
                )
                logger.info("Strategist auto-created trial: %s", h["hypothesis"][:50])
                break  # Only one trial at a time

        # Store specialization proposals
        for sp in result.get("specialization_proposals", []):
            await self.db.execute(
                "INSERT INTO specialization_proposals "
                "(id, proposed_by, role, specialty, description, rationale) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    "strategist",
                    sp.get("role", "specialist"),
                    sp.get("specialty"),
                    sp.get("description", ""),
                    sp.get("rationale", ""),
                ),
            )
            logger.info("Strategist proposed specialist: %s", sp.get("role"))

        return result

    async def _get_evaluation_summary(self) -> dict:
        """Summarize recent evaluations by task type."""
        rows = await self.db.fetch_all(
            "SELECT task_type, COUNT(*) as cnt, AVG(overall_score) as avg_score, "
            "AVG(implicit_feedback) as avg_feedback "
            "FROM evaluations "
            "WHERE created_at > datetime('now', '-7 days') "
            "GROUP BY task_type "
            "ORDER BY cnt DESC LIMIT 10"
        )
        return {
            "by_task_type": [dict(r) for r in rows],
            "total_recent": sum(r["cnt"] for r in rows) if rows else 0,
        }

    def _build_prompt(self, eval_summary: dict, failed_trials: list, directions: list) -> str:
        failed_summary = ""
        if failed_trials:
            failed_summary = "\n".join(
                f"- {f.get('hypothesis', '?')}: {f.get('failure_reason', '?')} — {f.get('lessons', '')}"
                for f in failed_trials[:5]
            )

        direction_summary = ""
        if directions:
            direction_summary = "\n".join(
                f"- {d.get('direction', '?')} (confidence: {d.get('confidence', '?')})"
                for d in directions[:3]
            )

        task_summary = ""
        if eval_summary.get("by_task_type"):
            task_summary = "\n".join(
                f"- {t.get('task_type', '?')}: {t.get('cnt', 0)} actions, avg score {t.get('avg_score', 0):.1f}, "
                f"avg feedback {t.get('avg_feedback', 0):.1f}"
                for t in eval_summary["by_task_type"]
            )

        return f"""You are the strategist for an AI agent's self-improvement system.
Analyze this agent's recent performance and propose improvements.

## Agent Context
Description: {self._agent_description or 'No description set'}
Available tools: {', '.join(self._agent_tools) if self._agent_tools else 'None listed'}

## Recent Evaluation Summary (last 7 days)
{task_summary or 'No evaluations yet.'}

## Failed Trials (avoid repeating these)
{failed_summary or 'None.'}

## Recent Direction Log
{direction_summary or 'No prior direction set.'}

## Instructions
Based on the above, produce a JSON object with:
1. "analysis" — 1-2 sentence summary of current performance
2. "direction" — 1 sentence on what to focus on improving
3. "hypotheses" — Array of 0-3 improvement proposals. Each has:
   - "type": "trial_hypothesis"
   - "hypothesis": what to try
   - "target": "prompt_section"
   - "target_name": which section to modify (e.g. "voice", "identity", "meta")
   - "change": the new content for that section
   - "confidence": 0.0-1.0
4. "specialization_proposals" — Array of 0-1 proposals if a domain is consistently weak and would benefit from a dedicated specialist agent. Each has:
   - "role": short role name
   - "specialty": routing tag
   - "description": 1-2 sentences
   - "rationale": why this specialist is needed

Do NOT propose changes that have already failed (see failed trials above).
Return ONLY the JSON object, no markdown."""


def _parse_json(text: str) -> dict | None:
    """Extract JSON from LLM response."""
    import re
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, TypeError):
            pass
    return None
```

**Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_strategist.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add odigos/core/strategist.py tests/test_strategist.py
git commit -m "feat: add Strategist module for autonomous hypothesis generation

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Wire Strategist into Heartbeat Phase 5

**Files:**
- Modify: `odigos/core/heartbeat.py:14-22` (imports), `odigos/core/heartbeat.py:40-54` (init), `odigos/core/heartbeat.py:101-108` (_run_evolution)
- Modify: `odigos/main.py` (strategist initialization)

**Step 1: Write the failing test**

Create `tests/test_heartbeat_strategist.py`:

```python
"""Test that heartbeat Phase 5 runs the strategist."""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_tick_runs_strategist_when_should_run():
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
    heartbeat.evolution_engine.score_past_actions = AsyncMock(return_value=0)
    heartbeat.evolution_engine.check_active_trial = AsyncMock(return_value=None)
    heartbeat.strategist = AsyncMock()
    heartbeat.strategist.should_run = AsyncMock(return_value=True)
    heartbeat.strategist.analyze = AsyncMock(return_value={"hypotheses": []})

    heartbeat._fire_reminders = AsyncMock(return_value=False)
    heartbeat._work_todos = AsyncMock(return_value=False)
    heartbeat._deliver_subagent_results = AsyncMock(return_value=False)
    heartbeat._idle_think = AsyncMock()

    await heartbeat._tick()

    heartbeat.strategist.should_run.assert_called_once()
    heartbeat.strategist.analyze.assert_called_once()
```

**Step 2: Run to verify failure**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_heartbeat_strategist.py -v`
Expected: FAIL (Heartbeat doesn't have `strategist`)

**Step 3: Update heartbeat.py**

Add to TYPE_CHECKING imports (after `from odigos.core.evolution import EvolutionEngine`):
```python
from odigos.core.strategist import Strategist
```

Add `strategist` parameter to `__init__` (after `evolution_engine`):
```python
strategist: Strategist | None = None,
```

Store it: `self.strategist = strategist`

Update `_run_evolution` method to include strategist (replace existing method):

```python
    async def _run_evolution(self) -> None:
        """Phase 5: Score past actions, manage trials, run strategist."""
        try:
            scored = await self.evolution_engine.score_past_actions(limit=3)
            if scored:
                logger.debug("Evolution: scored %d past actions", scored)

            result = await self.evolution_engine.check_active_trial()
            if result and result != "continue":
                logger.info("Evolution: trial %s", result)

            # Run strategist if enough new evaluations
            if self.strategist:
                if await self.strategist.should_run():
                    analysis = await self.strategist.analyze()
                    if analysis:
                        logger.info("Strategist: analyzed, %d hypotheses",
                                    len(analysis.get("hypotheses", [])))
        except Exception:
            logger.debug("Evolution cycle failed", exc_info=True)
```

**Step 4: Update main.py**

After `evolution_engine` initialization, add strategist:

```python
from odigos.core.strategist import Strategist

# Gather tool names for strategist context
tool_names = [t.name for t in tool_registry.list()] if hasattr(tool_registry, 'list') else []

strategist = Strategist(
    db=_db,
    provider=_router,
    evolution_engine=evolution_engine,
    agent_description=settings.agent.description,
    agent_tools=tool_names,
)
logger.info("Strategist initialized")
```

Pass `strategist=strategist` to the Heartbeat constructor.

**Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_heartbeat_strategist.py tests/test_heartbeat_evolution.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add odigos/core/heartbeat.py odigos/main.py tests/test_heartbeat_strategist.py
git commit -m "feat: wire strategist into heartbeat Phase 5

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Evolution API Endpoints

**Files:**
- Create: `odigos/api/evolution.py`
- Test: `tests/test_api_evolution.py`

**Context:** The dashboard needs REST endpoints to read evolution data and manually control trials.

**Step 1: Write the failing test**

```python
"""Tests for the evolution API endpoints."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from odigos.api.evolution import router as evolution_router
from odigos.db import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:", migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def app(db):
    app = FastAPI()
    app.state.db = db
    app.state.api_key = "test-key"
    app.state.checkpoint_manager = AsyncMock()
    app.state.evolution_engine = AsyncMock()
    app.include_router(evolution_router)
    return app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers["Authorization"] = "Bearer test-key"
        yield c


@pytest.mark.asyncio
async def test_get_evolution_status(client, db):
    # Insert a trial
    cp_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO checkpoints (id, label) VALUES (?, ?)", (cp_id, "test")
    )
    trial_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO trials (id, checkpoint_id, hypothesis, target, expires_at, status) "
        "VALUES (?, ?, ?, ?, datetime('now', '+1 day'), 'active')",
        (trial_id, cp_id, "test hypothesis", "prompt_section"),
    )
    # Insert evaluations
    for i in range(3):
        await db.execute(
            "INSERT INTO evaluations (id, overall_score, created_at) VALUES (?, ?, datetime('now'))",
            (str(uuid.uuid4()), 7.0),
        )

    resp = await client.get("/api/evolution/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_trial"] is not None
    assert data["recent_eval_count"] == 3


@pytest.mark.asyncio
async def test_get_evaluations(client, db):
    for i in range(5):
        await db.execute(
            "INSERT INTO evaluations (id, task_type, overall_score, implicit_feedback, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), "general", 6.0 + i, 0.3),
        )
    resp = await client.get("/api/evolution/evaluations?limit=3")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["evaluations"]) == 3


@pytest.mark.asyncio
async def test_get_directions(client, db):
    await db.execute(
        "INSERT INTO direction_log (id, analysis, direction, confidence, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (str(uuid.uuid4()), "Doing well", "Keep going", 0.8),
    )
    resp = await client.get("/api/evolution/directions")
    assert resp.status_code == 200
    assert len(resp.json()["directions"]) == 1


@pytest.mark.asyncio
async def test_get_proposals(client, db):
    await db.execute(
        "INSERT INTO specialization_proposals (id, proposed_by, role, description, status) "
        "VALUES (?, ?, ?, ?, 'pending')",
        (str(uuid.uuid4()), "strategist", "coder", "Coding specialist"),
    )
    resp = await client.get("/api/proposals")
    assert resp.status_code == 200
    assert len(resp.json()["proposals"]) == 1


@pytest.mark.asyncio
async def test_approve_proposal(client, db):
    pid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO specialization_proposals (id, proposed_by, role, description, status) "
        "VALUES (?, ?, ?, ?, 'pending')",
        (pid, "strategist", "coder", "Coding specialist"),
    )
    resp = await client.post(f"/api/proposals/{pid}/approve")
    assert resp.status_code == 200
    row = await db.fetch_one("SELECT status FROM specialization_proposals WHERE id = ?", (pid,))
    assert row["status"] == "approved"
```

**Step 2: Run to verify failures**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_api_evolution.py -v`
Expected: FAIL

**Step 3: Write the implementation**

```python
"""Evolution engine API endpoints for dashboard."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from odigos.api.deps import get_db, require_api_key
from odigos.db import Database

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


@router.get("/evolution/status")
async def get_evolution_status(db: Database = Depends(get_db)):
    """Get current evolution engine status."""
    active_trial = await db.fetch_one(
        "SELECT * FROM trials WHERE status = 'active' ORDER BY started_at DESC LIMIT 1"
    )
    eval_count = await db.fetch_one("SELECT COUNT(*) as cnt FROM evaluations")
    recent_evals = await db.fetch_all(
        "SELECT overall_score FROM evaluations ORDER BY created_at DESC LIMIT 20"
    )
    avg_score = None
    if recent_evals:
        scores = [r["overall_score"] for r in recent_evals if r["overall_score"] is not None]
        avg_score = sum(scores) / len(scores) if scores else None

    return {
        "active_trial": dict(active_trial) if active_trial else None,
        "recent_eval_count": eval_count["cnt"] if eval_count else 0,
        "recent_avg_score": avg_score,
    }


@router.get("/evolution/evaluations")
async def get_evaluations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
):
    """Get paginated evaluation history."""
    rows = await db.fetch_all(
        "SELECT * FROM evaluations ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return {"evaluations": [dict(r) for r in rows]}


@router.get("/evolution/directions")
async def get_directions(
    limit: int = Query(default=10, ge=1, le=50),
    db: Database = Depends(get_db),
):
    """Get direction log entries."""
    rows = await db.fetch_all(
        "SELECT * FROM direction_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return {"directions": [dict(r) for r in rows]}


@router.get("/evolution/failed-trials")
async def get_failed_trials(
    limit: int = Query(default=20, ge=1, le=100),
    db: Database = Depends(get_db),
):
    """Get failed trial history."""
    rows = await db.fetch_all(
        "SELECT * FROM failed_trials_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return {"failed_trials": [dict(r) for r in rows]}


@router.post("/evolution/trial/{trial_id}/promote")
async def promote_trial(trial_id: str, request: Request, db: Database = Depends(get_db)):
    """Manually promote an active trial."""
    trial = await db.fetch_one(
        "SELECT * FROM trials WHERE id = ? AND status = 'active'", (trial_id,)
    )
    if not trial:
        raise HTTPException(status_code=404, detail="Active trial not found")
    checkpoint_mgr = request.app.state.checkpoint_manager
    await checkpoint_mgr.promote_trial(trial_id)
    return {"status": "promoted"}


@router.post("/evolution/trial/{trial_id}/revert")
async def revert_trial(trial_id: str, request: Request, db: Database = Depends(get_db)):
    """Manually revert an active trial."""
    trial = await db.fetch_one(
        "SELECT * FROM trials WHERE id = ? AND status = 'active'", (trial_id,)
    )
    if not trial:
        raise HTTPException(status_code=404, detail="Active trial not found")
    checkpoint_mgr = request.app.state.checkpoint_manager
    await checkpoint_mgr.revert_trial(trial_id, reason="manual_revert")
    return {"status": "reverted"}


@router.get("/proposals")
async def get_proposals(
    status: str = Query(default="pending"),
    db: Database = Depends(get_db),
):
    """Get specialization proposals."""
    rows = await db.fetch_all(
        "SELECT * FROM specialization_proposals WHERE status = ? ORDER BY created_at DESC",
        (status,),
    )
    return {"proposals": [dict(r) for r in rows]}


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, db: Database = Depends(get_db)):
    """Approve a specialization proposal."""
    row = await db.fetch_one(
        "SELECT * FROM specialization_proposals WHERE id = ? AND status = 'pending'",
        (proposal_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Pending proposal not found")
    await db.execute(
        "UPDATE specialization_proposals SET status = 'approved', approved_at = datetime('now') "
        "WHERE id = ?",
        (proposal_id,),
    )
    return {"status": "approved"}


@router.post("/proposals/{proposal_id}/dismiss")
async def dismiss_proposal(proposal_id: str, db: Database = Depends(get_db)):
    """Dismiss a specialization proposal."""
    row = await db.fetch_one(
        "SELECT * FROM specialization_proposals WHERE id = ? AND status = 'pending'",
        (proposal_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Pending proposal not found")
    await db.execute(
        "UPDATE specialization_proposals SET status = 'dismissed' WHERE id = ?",
        (proposal_id,),
    )
    return {"status": "dismissed"}
```

**Step 4: Mount the router in main.py**

Add after the existing router includes (around line 520):
```python
from odigos.api.evolution import router as evolution_router
app.include_router(evolution_router)
app.state.checkpoint_manager = checkpoint_manager
app.state.evolution_engine = evolution_engine
```

**Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_api_evolution.py -v`
Expected: All 5 tests PASS

**Step 6: Commit**

```bash
git add odigos/api/evolution.py tests/test_api_evolution.py odigos/main.py
git commit -m "feat: add evolution API endpoints for dashboard

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Conversation Auto-Title Generation

**Files:**
- Modify: `odigos/api/ws.py` (after chat_response is sent)
- Test: `tests/test_auto_title.py`

**Context:** After the first assistant response in a conversation, generate a short title via the fallback LLM and PATCH the conversation. The WebSocket handler in `odigos/api/ws.py` sends `chat_response` messages — that's where we hook in.

**Step 1: Write the failing test**

```python
"""Test conversation auto-title generation."""
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from odigos.core.auto_title import generate_title, maybe_auto_title
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
    provider.complete = AsyncMock(return_value=AsyncMock(
        content="Python Decorator Help"
    ))
    return provider


@pytest.mark.asyncio
async def test_generate_title(mock_provider):
    title = await generate_title(
        mock_provider, "Explain decorators in Python", "Decorators wrap functions..."
    )
    assert title == "Python Decorator Help"
    mock_provider.complete.assert_called_once()


@pytest.mark.asyncio
async def test_maybe_auto_title_sets_title(db, mock_provider):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "web")
    )
    # First message pair — should trigger title
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), conv_id, "user", "Explain decorators"),
    )
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), conv_id, "assistant", "Decorators wrap functions..."),
    )
    await maybe_auto_title(db, mock_provider, conv_id, "Explain decorators", "Decorators wrap functions...")
    conv = await db.fetch_one("SELECT title FROM conversations WHERE id = ?", (conv_id,))
    assert conv["title"] == "Python Decorator Help"


@pytest.mark.asyncio
async def test_maybe_auto_title_skips_if_title_exists(db, mock_provider):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel, title) VALUES (?, ?, ?)", (conv_id, "web", "Existing Title")
    )
    await maybe_auto_title(db, mock_provider, conv_id, "msg", "resp")
    # Should not call LLM
    mock_provider.complete.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_auto_title_skips_after_first_exchange(db, mock_provider):
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)", (conv_id, "web")
    )
    # Multiple messages — not the first exchange
    for i in range(4):
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), conv_id, "user" if i % 2 == 0 else "assistant", f"msg {i}"),
        )
    await maybe_auto_title(db, mock_provider, conv_id, "msg", "resp")
    # Should not call LLM (message_count > 2)
    mock_provider.complete.assert_not_called()
```

**Step 2: Run to verify failure**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_auto_title.py -v`
Expected: FAIL

**Step 3: Write the implementation**

Create `odigos/core/auto_title.py`:

```python
"""Auto-generate conversation titles after the first exchange."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.db import Database
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)


async def generate_title(provider: LLMProvider, user_message: str, assistant_response: str) -> str:
    """Generate a short conversation title from the first exchange."""
    response = await provider.complete(
        [{"role": "user", "content": (
            "Generate a short title (3-6 words, no quotes) for a conversation "
            "that starts with this exchange:\n\n"
            f"User: {user_message[:200]}\n"
            f"Assistant: {assistant_response[:200]}\n\n"
            "Title:"
        )}],
        model=getattr(provider, "fallback_model", None),
        max_tokens=20,
        temperature=0.3,
    )
    title = response.content.strip().strip('"').strip("'")
    # Truncate if too long
    if len(title) > 60:
        title = title[:57] + "..."
    return title


async def maybe_auto_title(
    db: Database,
    provider: LLMProvider,
    conversation_id: str,
    user_message: str,
    assistant_response: str,
) -> None:
    """Auto-title a conversation if it's the first exchange and has no title."""
    try:
        conv = await db.fetch_one(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        )
        if not conv:
            return
        if conv["title"]:
            return  # Already titled

        # Only auto-title on first exchange
        msg_count = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        if msg_count and msg_count["cnt"] > 2:
            return  # Past first exchange

        title = await generate_title(provider, user_message, assistant_response)
        await db.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title, conversation_id),
        )
        logger.debug("Auto-titled conversation %s: %s", conversation_id[:8], title)
    except Exception:
        logger.debug("Auto-title failed for %s", conversation_id, exc_info=True)
```

**Step 4: Wire into the WebSocket handler**

In `odigos/api/ws.py`, after the `chat_response` is sent back to the client, add an async call to `maybe_auto_title`. This fires in the background so it doesn't delay the response.

Find the line where `chat_response` is sent (approximately):
```python
await websocket.send_json({"type": "chat_response", "content": response, ...})
```

Add after it:
```python
# Auto-title in background (don't block response)
import asyncio
from odigos.core.auto_title import maybe_auto_title
asyncio.create_task(maybe_auto_title(
    db, provider, conversation_id, content, response
))
```

The exact wiring depends on what variables are in scope — read the ws.py file to find the right variable names for db, provider, conversation_id, the user's content, and the response.

**Step 5: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_auto_title.py -v`
Expected: All 4 tests PASS

**Step 6: Commit**

```bash
git add odigos/core/auto_title.py tests/test_auto_title.py odigos/api/ws.py
git commit -m "feat: auto-generate conversation titles after first exchange

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Evolution Dashboard Page (Frontend)

**Files:**
- Create: `dashboard/src/pages/EvolutionPage.tsx`
- Modify: `dashboard/src/App.tsx` (add route)
- Modify: `dashboard/src/layouts/AppLayout.tsx` (add nav link)

**Context:** This task creates the Evolution Dashboard page. It uses the API endpoints from Task 5 to show active trial status, evaluation history, direction log, and specialization proposals.

**Step 1: Create EvolutionPage.tsx**

```tsx
import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Activity, TrendingUp, TrendingDown, AlertTriangle, Lightbulb, RotateCcw, Check } from 'lucide-react'

interface Trial {
  id: string
  hypothesis: string
  target: string
  status: string
  started_at: string
  expires_at: string
  evaluation_count: number
  min_evaluations: number
  avg_score: number | null
  baseline_avg_score: number | null
}

interface Evaluation {
  id: string
  task_type: string
  overall_score: number
  implicit_feedback: number
  created_at: string
}

interface Direction {
  id: string
  analysis: string
  direction: string
  confidence: number
  created_at: string
}

interface FailedTrial {
  id: string
  hypothesis: string
  failure_reason: string
  lessons: string
  created_at: string
}

interface Proposal {
  id: string
  role: string
  specialty: string
  description: string
  rationale: string
  status: string
  created_at: string
}

export default function EvolutionPage() {
  const [activeTrial, setActiveTrial] = useState<Trial | null>(null)
  const [recentAvg, setRecentAvg] = useState<number | null>(null)
  const [evalCount, setEvalCount] = useState(0)
  const [evaluations, setEvaluations] = useState<Evaluation[]>([])
  const [directions, setDirections] = useState<Direction[]>([])
  const [failedTrials, setFailedTrials] = useState<FailedTrial[]>([])
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [showFailed, setShowFailed] = useState(false)

  const loadAll = useCallback(async () => {
    try {
      const [status, evals, dirs, failed, props] = await Promise.all([
        get<{ active_trial: Trial | null; recent_eval_count: number; recent_avg_score: number | null }>('/api/evolution/status'),
        get<{ evaluations: Evaluation[] }>('/api/evolution/evaluations?limit=20'),
        get<{ directions: Direction[] }>('/api/evolution/directions?limit=5'),
        get<{ failed_trials: FailedTrial[] }>('/api/evolution/failed-trials?limit=10'),
        get<{ proposals: Proposal[] }>('/api/proposals?status=pending'),
      ])
      setActiveTrial(status.active_trial)
      setRecentAvg(status.recent_avg_score)
      setEvalCount(status.recent_eval_count)
      setEvaluations(evals.evaluations)
      setDirections(dirs.directions)
      setFailedTrials(failed.failed_trials)
      setProposals(props.proposals)
    } catch {
      toast.error('Failed to load evolution data')
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  async function handlePromote(trialId: string) {
    try {
      await post(`/api/evolution/trial/${trialId}/promote`)
      toast.success('Trial promoted')
      loadAll()
    } catch { toast.error('Failed to promote trial') }
  }

  async function handleRevert(trialId: string) {
    try {
      await post(`/api/evolution/trial/${trialId}/revert`)
      toast.success('Trial reverted')
      loadAll()
    } catch { toast.error('Failed to revert trial') }
  }

  async function handleApproveProposal(id: string) {
    try {
      await post(`/api/proposals/${id}/approve`)
      toast.success('Proposal approved')
      loadAll()
    } catch { toast.error('Failed to approve proposal') }
  }

  async function handleDismissProposal(id: string) {
    try {
      await post(`/api/proposals/${id}/dismiss`)
      toast.success('Proposal dismissed')
      loadAll()
    } catch { toast.error('Failed to dismiss proposal') }
  }

  function scoreColor(score: number): string {
    if (score >= 8) return 'text-green-500'
    if (score >= 6) return 'text-yellow-500'
    return 'text-red-500'
  }

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-8">
        <h1 className="text-xl font-semibold">Evolution Engine</h1>

        {/* Overview stats */}
        <div className="grid grid-cols-3 gap-4">
          <div className="p-4 rounded-lg border border-border/40 bg-muted/30">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">Evaluations</div>
            <div className="text-2xl font-semibold mt-1">{evalCount}</div>
          </div>
          <div className="p-4 rounded-lg border border-border/40 bg-muted/30">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">Avg Score</div>
            <div className={`text-2xl font-semibold mt-1 ${recentAvg ? scoreColor(recentAvg) : ''}`}>
              {recentAvg ? recentAvg.toFixed(1) : '--'}
            </div>
          </div>
          <div className="p-4 rounded-lg border border-border/40 bg-muted/30">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">Trial Status</div>
            <div className="text-2xl font-semibold mt-1">
              {activeTrial ? 'Active' : 'None'}
            </div>
          </div>
        </div>

        {/* Active Trial */}
        {activeTrial && (
          <section className="p-4 rounded-lg border border-border/40 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium flex items-center gap-2">
                <Activity className="h-4 w-4" /> Active Trial
              </h2>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => handlePromote(activeTrial.id)}>
                  <Check className="h-3 w-3 mr-1" /> Promote
                </Button>
                <Button variant="outline" size="sm" onClick={() => handleRevert(activeTrial.id)}>
                  <RotateCcw className="h-3 w-3 mr-1" /> Revert
                </Button>
              </div>
            </div>
            <p className="text-sm">{activeTrial.hypothesis}</p>
            <div className="grid grid-cols-3 gap-4 text-xs text-muted-foreground">
              <div>Evaluations: {activeTrial.evaluation_count}/{activeTrial.min_evaluations}</div>
              <div>Score: {activeTrial.avg_score?.toFixed(1) ?? '--'} vs baseline {activeTrial.baseline_avg_score?.toFixed(1) ?? '--'}</div>
              <div>Expires: {new Date(activeTrial.expires_at).toLocaleString()}</div>
            </div>
          </section>
        )}

        {/* Specialization Proposals */}
        {proposals.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-sm font-medium flex items-center gap-2">
              <Lightbulb className="h-4 w-4" /> Specialization Proposals
            </h2>
            {proposals.map((p) => (
              <div key={p.id} className="p-4 rounded-lg border border-border/40 bg-muted/30">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium">{p.role} {p.specialty && `(${p.specialty})`}</div>
                    <div className="text-xs text-muted-foreground mt-1">{p.description}</div>
                    {p.rationale && <div className="text-xs text-muted-foreground mt-1">Rationale: {p.rationale}</div>}
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => handleApproveProposal(p.id)}>Approve</Button>
                    <Button variant="ghost" size="sm" onClick={() => handleDismissProposal(p.id)}>Dismiss</Button>
                  </div>
                </div>
              </div>
            ))}
          </section>
        )}

        {/* Direction Log */}
        {directions.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-sm font-medium flex items-center gap-2">
              <TrendingUp className="h-4 w-4" /> Direction Log
            </h2>
            {directions.map((d) => (
              <div key={d.id} className="p-3 rounded-lg border border-border/40 bg-muted/30 text-sm">
                <div>{d.direction}</div>
                <div className="text-xs text-muted-foreground mt-1">
                  {d.analysis} &middot; Confidence: {(d.confidence * 100).toFixed(0)}%
                </div>
              </div>
            ))}
          </section>
        )}

        {/* Evaluation History */}
        <section className="space-y-3">
          <h2 className="text-sm font-medium">Recent Evaluations</h2>
          <div className="rounded-lg border border-border/40 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="text-left px-3 py-2 text-xs text-muted-foreground font-medium">Type</th>
                  <th className="text-left px-3 py-2 text-xs text-muted-foreground font-medium">Score</th>
                  <th className="text-left px-3 py-2 text-xs text-muted-foreground font-medium">Feedback</th>
                  <th className="text-left px-3 py-2 text-xs text-muted-foreground font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {evaluations.map((e) => (
                  <tr key={e.id} className="border-t border-border/20">
                    <td className="px-3 py-2">{e.task_type || '--'}</td>
                    <td className={`px-3 py-2 font-medium ${scoreColor(e.overall_score)}`}>{e.overall_score?.toFixed(1)}</td>
                    <td className="px-3 py-2">
                      {e.implicit_feedback > 0 ? <TrendingUp className="h-3 w-3 text-green-500 inline" /> :
                       e.implicit_feedback < 0 ? <TrendingDown className="h-3 w-3 text-red-500 inline" /> :
                       <span className="text-muted-foreground">--</span>}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{new Date(e.created_at).toLocaleString()}</td>
                  </tr>
                ))}
                {evaluations.length === 0 && (
                  <tr><td colSpan={4} className="px-3 py-4 text-center text-muted-foreground">No evaluations yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Failed Trials (collapsed) */}
        {failedTrials.length > 0 && (
          <section className="space-y-3">
            <button
              onClick={() => setShowFailed(!showFailed)}
              className="text-sm font-medium flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
            >
              <AlertTriangle className="h-4 w-4" />
              Failed Trials ({failedTrials.length})
            </button>
            {showFailed && failedTrials.map((f) => (
              <div key={f.id} className="p-3 rounded-lg border border-border/40 bg-muted/30 text-sm">
                <div>{f.hypothesis}</div>
                <div className="text-xs text-muted-foreground mt-1">
                  {f.failure_reason} &middot; {f.lessons}
                </div>
              </div>
            ))}
          </section>
        )}
      </div>
    </div>
  )
}
```

**Step 2: Add route to App.tsx**

Find the route definitions and add:
```tsx
import EvolutionPage from '@/pages/EvolutionPage'

// In the routes:
<Route path="/evolution" element={<EvolutionPage />} />
```

**Step 3: Add nav link to AppLayout.tsx**

In the sidebar, add a link to `/evolution` alongside the Settings link. Use the `Activity` icon from lucide-react:

```tsx
<NavLink to="/evolution" className={...same pattern as Settings...}>
  <Activity className="h-4 w-4 shrink-0" />
  {!collapsed && 'Evolution'}
</NavLink>
```

**Step 4: Verify it builds**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npm run build`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add dashboard/src/pages/EvolutionPage.tsx dashboard/src/App.tsx dashboard/src/layouts/AppLayout.tsx
git commit -m "feat: add Evolution Dashboard page with trial controls and evaluation history

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Agent Registry API + Dashboard Page

**Files:**
- Create: `odigos/api/agents.py`
- Create: `dashboard/src/pages/AgentsPage.tsx`
- Modify: `dashboard/src/App.tsx` (add route)
- Modify: `dashboard/src/layouts/AppLayout.tsx` (add nav link)

**Step 1: Write the API**

Create `odigos/api/agents.py`:

```python
"""Agent registry API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from odigos.api.deps import get_db, require_api_key
from odigos.db import Database

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


@router.get("/agents")
async def list_agents(db: Database = Depends(get_db)):
    """List all registered agents."""
    rows = await db.fetch_all(
        "SELECT * FROM agent_registry ORDER BY agent_name"
    )
    return {"agents": [dict(r) for r in rows]}


@router.get("/agents/{agent_name}")
async def get_agent(agent_name: str, db: Database = Depends(get_db)):
    """Get details for a specific agent."""
    row = await db.fetch_one(
        "SELECT * FROM agent_registry WHERE agent_name = ?", (agent_name,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return dict(row)


@router.get("/agents/{agent_name}/messages")
async def get_agent_messages(
    agent_name: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: Database = Depends(get_db),
):
    """Get recent messages with a peer agent."""
    rows = await db.fetch_all(
        "SELECT * FROM peer_messages WHERE peer_name = ? ORDER BY created_at DESC LIMIT ?",
        (agent_name, limit),
    )
    return {"messages": [dict(r) for r in rows]}
```

**Step 2: Create AgentsPage.tsx**

```tsx
import { useState, useEffect, useCallback } from 'react'
import { get } from '@/lib/api'
import { toast } from 'sonner'
import { Users, Wifi, WifiOff, Clock } from 'lucide-react'

interface Agent {
  agent_name: string
  role: string
  description: string
  specialty: string | null
  status: string
  last_seen: string | null
  evolution_score: number | null
  netbird_ip: string
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([])

  const loadAgents = useCallback(async () => {
    try {
      const data = await get<{ agents: Agent[] }>('/api/agents')
      setAgents(data.agents)
    } catch {
      toast.error('Failed to load agents')
    }
  }, [])

  useEffect(() => { loadAgents() }, [loadAgents])

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-8">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Users className="h-5 w-5" /> Agent Network
          </h1>
        </div>

        {agents.length === 0 && (
          <div className="text-center py-16 text-muted-foreground">
            <Users className="h-8 w-8 mx-auto mb-3 opacity-50" />
            <p>No agents registered yet.</p>
            <p className="text-xs mt-1">Agents will appear here when they join the mesh.</p>
          </div>
        )}

        <div className="grid gap-4">
          {agents.map((a) => (
            <div key={a.agent_name} className="p-4 rounded-lg border border-border/40 bg-muted/30">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{a.agent_name}</span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">{a.role}</span>
                    {a.specialty && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">{a.specialty}</span>
                    )}
                  </div>
                  {a.description && <p className="text-sm text-muted-foreground mt-1">{a.description}</p>}
                </div>
                <div className="flex items-center gap-2">
                  {a.status === 'online' ? (
                    <Wifi className="h-4 w-4 text-green-500" />
                  ) : (
                    <WifiOff className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-xs text-muted-foreground">{a.status}</span>
                </div>
              </div>
              <div className="flex gap-6 mt-3 text-xs text-muted-foreground">
                {a.netbird_ip && <span>IP: {a.netbird_ip}</span>}
                {a.evolution_score !== null && <span>Score: {a.evolution_score.toFixed(1)}</span>}
                {a.last_seen && (
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {new Date(a.last_seen).toLocaleString()}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
```

**Step 3: Add route + nav**

Add to App.tsx:
```tsx
import AgentsPage from '@/pages/AgentsPage'
<Route path="/agents" element={<AgentsPage />} />
```

Add to AppLayout.tsx sidebar (between Evolution and Settings):
```tsx
<NavLink to="/agents" className={...}>
  <Users className="h-4 w-4 shrink-0" />
  {!collapsed && 'Agents'}
</NavLink>
```

**Step 4: Mount router in main.py**

```python
from odigos.api.agents import router as agents_router
app.include_router(agents_router)
```

**Step 5: Verify build**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npm run build`
Expected: Build succeeds

**Step 6: Commit**

```bash
git add odigos/api/agents.py dashboard/src/pages/AgentsPage.tsx dashboard/src/App.tsx dashboard/src/layouts/AppLayout.tsx odigos/main.py
git commit -m "feat: add Agent Network page and registry API endpoints

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 9: Send Auto-Title to Dashboard via WebSocket

**Files:**
- Modify: `odigos/api/ws.py` (send title update over WebSocket)
- Modify: `dashboard/src/pages/ChatPage.tsx` (handle title update message)

**Context:** When auto-title fires, the sidebar needs to update without a full page refresh. Send a WebSocket message with the new title so the frontend can update immediately.

**Step 1: Update ws.py**

After the `maybe_auto_title` call (from Task 6), also send a WebSocket message to the client:

```python
# After auto-title generates, send title update to client
async def _send_title_update(ws, db, conversation_id):
    try:
        conv = await db.fetch_one(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        )
        if conv and conv["title"]:
            await ws.send_json({
                "type": "title_updated",
                "conversation_id": conversation_id,
                "title": conv["title"],
            })
    except Exception:
        pass
```

Schedule it after the auto-title task completes.

**Step 2: Update ChatPage.tsx**

In the WebSocket message handler (the `ChatSocket` callback), add handling for `title_updated`:

```tsx
if (msg.type === 'title_updated' && msg.conversation_id && msg.title) {
  setConversationTitle(msg.title as string)
  refreshConversations()  // Refresh sidebar list
}
```

**Step 3: Verify build**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add odigos/api/ws.py dashboard/src/pages/ChatPage.tsx
git commit -m "feat: push auto-generated titles to dashboard via WebSocket

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 10: Full Test Suite + Verification

**Step 1: Run all Python tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Verify all imports**

Run: `cd /Users/jacob/Projects/odigos && python3 -c "from odigos.core.strategist import Strategist; from odigos.core.auto_title import generate_title; from odigos.api.evolution import router; from odigos.api.agents import router; print('All imports OK')"`
Expected: `All imports OK`

**Step 3: Verify dashboard builds**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npm run build`
Expected: Build succeeds

**Step 4: Verify migration chain**

Run: `cd /Users/jacob/Projects/odigos && python3 -c "import asyncio; from odigos.db import Database; asyncio.run(Database(':memory:', migrations_dir='migrations').initialize()); print('All migrations OK')"`
Expected: `All migrations OK`

**Step 5: Final commit if anything remains**

```bash
git status
# If clean: done
# If changes: git add + commit
```
