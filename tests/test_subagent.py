import json
import uuid

import pytest
import pytest_asyncio

from odigos.db import Database


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


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
        """Tool resolution: skill.tools union persona.tools by default."""
        from odigos.core.subagent import resolve_tools

        persona_tools = ["web_search", "scrape"]
        skill_tools = ["memory_recall", "scrape"]
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
