import json

import pytest
from unittest.mock import AsyncMock

from odigos.db import Database
from odigos.providers.base import LLMResponse, ToolCall


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


class TestActionLogMigration:
    async def test_action_log_table_exists(self, db: Database):
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='action_log'"
        )
        assert row is not None

    async def test_action_log_columns(self, db: Database):
        rows = await db.fetch_all("PRAGMA table_info(action_log)")
        col_names = {r["name"] for r in rows}
        assert col_names == {
            "id", "conversation_id", "action_type", "action_name",
            "details_json", "timestamp",
        }


class TestAgentLogsActions:
    async def test_tool_execution_logged(self, db: Database):
        """When executor runs a tool, it logs the result."""
        from odigos.core.executor import Executor
        from odigos.core.context import ContextAssembler
        from odigos.tools.base import BaseTool, ToolResult
        from odigos.tools.registry import ToolRegistry

        mock_tool = AsyncMock(spec=BaseTool)
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters_schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        mock_tool.execute = AsyncMock(
            return_value=ToolResult(success=True, data="results here")
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        mock_provider = AsyncMock()
        mock_provider.complete.side_effect = [
            LLMResponse(
                content="", model="test", tokens_in=10, tokens_out=10, cost_usd=0.001,
                tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "test"})],
            ),
            LLMResponse(
                content="Found it", model="test", tokens_in=10, tokens_out=5, cost_usd=0.001,
            ),
        ]

        assembler = ContextAssembler(
            db=db, agent_name="Test", history_limit=20, personality_path="/nonexistent"
        )
        executor = Executor(
            provider=mock_provider,
            context_assembler=assembler,
            tool_registry=registry,
            db=db,
        )

        # Need a conversation for context assembler
        await db.execute(
            "INSERT INTO conversations (id, channel) VALUES (?, ?)",
            ("conv-1", "test"),
        )

        await executor.execute("conv-1", "search for test")

        rows = await db.fetch_all(
            "SELECT * FROM action_log WHERE action_type = 'tool'"
        )
        assert len(rows) == 1
        assert rows[0]["action_name"] == "web_search"
        details = json.loads(rows[0]["details_json"])
        assert details["success"] is True
