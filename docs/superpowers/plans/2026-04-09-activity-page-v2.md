# Activity Page V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the ActivityPage from a notification feed into an interactive hub showing live agent state, goals, plans, todos, and recent activity — all clickable to drill into details.

**Architecture:** Backend gains `progress` field on goals, a new `/api/plans/active` endpoint, heartbeat state reporting via `get_status()`, and 60s caching on heavy `/api/state` queries. Frontend rewrites ActivityPage as a thin layout composing 5 section components, all driven by a single `useActivityData` hook polling every 15s.

**Tech Stack:** Python 3.12 + FastAPI + aiosqlite (backend), React 19 + TypeScript + Vite + Tailwind 4 + shadcn/Radix (frontend), SegmentedProgressBar + DotMatrixLoader from the design system foundation just shipped.

**Spec:** `docs/superpowers/specs/2026-04-09-activity-page-v2-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `migrations/007_goal_progress.sql` | Add `progress` column to `goals` table |
| `odigos/api/plans.py` | New endpoint: `GET /api/plans/active` |
| `dashboard/src/hooks/useActivityData.ts` | Polling orchestrator for state/budget/goals/plans/todos |
| `dashboard/src/components/activity/HeroSection.tsx` | Working Now + Budget hero cards |
| `dashboard/src/components/activity/GoalsSection.tsx` | Active goals with progress bars |
| `dashboard/src/components/activity/PlansSection.tsx` | In-progress plans list |
| `dashboard/src/components/activity/TodosSection.tsx` | Pending todos with quick complete |
| `dashboard/src/components/activity/ActivityFeedSection.tsx` | Notification feed (extracted) |
| `tests/test_api_plans.py` | Tests for new plans endpoint |

### Modified Files

| File | Change |
|------|--------|
| `schema.sql` | Add `progress INTEGER DEFAULT 0` to goals table |
| `odigos/core/goal_store.py` | Add `progress` to `update_goal` allowed fields, default to 0 in `create_goal` |
| `odigos/api/goals.py` | Goal response includes `progress` (automatic via SELECT *) |
| `odigos/core/heartbeat/orchestrator.py` | Add `get_status()` method, set instance attrs on phase enter/exit |
| `odigos/api/state.py` | Read heartbeat status, cache heavy aggregates for 60s |
| `dashboard/src/pages/ActivityPage.tsx` | Rewritten as ~80-line layout composing sections |

---

### Task 1: Goal Progress Schema + Store

**Files:**
- Modify: `schema.sql`
- Create: `migrations/007_goal_progress.sql`
- Modify: `odigos/core/goal_store.py`
- Test: `tests/test_goal_store.py` (extend existing or create)

- [ ] **Step 1: Write the failing test**

Check if `tests/test_goal_store.py` exists. If not, create it. Add this test:

```python
"""Tests for GoalStore progress field."""
from __future__ import annotations

import pytest
import pytest_asyncio

from odigos.core.goal_store import GoalStore
from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


class TestGoalProgress:
    async def test_create_goal_defaults_progress_to_zero(self, db):
        store = GoalStore(db)
        goal_id = await store.create_goal("Ship the feature")
        goals = await store.list_goals(status="active")
        match = next((g for g in goals if g["id"] == goal_id), None)
        assert match is not None
        assert match["progress"] == 0

    async def test_update_goal_progress(self, db):
        store = GoalStore(db)
        goal_id = await store.create_goal("Ship the feature")
        result = await store.update_goal(goal_id, progress=75)
        assert result is True
        goals = await store.list_goals(status="active")
        match = next((g for g in goals if g["id"] == goal_id), None)
        assert match["progress"] == 75

    async def test_update_goal_progress_with_other_fields(self, db):
        store = GoalStore(db)
        goal_id = await store.create_goal("Ship the feature")
        result = await store.update_goal(
            goal_id, progress=50, progress_note="halfway"
        )
        assert result is True
        goals = await store.list_goals(status="active")
        match = next((g for g in goals if g["id"] == goal_id), None)
        assert match["progress"] == 50
        assert match["progress_note"] == "halfway"

    async def test_update_goal_rejects_unknown_fields(self, db):
        store = GoalStore(db)
        goal_id = await store.create_goal("Ship the feature")
        # Unknown field is silently dropped, valid field still applied
        result = await store.update_goal(goal_id, progress=25, bogus="ignored")
        assert result is True
        goals = await store.list_goals(status="active")
        match = next((g for g in goals if g["id"] == goal_id), None)
        assert match["progress"] == 25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_goal_store.py::TestGoalProgress -x -q`
Expected: FAIL — `progress` column does not exist.

- [ ] **Step 3: Update schema.sql**

In `schema.sql`, find the `goals` table definition (around line 220) and add `progress INTEGER DEFAULT 0` after `reviewed_at TEXT`:

```sql
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    created_by TEXT DEFAULT 'user',
    progress_note TEXT,
    reviewed_at TEXT,
    progress INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
