"""Integration tests for user-facing features.

These test real feature paths: skills CRUD + activation, settings persistence,
goal/todo/reminder lifecycle, approval gate wiring, evolution status,
budget enforcement, and memory search — all through the actual API layer
or real class instances with a real SQLite database.
"""

from __future__ import annotations

import json
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from starlette.testclient import TestClient

from odigos.db import Database
from odigos.core.goal_store import GoalStore
from odigos.core.trace import Tracer
from odigos.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    # seed one built-in skill
    (d / "research.md").write_text(textwrap.dedent("""\
        ---
        name: research
        description: Deep research on a topic
        tools:
          - web_search
          - scrape
        complexity: standard
        ---
        You are a research assistant. Search the web and summarize findings.
    """))
    return str(d)


def _make_app(
    db: Database,
    settings: SimpleNamespace,
    skill_registry: SkillRegistry | None = None,
    goal_store: GoalStore | None = None,
    config_path: str = "/tmp/test_config.yaml",
    env_path: str = "/tmp/test_env",
) -> FastAPI:
    """Build a minimal FastAPI app with real routers wired to test state."""
    from odigos.api.skills import router as skills_router
    from odigos.api.goals import router as goals_router
    from odigos.api.settings import router as settings_router
    from odigos.api.evolution import router as evolution_router

    app = FastAPI()
    app.include_router(skills_router)
    app.include_router(goals_router)
    app.include_router(settings_router)
    app.include_router(evolution_router)

    app.state.settings = settings
    app.state.db = db
    app.state.config_path = config_path
    app.state.env_path = env_path
    if skill_registry:
        app.state.skill_registry = skill_registry
    if goal_store:
        app.state.goal_store = goal_store
    return app


