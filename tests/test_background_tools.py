"""Tests for backgroundable tools: poll_once, pending detection, background polling."""
import pytest
import httpx

from odigos.tools.api_tool import APITool, ToolAPIError
from odigos.tools.base import ToolResult

# conftest.py provides the fake_db fixture


class FakeBgTool(APITool):
    name = "fake_bg"
    description = "Test backgroundable tool"

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True, data="ok")


class TestPollOnce:
    @pytest.mark.asyncio
    async def test_poll_once_done(self, httpx_mock):
        httpx_mock.add_response(url="https://api.example.com/poll?taskId=t1", json={"status": "done", "result": "image.png"})
        client = httpx.AsyncClient()
        tool = FakeBgTool(http=client)
        status, result = await tool.poll_once(
            "https://api.example.com/poll", api_key="test", params={"taskId": "t1"},
            success_check=lambda d: d.get("status") == "done",
            failure_check=lambda d: d.get("status") == "failed",
            extract=lambda d: d["result"],
        )
        assert status == "done"
        assert result == "image.png"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_poll_once_pending(self, httpx_mock):
        httpx_mock.add_response(url="https://api.example.com/poll", json={"status": "processing"})
        client = httpx.AsyncClient()
        tool = FakeBgTool(http=client)
        status, result = await tool.poll_once(
            "https://api.example.com/poll", api_key="test", params={},
            success_check=lambda d: d.get("status") == "done",
            failure_check=lambda d: d.get("status") == "failed",
            extract=lambda d: d["result"],
        )
        assert status == "pending"
        assert result is None
        await client.aclose()

    @pytest.mark.asyncio
    async def test_poll_once_failed(self, httpx_mock):
        httpx_mock.add_response(url="https://api.example.com/poll", json={"status": "failed", "error": "bad input"})
        client = httpx.AsyncClient()
        tool = FakeBgTool(http=client)
        status, result = await tool.poll_once(
            "https://api.example.com/poll", api_key="test", params={},
            success_check=lambda d: d.get("status") == "done",
            failure_check=lambda d: d.get("status") == "failed",
            extract=lambda d: d["result"],
        )
        assert status == "failed"
        assert result["error"] == "bad input"
        await client.aclose()


class TestPendingDetection:
    @pytest.mark.asyncio
    async def test_store_background_task(self, fake_db):
        from odigos.core.executor import _store_background_task
        bg_info = {
            "tool_name": "generate_image",
            "external_task_id": "ext123",
            "conversation_id": "conv456",
            "arguments": {"prompt": "sunset"},
        }
        task_id = await _store_background_task(fake_db, bg_info)
        assert task_id is not None

        row = await fake_db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        assert row is not None
        assert row["type"] == "background_poll"
        assert row["status"] == "pending"
        assert "generate_image" in row["payload_json"]
        assert row["conversation_id"] == "conv456"