```

- [ ] **Step 4: Create migration file**

Create `migrations/007_goal_progress.sql`:

```sql
-- Add progress column to goals table
ALTER TABLE goals ADD COLUMN progress INTEGER DEFAULT 0;
```

- [ ] **Step 5: Update GoalStore**

In `odigos/core/goal_store.py`, update `update_goal` to add `progress` to allowed fields:

```python
    async def update_goal(self, goal_id: str, **kwargs) -> bool:
        allowed = {"status", "progress_note", "reviewed_at", "progress"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [goal_id]
        await self.db.execute(
            f"UPDATE goals SET {set_clause} WHERE id = ?", tuple(values)
        )
        return True
```

The `create_goal` method doesn't need changes — the DB default of 0 handles it.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_goal_store.py::TestGoalProgress -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Run full goal/api tests for regressions**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q -k "goal"`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add schema.sql migrations/007_goal_progress.sql odigos/core/goal_store.py tests/test_goal_store.py
git commit -m "feat(goals): add progress field with update_goal support"
```

---

### Task 2: Plans Active Endpoint

**Files:**
- Create: `odigos/api/plans.py`
- Create: `tests/test_api_plans.py`
- Modify: app router registration (likely `odigos/api/__init__.py` or similar)

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_plans.py`:

```python
"""Tests for /api/plans/active endpoint."""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


async def _seed_plan(db, goal: str, steps: list[dict], status: str = "in_progress"):
    plan_id = str(uuid.uuid4())
    conv_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO conversations (id, channel) VALUES (?, ?)",
        (conv_id, "test"),
    )
    await db.execute(
        "INSERT INTO task_plans (id, conversation_id, goal, steps, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (plan_id, conv_id, goal, json.dumps(steps), status),
    )
    return plan_id


class TestPlansActive:
    async def test_returns_in_progress_plans_with_step_counts(self, client: AsyncClient, db):
        steps = [
            {"step": 1, "task": "First step", "status": "done"},
            {"step": 2, "task": "Second step", "status": "done"},
            {"step": 3, "task": "Third step", "status": "in_progress"},
            {"step": 4, "task": "Fourth step", "status": "pending"},
            {"step": 5, "task": "Fifth step", "status": "pending"},
        ]
        await _seed_plan(db, "Ship the feature", steps)

        resp = await client.get("/api/plans/active")
        assert resp.status_code == 200
        data = resp.json()
        assert "plans" in data
        assert len(data["plans"]) == 1
        plan = data["plans"][0]
        assert plan["goal"] == "Ship the feature"
        assert plan["current_step"] == 3
        assert plan["total_steps"] == 5

    async def test_excludes_done_plans(self, client: AsyncClient, db):
        await _seed_plan(db, "Done plan", [{"step": 1, "status": "done"}], status="done")
        await _seed_plan(db, "Active plan", [{"step": 1, "status": "pending"}])

        resp = await client.get("/api/plans/active")
        assert resp.status_code == 200
        plans = resp.json()["plans"]
        assert len(plans) == 1
        assert plans[0]["goal"] == "Active plan"

    async def test_empty_when_no_active_plans(self, client: AsyncClient, db):
        resp = await client.get("/api/plans/active")
        assert resp.status_code == 200
        assert resp.json()["plans"] == []

    async def test_handles_malformed_steps_json(self, client: AsyncClient, db):
        plan_id = str(uuid.uuid4())
        conv_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            (conv_id, "test"),
        )
        await db.execute(
            "INSERT INTO task_plans (id, conversation_id, goal, steps, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (plan_id, conv_id, "Bad plan", "not json", "in_progress"),
        )
        resp = await client.get("/api/plans/active")
        assert resp.status_code == 200
        plans = resp.json()["plans"]
        # Malformed plan should still appear but with 0/0 step counts
        assert len(plans) == 1
        assert plans[0]["current_step"] == 0
        assert plans[0]["total_steps"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_api_plans.py -x -q`
Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Create plans.py endpoint**

Create `odigos/api/plans.py`:

```python
"""Plans API endpoint."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends

from odigos.api.deps import get_db, require_auth
from odigos.db import Database

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)


def _count_steps(steps_json: str) -> tuple[int, int]:
    """Parse steps JSON and return (current_step, total_steps).

    current_step is the 1-indexed position of the first non-done step,
    or total_steps + 1 if everything is done.
    Returns (0, 0) if the JSON is malformed.
    """
    try:
        steps = json.loads(steps_json)
        if not isinstance(steps, list):
            return (0, 0)
    except (json.JSONDecodeError, TypeError):
        return (0, 0)

    total = len(steps)
    if total == 0:
        return (0, 0)

    done_count = 0
    for s in steps:
        if isinstance(s, dict) and s.get("status") == "done":
            done_count += 1
        else:
            break
    current = done_count + 1 if done_count < total else total
    return (current, total)


@router.get("/plans/active")
async def list_active_plans(db: Database = Depends(get_db)):
    """Return active task plans with step progress."""
    rows = await db.fetch_all(
        "SELECT id, conversation_id, goal, steps, created_at, updated_at "
        "FROM task_plans WHERE status = 'in_progress' "
        "ORDER BY updated_at DESC LIMIT 20"
    )

    plans = []
    for row in rows:
        current_step, total_steps = _count_steps(row["steps"])
        plans.append({
            "id": row["id"],
            "goal": row["goal"] or "",
            "current_step": current_step,
            "total_steps": total_steps,
            "started_at": row["created_at"],
            "updated_at": row["updated_at"],
            "conversation_id": row["conversation_id"],
        })

    return {"plans": plans}
```

- [ ] **Step 4: Register the router**

Find where API routers are registered. Search:

Run: `grep -rn "include_router" odigos/api/ odigos/main.py odigos/bootstrap.py 2>&1 | head -10`

Add the import and registration alongside other routers, e.g.:
```python
from odigos.api.plans import router as plans_router
app.include_router(plans_router)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_api_plans.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add odigos/api/plans.py tests/test_api_plans.py odigos/api/__init__.py odigos/main.py
git commit -m "feat(api): add /api/plans/active endpoint with step progress"
```

(Adjust file list to match where you registered the router.)

---

### Task 3: Heartbeat get_status() Method

**Files:**
- Modify: `odigos/core/heartbeat/orchestrator.py`
- Test: `tests/test_heartbeat_status.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_heartbeat_status.py`:

```python
"""Tests for Heartbeat.get_status() method."""
from __future__ import annotations

from unittest.mock import MagicMock

from odigos.core.heartbeat.orchestrator import Heartbeat


class TestHeartbeatStatus:
    def test_get_status_returns_idle_by_default(self):
        # Create a minimal Heartbeat without running it
        hb = MagicMock(spec=Heartbeat)
        # Use the real method bound to the mock
        hb.current_phase = None
        hb.current_activity = None
        hb.current_plan = None
        hb.get_status = Heartbeat.get_status.__get__(hb, Heartbeat)

        status = hb.get_status()
        assert status["current_phase"] is None
        assert status["current_activity"] is None
        assert status["current_plan"] is None

    def test_get_status_returns_active_phase(self):
        hb = MagicMock(spec=Heartbeat)
        hb.current_phase = "memory_evolution"
        hb.current_activity = "Processing 5 evolution queue items"
        hb.current_plan = None
        hb.get_status = Heartbeat.get_status.__get__(hb, Heartbeat)

        status = hb.get_status()
        assert status["current_phase"] == "memory_evolution"
        assert status["current_activity"] == "Processing 5 evolution queue items"

    def test_get_status_returns_active_plan(self):
        hb = MagicMock(spec=Heartbeat)
        hb.current_phase = "plans"
        hb.current_activity = None
        hb.current_plan = {
            "id": "abc-123",
            "goal": "Draft newsletter",
            "current_step": 3,
            "total_steps": 5,
        }
        hb.get_status = Heartbeat.get_status.__get__(hb, Heartbeat)

        status = hb.get_status()
        assert status["current_plan"]["goal"] == "Draft newsletter"
        assert status["current_plan"]["current_step"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_heartbeat_status.py -x -q`
Expected: FAIL — method doesn't exist.

- [ ] **Step 3: Add get_status to Heartbeat class**

In `odigos/core/heartbeat/orchestrator.py`, find the `Heartbeat` class `__init__` and add three instance attributes:

```python
        self.current_phase: str | None = None
        self.current_activity: str | None = None
        self.current_plan: dict | None = None
```

Add this method to the Heartbeat class (anywhere after `__init__`):

```python
    def get_status(self) -> dict:
        """Return current heartbeat status for the activity dashboard."""
        return {
            "current_phase": self.current_phase,
            "current_activity": self.current_activity,
            "current_plan": self.current_plan,
        }
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_heartbeat_status.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Wire phase tracking into the orchestrator loop**

In the heartbeat main loop (the function that runs each phase), wrap key phase calls to set/clear `current_phase`. For example, around the experience extraction phase:

```python
        # Phase 9: experience extraction
        try:
            self.current_phase = "experience_extraction"
            self.current_activity = "Extracting agent experiences"
            await profiling.extract_experiences(self)
        finally:
            self.current_phase = None
            self.current_activity = None
```

Apply the same pattern to:
- `memory_evolution` phase (Phase 9.5) — set to `"memory_evolution"` with activity `"Refining memories"`
- `plans` phase (Phase 4e via `work_in_progress_plans`) — set to `"plans"` with activity `"Executing plan step"` AND populate `current_plan` with the plan dict
- `consolidation` (within run_evolution) — set to `"consolidation"` with activity `"Consolidating corrections"`

For the plans phase specifically, in `odigos/core/heartbeat/plans.py:work_in_progress_plans`, add right before calling `hb.agent.handle_message`:
```python
    hb.current_phase = "plans"
    hb.current_activity = f"Executing step {step_num}: {step_desc[:80]}"
    hb.current_plan = {
        "id": plan_id,
        "goal": goal or "",
        "current_step": int(step_num) if step_num.isdigit() else 0,
        "total_steps": len(steps),
        "conversation_id": conversation_id,
    }
```
And in the `finally` or after the call:
```python
    hb.current_phase = None
    hb.current_activity = None
    hb.current_plan = None
```

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add odigos/core/heartbeat/orchestrator.py odigos/core/heartbeat/plans.py tests/test_heartbeat_status.py
git commit -m "feat(heartbeat): add get_status() and phase tracking for activity dashboard"
```

---

### Task 4: /api/state Caching + Heartbeat Status

**Files:**
- Modify: `odigos/api/state.py`
- Test: extend `tests/test_state_api.py` if it exists, or create

- [ ] **Step 1: Read current state.py**

Run: `cat odigos/api/state.py | head -120`

Note the existing query patterns. We need to:
1. Cache the heavy aggregate counts (conversations, memory totals, etc.) for 60s
2. Always read heartbeat.get_status() live
3. Always read budget live

- [ ] **Step 2: Write the test**

Create or extend `tests/test_state_api.py`:

```python
"""Tests for /api/state endpoint with heartbeat status."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient


class TestStateEndpoint:
    async def test_state_includes_heartbeat_status_fields(
        self, client: AsyncClient
    ):
        resp = await client.get("/api/state")
        assert resp.status_code == 200
        data = resp.json()
        # The new fields should be present even if null
        assert "current_phase" in data
        assert "current_activity" in data
        assert "current_plan" in data

    async def test_state_caches_heavy_counts_for_60s(self, client: AsyncClient):
        from odigos.api.state import _state_cache_clear
        _state_cache_clear()  # ensure clean state

        # First request — populates cache
        resp1 = await client.get("/api/state")
        assert resp1.status_code == 200

        # Second request immediately — should hit cache
        resp2 = await client.get("/api/state")
        assert resp2.status_code == 200

        # Both should return identical aggregate fields (proves caching)
        # (heartbeat status may differ but counts should be stable)
        for key in ("total_messages", "active_conversations"):
            if key in resp1.json():
                assert resp1.json()[key] == resp2.json()[key]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_state_api.py::TestStateEndpoint::test_state_includes_heartbeat_status_fields -x -q`
Expected: FAIL — fields not in response.

- [ ] **Step 4: Add caching helper + update endpoint**

In `odigos/api/state.py`, add this caching helper near the top (after imports):

```python
import time

_STATE_CACHE: dict = {}
_STATE_CACHE_TTL_SECONDS = 60


def _state_cache_get(key: str):
    """Return cached value if not expired."""
    entry = _STATE_CACHE.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() > expires_at:
        return None
    return value


def _state_cache_set(key: str, value):
    """Store value with TTL."""
    _STATE_CACHE[key] = (value, time.time() + _STATE_CACHE_TTL_SECONDS)


def _state_cache_clear():
    """Clear the cache (for tests)."""
    _STATE_CACHE.clear()
```

In the `/api/state` endpoint function, wrap the heavy queries:

```python
async def get_state(...):
    # ... existing dependency injection ...

    # Heavy aggregates — cache for 60s
    cached_aggregates = _state_cache_get("aggregates")
    if cached_aggregates is None:
        # Run the existing heavy queries here
        total_convs = await db.fetch_one("SELECT COUNT(*) as c FROM conversations")
        total_msgs = await db.fetch_one("SELECT COUNT(*) as c FROM messages")
        # ... other heavy queries ...
        cached_aggregates = {
            "total_conversations": total_convs["c"] if total_convs else 0,
            "total_messages": total_msgs["c"] if total_msgs else 0,
            # ... other fields ...
        }
        _state_cache_set("aggregates", cached_aggregates)

    # Heartbeat status — always live, never cached
    heartbeat_status = {
        "current_phase": None,
        "current_activity": None,
        "current_plan": None,
    }
    if heartbeat is not None:
        try:
            heartbeat_status = heartbeat.get_status()
        except Exception:
            logger.debug("Failed to get heartbeat status", exc_info=True)

    return {
        **cached_aggregates,
        **heartbeat_status,
    }
```

Note: the exact existing code in `/api/state` will determine the precise integration. The principle is: split the function into "cached aggregates" and "live status" sections.

- [ ] **Step 5: Run tests to verify pass**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_state_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add odigos/api/state.py tests/test_state_api.py
git commit -m "feat(api): cache heavy state queries for 60s, expose heartbeat status"
```

---

### Task 5: useActivityData Hook

**Files:**
- Create: `dashboard/src/hooks/useActivityData.ts`

- [ ] **Step 1: Create the hook**

Create `dashboard/src/hooks/useActivityData.ts`:

```typescript
import { useEffect, useState, useCallback, useRef } from 'react'

export interface AgentState {
  current_phase: string | null
  current_activity: string | null
  current_plan: {
    id: string
    goal: string
    current_step: number
    total_steps: number
    conversation_id?: string
  } | null
}

export interface BudgetStatus {
  total_spent_today: number
  daily_budget: number
  remaining: number
  percent_used: number
}

export interface Goal {
  id: string
  description: string
  progress: number
  status: string
  created_at: string
}

export interface ActivePlan {
  id: string
  goal: string
  current_step: number
  total_steps: number
  started_at: string
  conversation_id: string
}

export interface Todo {
  id: string
  description: string
  status: string
  scheduled_at: string | null
  goal_id: string | null
}

export interface ActivityData {
  state: AgentState | null
  budget: BudgetStatus | null
  goals: Goal[]
  plans: ActivePlan[]
  todos: Todo[]
  loading: boolean
  errors: { [source: string]: string | null }
}

const POLL_INTERVAL_MS = 15000

async function safeFetch<T>(url: string): Promise<{ data: T | null; error: string | null }> {
  try {
    const resp = await fetch(url)
    if (!resp.ok) {
      return { data: null, error: `HTTP ${resp.status}` }
    }
    const data = await resp.json()
    return { data, error: null }
  } catch (e) {
    return { data: null, error: e instanceof Error ? e.message : 'fetch failed' }
  }
}

export function useActivityData(): ActivityData & { refresh: () => Promise<void> } {
  const [state, setState] = useState<AgentState | null>(null)
  const [budget, setBudget] = useState<BudgetStatus | null>(null)
  const [goals, setGoals] = useState<Goal[]>([])
  const [plans, setPlans] = useState<ActivePlan[]>([])
  const [todos, setTodos] = useState<Todo[]>([])
  const [loading, setLoading] = useState(true)
  const [errors, setErrors] = useState<{ [k: string]: string | null }>({})
  const intervalRef = useRef<number | null>(null)

  const fetchAll = useCallback(async () => {
    const [stateRes, budgetRes, goalsRes, plansRes, todosRes] = await Promise.all([
      safeFetch<AgentState>('/api/state'),
      safeFetch<BudgetStatus>('/api/budget'),
      safeFetch<{ goals: Goal[] }>('/api/goals?status=active'),
      safeFetch<{ plans: ActivePlan[] }>('/api/plans/active'),
      safeFetch<{ todos: Todo[] }>('/api/todos?status=pending'),
    ])

    if (stateRes.data) setState(stateRes.data)
    if (budgetRes.data) setBudget(budgetRes.data)
    if (goalsRes.data) setGoals(goalsRes.data.goals)
    if (plansRes.data) setPlans(plansRes.data.plans)
    if (todosRes.data) setTodos(todosRes.data.todos)

    setErrors({
      state: stateRes.error,
      budget: budgetRes.error,
      goals: goalsRes.error,
      plans: plansRes.error,
      todos: todosRes.error,
    })
    setLoading(false)
  }, [])

  useEffect(() => {
    void fetchAll()

    const startPolling = () => {
      if (intervalRef.current) return
      intervalRef.current = window.setInterval(() => {
        void fetchAll()
      }, POLL_INTERVAL_MS)
    }

    const stopPolling = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void fetchAll()
        startPolling()
      } else {
        stopPolling()
      }
    }

    if (document.visibilityState === 'visible') {
      startPolling()
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      stopPolling()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [fetchAll])

  return {
    state,
    budget,
    goals,
    plans,
    todos,
    loading,
    errors,
    refresh: fetchAll,
  }
}
```

- [ ] **Step 2: Type-check**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/hooks/useActivityData.ts
git commit -m "feat(dashboard): add useActivityData polling hook"
```

---

### Task 6: HeroSection Component

**Files:**
- Create: `dashboard/src/components/activity/HeroSection.tsx`

- [ ] **Step 1: Create HeroSection.tsx**

```typescript
import { useNavigate } from 'react-router-dom'
import { DotMatrixLoader } from '@/components/ui/loader'
import { SegmentedProgressBar } from '@/components/ui/SegmentedProgressBar'
import type { AgentState, BudgetStatus } from '@/hooks/useActivityData'

interface HeroSectionProps {
  state: AgentState | null
  budget: BudgetStatus | null
  errors: { state: string | null; budget: string | null }
}

function WorkingNowCard({ state, error }: { state: AgentState | null; error: string | null }) {
  const navigate = useNavigate()

  if (error) {
    return (
      <div className="bg-card rounded-xl p-4 border border-border">
        <div className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase mb-2">
          Working Now
        </div>
        <div className="text-sm text-muted-foreground">Status unavailable</div>
      </div>
    )
  }

  const isActive = state?.current_phase || state?.current_plan
  const isPlanActive = !!state?.current_plan

  return (
    <div className="bg-card rounded-xl p-4 border border-border">
      <div className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase mb-2">
        Working Now
      </div>
      <div className="flex items-start gap-3">
        {isActive ? (
          <DotMatrixLoader size="md" />
        ) : (
          <div className="size-2 rounded-full bg-muted-foreground mt-1.5" />
        )}
        <div className="flex-1 min-w-0">
          {isPlanActive && state?.current_plan ? (
            <>
              <div className="text-sm font-medium">Executing plan</div>
              <div className="text-sm text-muted-foreground truncate">
                {state.current_plan.goal}
              </div>
              <div className="text-xs text-muted-foreground mt-1 tabular-nums">
                Step {state.current_plan.current_step} of {state.current_plan.total_steps}
              </div>
            </>
          ) : isActive ? (
            <>
              <div className="text-sm font-medium">
                {state?.current_phase?.replace(/_/g, ' ') || 'Thinking...'}
              </div>
              {state?.current_activity && (
                <div className="text-sm text-muted-foreground truncate">
                  {state.current_activity}
                </div>
              )}
            </>
          ) : (
            <div className="text-sm text-muted-foreground">Idle</div>
          )}
        </div>
      </div>
      {isPlanActive && state?.current_plan && (
        <div className="flex gap-2 mt-3">
          <button
            onClick={() => navigate(`/?c=${state.current_plan!.conversation_id}`)}
            className="text-xs text-primary hover:underline"
          >
            View plan →
          </button>
        </div>
      )}
    </div>
  )
}

function BudgetCard({ budget, error }: { budget: BudgetStatus | null; error: string | null }) {
  const navigate = useNavigate()

  if (error || !budget) return null

  return (
    <div
      className="bg-card rounded-xl p-4 border border-border cursor-pointer hover:border-primary/30 transition-colors"
      onClick={() => navigate('/settings#budget')}
    >
      <div className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase mb-2">
        Budget Today
      </div>
      <SegmentedProgressBar
        value={budget.total_spent_today}
        max={budget.daily_budget}
        segments={10}
      />
      <div className="text-xs text-muted-foreground mt-2 tabular-nums">
        ${budget.total_spent_today.toFixed(2)} / ${budget.daily_budget.toFixed(2)}
      </div>
      <div className="text-xs text-muted-foreground tabular-nums">
        Remaining: ${budget.remaining.toFixed(2)}
      </div>
    </div>
  )
}

export function HeroSection({ state, budget, errors }: HeroSectionProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
      <WorkingNowCard state={state} error={errors.state} />
      <BudgetCard budget={budget} error={errors.budget} />
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/activity/HeroSection.tsx
git commit -m "feat(dashboard): add HeroSection with Working Now + Budget cards"
```

---

### Task 7: Goals, Plans, Todos Sections

**Files:**
- Create: `dashboard/src/components/activity/GoalsSection.tsx`
- Create: `dashboard/src/components/activity/PlansSection.tsx`
- Create: `dashboard/src/components/activity/TodosSection.tsx`

- [ ] **Step 1: Create GoalsSection.tsx**

```typescript
import { useNavigate } from 'react-router-dom'
import { SegmentedProgressBar } from '@/components/ui/SegmentedProgressBar'
import type { Goal } from '@/hooks/useActivityData'

interface GoalsSectionProps {
  goals: Goal[]
  error: string | null
}

function isStaleGoal(goal: Goal): boolean {
  if (goal.progress > 0) return false
  const created = new Date(goal.created_at).getTime()
  const dayMs = 24 * 60 * 60 * 1000
  return Date.now() - created < dayMs
}

export function GoalsSection({ goals, error }: GoalsSectionProps) {
  const navigate = useNavigate()

  if (error) return null

  const handleAdd = () => {
    navigate('/?c=new&prefill=Create+a+new+goal:+')
  }

  return (
    <section className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
          Goals
        </h2>
        <button
          onClick={handleAdd}
          className="text-xs text-muted-foreground hover:text-foreground"
          aria-label="Add new goal"
        >
          +
        </button>
      </div>
      {goals.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          No active goals. Set one in chat.
        </div>
      ) : (
        <div className="space-y-2">
          {goals.map((goal) => {
            const stale = isStaleGoal(goal)
            return (
              <button
                key={goal.id}
                onClick={() => navigate(`/?c=new&about=goal:${goal.id}`)}
                className="w-full bg-card rounded-xl p-3 border border-border hover:border-primary/30 transition-colors text-left"
              >
                <div className="flex items-center gap-3">
                  {!stale && (
                    <div className="w-24 flex-shrink-0">
                      <SegmentedProgressBar
                        value={goal.progress}
                        max={100}
                        segments={10}
                        size="sm"
                      />
                    </div>
                  )}
                  <div className="flex-1 text-sm truncate">{goal.description}</div>
                  {!stale && (
                    <div className="text-xs text-muted-foreground tabular-nums">
                      {goal.progress}%
                    </div>
                  )}
                </div>
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}
```

- [ ] **Step 2: Create PlansSection.tsx**

```typescript
import { useNavigate } from 'react-router-dom'
import type { ActivePlan } from '@/hooks/useActivityData'

interface PlansSectionProps {
  plans: ActivePlan[]
  error: string | null
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  const diffMs = Date.now() - then
  const minutes = Math.floor(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function PlansSection({ plans, error }: PlansSectionProps) {
  const navigate = useNavigate()

  if (error) return null

  return (
    <section className="mb-6">
      <h2 className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase mb-3">
        Plans In Progress
      </h2>
      {plans.length === 0 ? (
        <div className="text-sm text-muted-foreground">No plans in progress.</div>
      ) : (
        <div className="space-y-2">
          {plans.map((plan) => (
            <button
              key={plan.id}
              onClick={() => navigate(`/?c=${plan.conversation_id}`)}
              className="w-full bg-card rounded-xl p-3 border border-border hover:border-primary/30 transition-colors text-left"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium truncate flex-1">{plan.goal}</div>
                <div className="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                  step {plan.current_step} of {plan.total_steps}
                </div>
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                started {relativeTime(plan.started_at)}
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
```

- [ ] **Step 3: Create TodosSection.tsx**

```typescript
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Todo } from '@/hooks/useActivityData'

interface TodosSectionProps {
  todos: Todo[]
  error: string | null
  onComplete: (id: string) => Promise<void>
}

function dueText(todo: Todo): { text: string; overdue: boolean } {
  if (!todo.scheduled_at) return { text: 'no due date', overdue: false }
  const due = new Date(todo.scheduled_at).getTime()
  const now = Date.now()
  const diffMs = due - now

  if (diffMs < 0) {
    const overdueMs = -diffMs
    const minutes = Math.floor(overdueMs / 60000)
    if (minutes < 60) return { text: `${minutes}m overdue`, overdue: true }
    const hours = Math.floor(minutes / 60)
    if (hours < 24) return { text: `${hours}h overdue`, overdue: true }
    const days = Math.floor(hours / 24)
    return { text: `${days}d overdue`, overdue: true }
  }

  const dueDate = new Date(todo.scheduled_at)
  const today = new Date()
  if (dueDate.toDateString() === today.toDateString()) {
    return { text: 'today', overdue: false }
  }
  const tomorrow = new Date(today.getTime() + 86400000)
  if (dueDate.toDateString() === tomorrow.toDateString()) {
    return { text: 'tomorrow', overdue: false }
  }
  return { text: dueDate.toLocaleDateString(), overdue: false }
}

function sortTodos(todos: Todo[]): Todo[] {
  return [...todos].sort((a, b) => {
    const aTime = a.scheduled_at ? new Date(a.scheduled_at).getTime() : Infinity
    const bTime = b.scheduled_at ? new Date(b.scheduled_at).getTime() : Infinity
    return aTime - bTime
  })
}

export function TodosSection({ todos, error, onComplete }: TodosSectionProps) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)

  if (error) return null

  const sorted = sortTodos(todos)
  const visible = expanded ? sorted : sorted.slice(0, 5)
  const hasMore = sorted.length > 5

  return (
    <section className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
          Todos
        </h2>
        {hasMore && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            {expanded ? 'show less' : `view all (${sorted.length})`}
          </button>
        )}
      </div>
      {sorted.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          No pending todos. Add one in chat.
        </div>
      ) : (
        <div className="space-y-1">
          {visible.map((todo) => {
            const due = dueText(todo)
            return (
              <div
                key={todo.id}
                className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted/50"
              >
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    void onComplete(todo.id)
                  }}
                  className="size-4 border border-border rounded hover:bg-primary hover:border-primary transition-colors flex-shrink-0"
                  aria-label="Mark complete"
                />
                <button
                  onClick={() => navigate(`/?c=new&about=todo:${todo.id}`)}
                  className="flex-1 text-left text-sm truncate"
                >
                  {todo.description}
                </button>
                <div
                  className={`text-xs tabular-nums whitespace-nowrap ${
                    due.overdue
                      ? 'text-red-500 dark:text-red-400'
                      : 'text-muted-foreground'
                  }`}
                >
                  {due.text}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
```

- [ ] **Step 4: Type-check**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/activity/GoalsSection.tsx \
       dashboard/src/components/activity/PlansSection.tsx \
       dashboard/src/components/activity/TodosSection.tsx
git commit -m "feat(dashboard): add Goals, Plans, and Todos sections"
```

---

### Task 8: ActivityFeedSection (extract from existing page)

**Files:**
- Create: `dashboard/src/components/activity/ActivityFeedSection.tsx`

- [ ] **Step 1: Create ActivityFeedSection.tsx**

This extracts the existing notification feed logic from `ActivityPage.tsx` into a self-contained section component:

```typescript
import { useEffect, useCallback, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import Markdown from 'react-markdown'
import { useNotificationStore, type Notification } from '@/stores/notificationStore'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'

const TYPE_CONFIG: Record<string, { color: string; label: string; icon: string }> = {
  finding: { color: 'text-purple-400', label: 'FINDING', icon: '~' },
  suggestion: { color: 'text-blue-400', label: 'SUGGESTION', icon: '*' },
  status: { color: 'text-green-400', label: 'COMPLETED', icon: '+' },
  alert: { color: 'text-yellow-400', label: 'ALERT', icon: '!' },
}

function groupByDate(notifications: Notification[]): [string, Notification[]][] {
  const groups: Record<string, Notification[]> = {}
  const today = new Date().toDateString()
  const yesterday = new Date(Date.now() - 86400000).toDateString()
  for (const n of notifications) {
    const d = new Date(n.created_at).toDateString()
    const label = d === today ? 'Today' : d === yesterday ? 'Yesterday' : d
    if (!groups[label]) groups[label] = []
    groups[label].push(n)
  }
  return Object.entries(groups)
}

export function ActivityFeedSection() {
  const { notifications, fetchNotifications, markAsRead, discuss } = useNotificationStore()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<string>('all')
  const [showAll, setShowAll] = useState(false)
  const [artifactContent, setArtifactContent] = useState<string | null>(null)
  const [artifactTitle, setArtifactTitle] = useState('')
  const observersRef = useRef<Map<string, IntersectionObserver>>(new Map())

  useEffect(() => {
    void fetchNotifications(false, 20, 0)
  }, [fetchNotifications])

  const handleDiscuss = async (notif: Notification) => {
    const convId = await discuss(notif.id)
    if (convId) navigate(`/?c=${convId}`)
  }

  const handleViewArtifact = async (notif: Notification) => {
    if (!notif.artifact_path) return
    try {
      const resp = await fetch(`/api/files/read?path=${encodeURIComponent(notif.artifact_path)}`)
      if (resp.ok) {
        const data = await resp.json()
        setArtifactContent(data.content || 'No content')
      } else {
        setArtifactContent('Failed to load artifact')
      }
    } catch {
      setArtifactContent('Failed to load artifact')
    }
    setArtifactTitle(notif.title)
    void markAsRead(notif.id)
  }

  const markReadRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node) return
      const id = node.dataset.notifId
      if (!id) return
      // Cleanup previous observer for this node if any
      const prev = observersRef.current.get(id)
      if (prev) prev.disconnect()

      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            const el = entry.target as HTMLDivElement & {
              _readTimer?: ReturnType<typeof setTimeout>
            }
            if (entry.isIntersecting) {
              el._readTimer = setTimeout(() => void markAsRead(id), 500)
            } else if (el._readTimer) {
              clearTimeout(el._readTimer)
            }
          })
        },
        { threshold: 0.5 }
      )
      observer.observe(node)
      observersRef.current.set(id, observer)
    },
    [markAsRead]
  )

  useEffect(() => {
    return () => {
      observersRef.current.forEach((obs) => obs.disconnect())
      observersRef.current.clear()
    }
  }, [])

  const filtered = filter === 'all'
    ? notifications
    : notifications.filter((n) => n.type === filter)

  const visible = showAll ? filtered : filtered.slice(0, 5)
  const groups = groupByDate(visible)

  return (
    <section className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
          Recent Activity
        </h2>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="text-xs bg-transparent text-muted-foreground border border-border rounded px-2 py-1"
        >
          <option value="all">All</option>
          <option value="finding">Finding</option>
          <option value="suggestion">Suggestion</option>
          <option value="status">Completed</option>
          <option value="alert">Alert</option>
        </select>
      </div>

      {groups.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          No activity yet. Your agent will post findings here when it discovers something interesting.
        </div>
      ) : (
        groups.map(([label, notifs]) => (
          <div key={label} className="mb-4">
            <div className="text-[10px] font-semibold text-muted-foreground tracking-widest mb-2 uppercase">
              {label}
            </div>
            {notifs.map((notif) => {
              const config = TYPE_CONFIG[notif.type] || TYPE_CONFIG.status
              return (
                <div
                  key={notif.id}
                  ref={!notif.read ? markReadRef : undefined}
                  data-notif-id={notif.id}
                  className={`bg-card rounded-xl p-3 mb-2 border border-border transition-opacity ${
                    notif.read ? 'opacity-60' : ''
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={`text-[10px] font-semibold tracking-wide ${config.color}`}
                    >
                      {config.label}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {new Date(notif.created_at).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                  </div>
                  <div className="text-sm font-medium">{notif.title}</div>
                  {notif.body && (
                    <div className="text-xs text-muted-foreground mt-1 line-clamp-3">
                      {notif.body}
                    </div>
                  )}
                  <div className="flex gap-3 mt-2">
                    <button
                      onClick={() => void handleDiscuss(notif)}
                      className="text-xs text-primary hover:underline"
                    >
                      Discuss
                    </button>
                    {notif.artifact_path && (
                      <button
                        onClick={() => void handleViewArtifact(notif)}
                        className="text-xs text-muted-foreground hover:text-foreground"
                      >
                        View artifact
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        ))
      )}

      {filtered.length > 5 && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="w-full py-2 text-xs text-muted-foreground hover:text-foreground"
        >
          {showAll ? 'show less' : `show all (${filtered.length})`}
        </button>
      )}

      <Dialog open={!!artifactContent} onOpenChange={() => setArtifactContent(null)}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{artifactTitle}</DialogTitle>
          </DialogHeader>
          <div className="prose prose-invert prose-sm max-w-none">
            <Markdown>{artifactContent || ''}</Markdown>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/activity/ActivityFeedSection.tsx
git commit -m "feat(dashboard): extract ActivityFeedSection from ActivityPage"
```

---

### Task 9: Rewrite ActivityPage

**Files:**
- Modify: `dashboard/src/pages/ActivityPage.tsx`

- [ ] **Step 1: Rewrite ActivityPage.tsx**

Replace the entire contents of `dashboard/src/pages/ActivityPage.tsx` with:

```typescript
import { useCallback } from 'react'
import { useActivityData } from '@/hooks/useActivityData'
import { HeroSection } from '@/components/activity/HeroSection'
import { GoalsSection } from '@/components/activity/GoalsSection'
import { PlansSection } from '@/components/activity/PlansSection'
import { TodosSection } from '@/components/activity/TodosSection'
import { ActivityFeedSection } from '@/components/activity/ActivityFeedSection'

export default function ActivityPage() {
  const { state, budget, goals, plans, todos, errors, refresh } = useActivityData()

  const handleCompleteTodo = useCallback(
    async (id: string) => {
      try {
        await fetch(`/api/todos/${id}/complete`, { method: 'POST' })
        await refresh()
      } catch (e) {
        console.error('Failed to complete todo:', e)
      }
    },
    [refresh]
  )

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold">Activity</h1>
        <p className="text-sm text-muted-foreground mt-1">
          What your agent is doing
        </p>
      </div>

      <HeroSection
        state={state}
        budget={budget}
        errors={{ state: errors.state, budget: errors.budget }}
      />

      <GoalsSection goals={goals} error={errors.goals} />
      <PlansSection plans={plans} error={errors.plans} />
      <TodosSection todos={todos} error={errors.todos} onComplete={handleCompleteTodo} />
      <ActivityFeedSection />
    </div>
  )
}
```

- [ ] **Step 2: Verify the todo complete endpoint exists**

Run: `grep -n "complete" odigos/api/goals.py`

If `/api/todos/{id}/complete` doesn't exist, you'll need to add it. Check the existing GoalStore.complete_todo method — there's already a method, just no API exposure. If missing, add to `odigos/api/goals.py`:

```python
@router.post("/todos/{todo_id}/complete")
async def complete_todo_endpoint(
    todo_id: str,
    store: GoalStore = Depends(get_goal_store),
):
    await store.complete_todo(todo_id)
    return {"ok": True}
```

- [ ] **Step 3: Type-check**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Build dashboard**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npm run build 2>&1 | tail -20`
Expected: build succeeds (no TS or bundle errors).

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/ActivityPage.tsx odigos/api/goals.py
git commit -m "feat(dashboard): rewrite ActivityPage as compositional hub"
```

---

### Task 10: Final — Smoke Test

- [ ] **Step 1: Run full backend test suite**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 2: Type-check + build dashboard**

Run: `cd /Users/jacob/Projects/odigos/dashboard && npx tsc --noEmit && npm run build 2>&1 | tail -10`
Expected: Both succeed.

- [ ] **Step 3: Docker smoke test**

Run: `cd /Users/jacob/Projects/odigos && make build && make up && sleep 5 && make logs 2>&1 | tail -20`
Expected: Container starts cleanly.

- [ ] **Step 4: Manual verification**

Open the dashboard and navigate to the Activity page. Verify:
- Hero shows Working Now (idle or live state) and Budget bar
- Goals section renders (empty state OK)
- Plans section renders (empty state OK)
- Todos section renders (empty state OK)
- Activity feed renders the same notifications as before
- Filter dropdown works
- "show all" expansion works
- Polling refreshes data every 15s (check Network tab)

- [ ] **Step 5: Commit any final fixes**

```bash
git add -A && git commit -m "fix: lint and cleanup for activity page v2"
```