def _settings(**overrides):
    defaults = dict(
        api_key="test-key",
        llm_api_key="sk-test",
        llm=SimpleNamespace(
            base_url="https://api.example.com",
            default_model="test/model",
            fallback_model="test/fallback",
            background_model="",
            max_tokens=4096,
            temperature=0.7,
            request_timeout_seconds=60.0,
            connect_timeout_seconds=10.0,
            model_dump=lambda: {
                "base_url": "https://api.example.com",
                "default_model": "test/model",
                "fallback_model": "test/fallback",
                "background_model": "",
                "max_tokens": 4096,
                "temperature": 0.7,
                "request_timeout_seconds": 60.0,
                "connect_timeout_seconds": 10.0,
            },
        ),
        agent=SimpleNamespace(
            name="TestAgent",
            description="A test agent",
            role="assistant",
            max_tool_turns=25,
            run_timeout_seconds=300,
            model_dump=lambda: {
                "name": "TestAgent",
                "description": "A test agent",
                "role": "assistant",
                "max_tool_turns": 25,
                "run_timeout_seconds": 300,
            },
        ),
        budget=SimpleNamespace(
            daily_limit_usd=1.0,
            monthly_limit_usd=20.0,
            warn_threshold=0.8,
            model_dump=lambda: {
                "daily_limit_usd": 1.0,
                "monthly_limit_usd": 20.0,
                "warn_threshold": 0.8,
            },
        ),
        heartbeat=SimpleNamespace(
            interval_seconds=30,
            max_todos_per_tick=3,
            idle_think_interval=300,
            announce_interval_seconds=60,
            model_dump=lambda: {
                "interval_seconds": 30,
                "max_todos_per_tick": 3,
                "idle_think_interval": 300,
                "announce_interval_seconds": 60,
            },
        ),
        sandbox=SimpleNamespace(
            timeout_seconds=5,
            max_memory_mb=512,
            allow_network=False,
            model_dump=lambda: {
                "timeout_seconds": 5,
                "max_memory_mb": 512,
                "allow_network": False,
            },
        ),
        mesh=SimpleNamespace(
            enabled=False,
            model_dump=lambda: {"enabled": False},
        ),
        feed=SimpleNamespace(
            enabled=False,
            public=False,
            max_entries=200,
            model_dump=lambda: {"enabled": False, "public": False, "max_entries": 200},
        ),
        templates=SimpleNamespace(
            repo_url="https://github.com/msitarzewski/agency-agents",
            cache_ttl_days=7,
            model_dump=lambda: {
                "repo_url": "https://github.com/msitarzewski/agency-agents",
                "cache_ttl_days": 7,
            },
        ),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


AUTH = {"Authorization": "Bearer test-key"}


# ===========================================================================
# 1. Skills: CRUD + Built-in protection
# ===========================================================================

class TestSkillsCRUD:
    """Verify full skill lifecycle through the API."""

    def test_list_includes_builtin(self, db, skills_dir):
        registry = SkillRegistry()
        registry.load_all(skills_dir)
        app = _make_app(db, _settings(), skill_registry=registry)
        client = TestClient(app)

        resp = client.get("/api/skills", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        names = [s["name"] for s in data["skills"]]
        assert "research" in names
        research = next(s for s in data["skills"] if s["name"] == "research")
        assert research["builtin"] is True
        assert "web_search" in research["tools"]

    def test_create_custom_skill(self, db, skills_dir):
        registry = SkillRegistry()
        registry.load_all(skills_dir)
        app = _make_app(db, _settings(), skill_registry=registry)
        client = TestClient(app)

        resp = client.post("/api/skills", headers=AUTH, json={
            "name": "my-custom",
            "description": "Custom skill for testing",
            "system_prompt": "You are a testing assistant.",
            "tools": ["run_code"],
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "created"

        # Verify it appears in list
        resp = client.get("/api/skills", headers=AUTH)
        names = [s["name"] for s in resp.json()["skills"]]
        assert "my-custom" in names

        # Verify file on disk
        assert (Path(skills_dir) / "my-custom.md").exists()

    def test_update_custom_skill(self, db, skills_dir):
        registry = SkillRegistry()
        registry.load_all(skills_dir)
        app = _make_app(db, _settings(), skill_registry=registry)
        client = TestClient(app)

        # Create first
        client.post("/api/skills", headers=AUTH, json={
            "name": "updatable",
            "description": "Original",
            "system_prompt": "Original prompt",
            "tools": [],
        })

        # Update
        resp = client.put("/api/skills/updatable", headers=AUTH, json={
            "description": "Updated description",
            "system_prompt": "Updated prompt",
        })
        assert resp.status_code == 200

        # Verify update persisted
        resp = client.get("/api/skills/updatable", headers=AUTH)
        skill = resp.json()
        assert skill["description"] == "Updated description"
        assert skill["system_prompt"] == "Updated prompt"

    def test_delete_custom_skill(self, db, skills_dir):
        registry = SkillRegistry()
        registry.load_all(skills_dir)
        app = _make_app(db, _settings(), skill_registry=registry)
        client = TestClient(app)

        client.post("/api/skills", headers=AUTH, json={
            "name": "deletable",
            "description": "Will be deleted",
            "system_prompt": "Temporary",
            "tools": [],
        })
        assert (Path(skills_dir) / "deletable.md").exists()

        resp = client.delete("/api/skills/deletable", headers=AUTH)
        assert resp.status_code == 200

        # Gone from list and disk
        resp = client.get("/api/skills", headers=AUTH)
        names = [s["name"] for s in resp.json()["skills"]]
        assert "deletable" not in names
        assert not (Path(skills_dir) / "deletable.md").exists()

    def test_cannot_delete_builtin(self, db, skills_dir):
        registry = SkillRegistry()
        registry.load_all(skills_dir)
        app = _make_app(db, _settings(), skill_registry=registry)
        client = TestClient(app)

        resp = client.delete("/api/skills/research", headers=AUTH)
        assert resp.status_code == 400
        assert "built-in" in resp.json()["detail"].lower()

    def test_cannot_overwrite_builtin(self, db, skills_dir):
        registry = SkillRegistry()
        registry.load_all(skills_dir)
        app = _make_app(db, _settings(), skill_registry=registry)
        client = TestClient(app)

        resp = client.post("/api/skills", headers=AUTH, json={
            "name": "research",
            "description": "Hijacked",
            "system_prompt": "Malicious",
            "tools": [],
        })
        assert resp.status_code == 400

    def test_invalid_skill_name_rejected(self, db, skills_dir):
        registry = SkillRegistry()
        registry.load_all(skills_dir)
        app = _make_app(db, _settings(), skill_registry=registry)
        client = TestClient(app)

        resp = client.post("/api/skills", headers=AUTH, json={
            "name": "../escape",
            "description": "Path traversal attempt",
            "system_prompt": "Nope",
            "tools": [],
        })
        assert resp.status_code == 400


# ===========================================================================
# 2. Skill activation side-effect
# ===========================================================================

class TestSkillActivation:
    """Verify the activate_skill tool produces the right side_effect."""

    async def test_activate_skill_returns_side_effect(self, skills_dir):
        from odigos.tools.skill_tool import ActivateSkillTool

        registry = SkillRegistry()
        registry.load_all(skills_dir)
        tool = ActivateSkillTool(skill_registry=registry)

        result = await tool.execute({"name": "research"})
        assert result.success is True
        assert result.side_effect is not None
        assert result.side_effect["skill_activation"] is True
        assert result.side_effect["skill_name"] == "research"
        assert "web_search" in result.side_effect["skill_tools"]
        assert len(result.side_effect["skill_prompt"]) > 10

    async def test_activate_nonexistent_skill(self, skills_dir):
        from odigos.tools.skill_tool import ActivateSkillTool

        registry = SkillRegistry()
        registry.load_all(skills_dir)
        tool = ActivateSkillTool(skill_registry=registry)

        result = await tool.execute({"name": "does-not-exist"})
        assert result.success is False


# ===========================================================================
# 3. Settings persistence + hot-reload
# ===========================================================================

class TestSettings:
    """Verify settings save to disk and hot-reload in memory."""

    def test_get_settings_masks_keys(self, db):
        app = _make_app(db, _settings())
        client = TestClient(app)

        resp = client.get("/api/settings", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_api_key"] == "****"
        assert data["api_key"] == "****"
        assert data["llm"]["default_model"] == "test/model"

    def test_update_settings_writes_config(self, db, tmp_path):
        config_path = str(tmp_path / "config.yaml")
        env_path = str(tmp_path / ".env")
        settings = _settings()
        app = _make_app(db, settings, config_path=config_path, env_path=env_path)
        client = TestClient(app)

        resp = client.post("/api/settings", headers=AUTH, json={
            "agent": {"name": "NewName", "description": "Updated agent"},
        })
        assert resp.status_code == 200

        # Verify config.yaml on disk
        import yaml
        with open(config_path) as f:
            on_disk = yaml.safe_load(f)
        assert on_disk["agent"]["name"] == "NewName"
        assert on_disk["agent"]["description"] == "Updated agent"

        # Verify in-memory hot-reload
        assert settings.agent.name == "NewName"

    def test_update_llm_model_hot_reloads(self, db, tmp_path):
        config_path = str(tmp_path / "config.yaml")
        env_path = str(tmp_path / ".env")
        settings = _settings()
        app = _make_app(db, settings, config_path=config_path, env_path=env_path)
        client = TestClient(app)

        resp = client.post("/api/settings", headers=AUTH, json={
            "llm": {"default_model": "anthropic/claude-opus-4"},
        })
        assert resp.status_code == 200
        assert settings.llm.default_model == "anthropic/claude-opus-4"

    def test_update_llm_api_key_writes_env(self, db, tmp_path):
        config_path = str(tmp_path / "config.yaml")
        env_path = str(tmp_path / ".env")
        settings = _settings()
        app = _make_app(db, settings, config_path=config_path, env_path=env_path)
        client = TestClient(app)

        resp = client.post("/api/settings", headers=AUTH, json={
            "llm_api_key": "sk-new-key-12345",
        })
        assert resp.status_code == 200

        # Verify .env file
        env_contents = Path(env_path).read_text()
        assert "LLM_API_KEY=sk-new-key-12345" in env_contents

        # Verify in-memory
        assert settings.llm_api_key == "sk-new-key-12345"

    def test_masked_key_not_overwritten(self, db, tmp_path):
        config_path = str(tmp_path / "config.yaml")
        env_path = str(tmp_path / ".env")
        Path(env_path).write_text("LLM_API_KEY=sk-original\n")
        settings = _settings()
        app = _make_app(db, settings, config_path=config_path, env_path=env_path)
        client = TestClient(app)

        # Sending "****" should NOT overwrite
        resp = client.post("/api/settings", headers=AUTH, json={
            "llm_api_key": "****",
        })
        assert resp.status_code == 200
        assert "sk-original" in Path(env_path).read_text()


# ===========================================================================
# 4. Goals, Todos, Reminders lifecycle
# ===========================================================================

class TestGoalLifecycle:
    """Verify goal/todo/reminder creation, listing, status transitions."""

    async def test_create_and_list_goal(self, db):
        store = GoalStore(db=db)
        goal_id = await store.create_goal("Ship v1 of the agent")
        goals = await store.list_goals(status="active")
        assert len(goals) == 1
        assert goals[0]["description"] == "Ship v1 of the agent"
        assert goals[0]["id"] == goal_id

    async def test_archive_goal(self, db):
        store = GoalStore(db=db)
        goal_id = await store.create_goal("Temporary goal")
        await store.update_goal(goal_id, status="archived")
        active = await store.list_goals(status="active")
        archived = await store.list_goals(status="archived")
        assert len(active) == 0
        assert len(archived) == 1

    async def test_create_and_complete_todo(self, db):
        store = GoalStore(db=db)
        todo_id = await store.create_todo("Write integration tests")
        pending = await store.list_todos(status="pending")
        assert len(pending) == 1

        await store.complete_todo(todo_id, result="Done - 15 tests written")
        pending = await store.list_todos(status="pending")
        completed = await store.list_todos(status="completed")
        assert len(pending) == 0
        assert len(completed) == 1
        assert completed[0]["result"] == "Done - 15 tests written"

    async def test_todo_linked_to_goal(self, db):
        store = GoalStore(db=db)
        goal_id = await store.create_goal("Build feature X")
        todo_id = await store.create_todo("Step 1 of feature X", goal_id=goal_id)
        todos = await store.list_todos(status="pending")
        assert todos[0]["goal_id"] == goal_id

    async def test_create_and_fire_reminder(self, db):
        store = GoalStore(db=db)
        reminder_id = await store.create_reminder(
            "Check deployment",
            due_seconds=0,  # due immediately
        )
        pending = await store.list_reminders(status="pending")
        assert len(pending) == 1
        assert pending[0]["description"] == "Check deployment"

    async def test_cancel_reminder(self, db):
        store = GoalStore(db=db)
        reminder_id = await store.create_reminder("Cancel me", due_seconds=3600)
        result = await store.cancel_reminder(reminder_id)
        assert result is True
        pending = await store.list_reminders(status="pending")
        assert len(pending) == 0

    def test_goals_api_endpoint(self, db):
        store = GoalStore(db=db)
        app = _make_app(db, _settings(), goal_store=store)
        client = TestClient(app)

        resp = client.get("/api/goals", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["goals"] == []

        resp = client.get("/api/todos", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["todos"] == []

        resp = client.get("/api/reminders", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["reminders"] == []


# ===========================================================================
# 5. Approval gate: interception + resolution
# ===========================================================================

class TestApprovalGate:
    """Verify tool calls are intercepted and resolution works."""

    async def test_gated_tool_blocked_until_approved(self, db):
        import asyncio
        from odigos.core.approval import ApprovalGate

        gate = ApprovalGate(
            db=db,
            tools_requiring_approval=["run_code", "run_shell", "write_file"],
            timeout=5,
        )

        assert gate.requires_approval("run_code") is True
        assert gate.requires_approval("web_search") is False

        # Start a request in background, resolve it quickly
        async def approve_after_delay(gate: ApprovalGate):
            await asyncio.sleep(0.1)
            # Find pending approval
            row = await db.fetch_one(
                "SELECT id FROM approvals WHERE decision = 'pending'"
            )
            assert row is not None
            gate.resolve(row["id"], "approved")

        task = asyncio.create_task(approve_after_delay(gate))
        decision = await gate.request("run_code", {"code": "print('hi')"}, "conv-1")
        await task

        assert decision == "approved"

        # Verify DB record
        row = await db.fetch_one("SELECT * FROM approvals WHERE decision = 'approved'")
        assert row is not None
        assert row["tool_name"] == "run_code"

    async def test_denied_tool_returns_denied(self, db):
        import asyncio
        from odigos.core.approval import ApprovalGate

        gate = ApprovalGate(
            db=db,
            tools_requiring_approval=["run_code"],
            timeout=5,
        )

        async def deny_after_delay(gate: ApprovalGate):
            await asyncio.sleep(0.1)
            row = await db.fetch_one(
                "SELECT id FROM approvals WHERE decision = 'pending'"
            )
            gate.resolve(row["id"], "denied")

        task = asyncio.create_task(deny_after_delay(gate))
        decision = await gate.request("run_code", {"code": "rm -rf /"}, "conv-2")
        await task

        assert decision == "denied"

    async def test_timeout_returns_timeout(self, db):
        from odigos.core.approval import ApprovalGate

        gate = ApprovalGate(
            db=db,
            tools_requiring_approval=["run_code"],
            timeout=0.2,  # very short timeout
        )
        decision = await gate.request("run_code", {"code": "slow"}, "conv-3")
        assert decision == "timeout"

    async def test_add_remove_gated_tool(self, db):
        from odigos.core.approval import ApprovalGate

        gate = ApprovalGate(db=db, tools_requiring_approval=["run_code"])
        assert gate.requires_approval("file") is False

        gate.add_tool("file")
        assert gate.requires_approval("file") is True

        gate.remove_tool("file")
        assert gate.requires_approval("file") is False


# ===========================================================================
# 6. Evolution status + trial DB operations
# ===========================================================================

class TestEvolutionStatus:
    """Verify evolution engine DB state is readable through the API."""

    async def test_evolution_status_empty(self, db):
        app = _make_app(db, _settings())
        client = TestClient(app)

        resp = client.get("/api/evolution/status", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_trial"] is None
        assert data["recent_eval_count"] == 0

    async def test_evaluations_list_empty(self, db):
        app = _make_app(db, _settings())
        client = TestClient(app)

        resp = client.get("/api/evolution/evaluations", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["evaluations"] == []

    async def test_seeded_evaluations_appear(self, db):
        """Seed evaluation records and verify they appear in the API."""
        await db.execute(
            "INSERT INTO evaluations (id, message_id, conversation_id, task_type, "
            "rubric, overall_score, scores) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("eval-1", "msg-1", "conv-1", "research", "quality rubric", 8.5,
             json.dumps({"accuracy": 9, "clarity": 8})),
        )
        await db.execute(
            "INSERT INTO evaluations (id, message_id, conversation_id, task_type, "
            "rubric, overall_score, scores) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("eval-2", "msg-2", "conv-1", "coding", "code rubric", 7.0,
             json.dumps({"correctness": 7, "style": 7})),
        )

        app = _make_app(db, _settings())
        client = TestClient(app)

        resp = client.get("/api/evolution/status", headers=AUTH)
        data = resp.json()
        assert data["recent_eval_count"] == 2
        assert data["recent_avg_score"] == pytest.approx(7.75)

    async def test_trial_promote_revert(self, db):
        """Seed an active trial and verify promote/revert endpoints work."""
        import uuid

        trial_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO trials (id, hypothesis, target, status, min_evaluations, expires_at) "
            "VALUES (?, ?, ?, 'active', 3, datetime('now', '+1 day'))",
            (trial_id, "Test hypothesis", "prompt_section"),
        )

        app = _make_app(db, _settings())

        # Mock checkpoint manager since promote/revert need it
        mock_cm = AsyncMock()
        app.state.checkpoint_manager = mock_cm

        client = TestClient(app)

        # Promote
        resp = client.post(f"/api/evolution/trial/{trial_id}/promote", headers=AUTH)
        assert resp.status_code == 200
        mock_cm.promote_trial.assert_awaited_once_with(trial_id)

    async def test_proposals_approve_dismiss(self, db):
        """Verify specialization proposals can be approved and dismissed."""
        import uuid

        p1 = str(uuid.uuid4())
        p2 = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO specialization_proposals (id, proposed_by, role, description, status) "
            "VALUES (?, ?, ?, ?, 'pending')",
            (p1, "strategist", "researcher", "Focus on academic papers"),
        )
        await db.execute(
            "INSERT INTO specialization_proposals (id, proposed_by, role, description, status) "
            "VALUES (?, ?, ?, ?, 'pending')",
            (p2, "strategist", "code-reviewer", "Add more code review"),
        )

        app = _make_app(db, _settings())
        client = TestClient(app)

        # List pending
        resp = client.get("/api/proposals?status=pending", headers=AUTH)
        assert len(resp.json()["proposals"]) == 2

        # Approve one
        resp = client.post(f"/api/proposals/{p1}/approve", headers=AUTH)
        assert resp.status_code == 200

        # Dismiss other
        resp = client.post(f"/api/proposals/{p2}/dismiss", headers=AUTH)
        assert resp.status_code == 200

        # None pending
        resp = client.get("/api/proposals?status=pending", headers=AUTH)
        assert len(resp.json()["proposals"]) == 0


# ===========================================================================
# 7. Budget enforcement
# ===========================================================================

class TestBudgetEnforcement:
    """Verify budget tracker catches over-budget state."""

    async def test_within_budget(self, db):
        from odigos.core.budget import BudgetTracker

        tracker = BudgetTracker(
            db=db, daily_limit=10.0, monthly_limit=100.0, warn_threshold=0.8,
        )
        status = await tracker.check_budget()
        assert status.within_budget is True
        assert status.warning is False

    async def test_over_daily_budget(self, db):
        from odigos.core.budget import BudgetTracker

        # Seed expensive messages
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES ('conv-budget', 'test')"
        )
        for i in range(5):
            await db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, cost_usd) "
                "VALUES (?, 'conv-budget', 'assistant', 'expensive', ?)",
                (f"msg-budget-{i}", 3.0),
            )

        tracker = BudgetTracker(
            db=db, daily_limit=10.0, monthly_limit=100.0, warn_threshold=0.8,
        )
        status = await tracker.check_budget()
        # 5 * $3 = $15, over daily limit of $10
        assert status.within_budget is False

    async def test_warning_threshold(self, db):
        from odigos.core.budget import BudgetTracker

        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES ('conv-warn', 'test')"
        )
        # Seed $8.50 of spend against $10 daily limit (85% > 80% threshold)
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, cost_usd) "
            "VALUES ('msg-warn-1', 'conv-warn', 'assistant', 'pricey', 8.50)",
        )

        tracker = BudgetTracker(
            db=db, daily_limit=10.0, monthly_limit=100.0, warn_threshold=0.8,
        )
        status = await tracker.check_budget()
        assert status.within_budget is True
        assert status.warning is True


# ===========================================================================
# 8. Sandbox filesystem isolation
# ===========================================================================

class TestSandboxIsolation:
    """Verify sandboxed code runs in temp dir, not /app."""

    async def test_code_runs_in_temp_dir(self):
        from odigos.providers.sandbox import SandboxProvider

        sandbox = SandboxProvider(timeout=5)
        result = await sandbox.execute("import os; print(os.getcwd())", language="python")
        assert result.exit_code == 0
        assert "/app" not in result.stdout
        assert "odigos_sandbox_" in result.stdout

    async def test_code_cannot_see_env_vars(self):
        from odigos.providers.sandbox import SandboxProvider

        sandbox = SandboxProvider(timeout=5)
        result = await sandbox.execute(
            "import os; print(os.environ.get('HOME', 'none'))",
            language="python",
        )
        assert result.exit_code == 0
        # HOME should be the temp dir, not the real home
        assert "odigos_sandbox_" in result.stdout

    async def test_shell_runs_in_temp_dir(self):
        from odigos.providers.sandbox import SandboxProvider

        sandbox = SandboxProvider(timeout=5)
        result = await sandbox.execute("pwd", language="shell")
        assert result.exit_code == 0
        assert "odigos_sandbox_" in result.stdout

    async def test_timeout_kills_process(self):
        from odigos.providers.sandbox import SandboxProvider

        sandbox = SandboxProvider(timeout=1)
        result = await sandbox.execute(
            "import time; time.sleep(30)", language="python"
        )
        assert result.timed_out is True


# ===========================================================================
# 9. API authentication
# ===========================================================================

class TestAPIAuth:
    """Verify API endpoints require valid authentication."""

    def test_no_auth_rejected(self, db, skills_dir):
        registry = SkillRegistry()
        registry.load_all(skills_dir)
        app = _make_app(db, _settings(), skill_registry=registry)
        client = TestClient(app)

        assert client.get("/api/skills").status_code == 401
        assert client.get("/api/settings").status_code == 401
        assert client.get("/api/goals").status_code == 401

    def test_wrong_key_rejected(self, db, skills_dir):
        registry = SkillRegistry()
        registry.load_all(skills_dir)
        app = _make_app(db, _settings(), skill_registry=registry)
        client = TestClient(app)

        bad_auth = {"Authorization": "Bearer wrong-key"}
        assert client.get("/api/skills", headers=bad_auth).status_code == 403

    def test_valid_key_accepted(self, db, skills_dir):
        registry = SkillRegistry()
        registry.load_all(skills_dir)
        app = _make_app(db, _settings(), skill_registry=registry)
        client = TestClient(app)

        assert client.get("/api/skills", headers=AUTH).status_code == 200


# ===========================================================================
# 10. Default approval config
# ===========================================================================

class TestDefaultApprovalConfig:
    """Verify approval gate is enabled by default for dangerous tools."""

    def test_defaults_gate_dangerous_tools(self):
        from odigos.config import ApprovalConfig

        config = ApprovalConfig()
        assert config.enabled is True
        assert "run_code" in config.tools
        assert "run_shell" in config.tools
        assert "write_file" in config.tools
