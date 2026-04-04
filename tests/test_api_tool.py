"""Tests for APITool base class."""
from __future__ import annotations

import pytest
import httpx
from pytest_httpx import HTTPXMock

from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.api_tool import APITool, ToolAPIError


class FakeAPITool(APITool):
    name = "fake_api"
    description = "Test API tool"
    parameters_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True, data="ok")


class TestToolAPIError:
    def test_default_category(self):
        err = ToolAPIError(400, "Bad Request")
        assert err.failure_category == "unknown"

    def test_custom_category(self):
        err = ToolAPIError(503, "Unavailable", failure_category="transient")
        assert err.failure_category == "transient"

    def test_str_representation(self):
        err = ToolAPIError(422, "Unprocessable")
        assert str(err) == "Unprocessable"

    def test_status_code_stored(self):
        err = ToolAPIError(404, "Not found")
        assert err.status_code == 404

    def test_message_stored(self):
        err = ToolAPIError(500, "Server error")
        assert err.message == "Server error"


class TestAPIToolInit:
    @pytest.mark.asyncio
    async def test_stores_http_client(self):
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        assert tool.http is client
        await client.aclose()

    @pytest.mark.asyncio
    async def test_inherits_from_base_tool(self):
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        assert isinstance(tool, BaseTool)
        await client.aclose()


class TestAPIToolPost:
    @pytest.mark.asyncio
    async def test_post_success_returns_parsed_json(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/v1/create",
            json={"id": "abc123", "status": "ok"},
            status_code=200,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        result = await tool.api_post(
            "https://api.example.com/v1/create",
            {"prompt": "hello"},
            "test-key",
        )
        assert result == {"id": "abc123", "status": "ok"}
        await client.aclose()

    @pytest.mark.asyncio
    async def test_post_raises_tool_api_error_on_4xx(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/v1/create",
            json={"error": "Bad input"},
            status_code=400,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        with pytest.raises(ToolAPIError) as exc_info:
            await tool.api_post(
                "https://api.example.com/v1/create",
                {"prompt": "hello"},
                "test-key",
            )
        assert exc_info.value.status_code == 400
        assert "Bad input" in exc_info.value.message
        await client.aclose()

    @pytest.mark.asyncio
    async def test_post_uses_msg_field_for_error(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/v1/create",
            json={"msg": "rate limited"},
            status_code=429,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        with pytest.raises(ToolAPIError) as exc_info:
            await tool.api_post(
                "https://api.example.com/v1/create",
                {},
                "test-key",
            )
        assert "rate limited" in exc_info.value.message
        await client.aclose()


class TestAPIToolGet:
    @pytest.mark.asyncio
    async def test_get_success_returns_parsed_json(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            method="GET",
            url="https://api.example.com/v1/status?task_id=xyz",
            json={"status": "complete", "url": "http://result.com/out.mp3"},
            status_code=200,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        result = await tool.api_get(
            "https://api.example.com/v1/status",
            "test-key",
            params={"task_id": "xyz"},
        )
        assert result["status"] == "complete"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_get_raises_on_5xx(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            method="GET",
            url="https://api.example.com/v1/status",
            json={"error": "Internal Server Error"},
            status_code=500,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        with pytest.raises(ToolAPIError) as exc_info:
            await tool.api_get(
                "https://api.example.com/v1/status",
                "test-key",
            )
        assert exc_info.value.status_code == 500
        await client.aclose()


class TestAPIToolPollUntil:
    @pytest.mark.asyncio
    async def test_poll_success_pending_then_done(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            method="GET",
            url="https://api.example.com/v1/task?task_id=t1",
            json={"status": "pending"},
            status_code=200,
        )
        httpx_mock.add_response(
            method="GET",
            url="https://api.example.com/v1/task?task_id=t1",
            json={"status": "complete", "result": "done!"},
            status_code=200,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        result = await tool.poll_until(
            url="https://api.example.com/v1/task",
            api_key="test-key",
            params={"task_id": "t1"},
            success_check=lambda d: d.get("status") == "complete",
            failure_check=lambda d: d.get("status") == "failed",
            extract=lambda d: d["result"],
            max_seconds=5,
            initial_delay=0.01,
            max_delay=0.05,
        )
        assert result == "done!"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_poll_failure_raises(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            method="GET",
            url="https://api.example.com/v1/task?task_id=t2",
            json={"status": "failed", "reason": "out of credits"},
            status_code=200,
        )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        with pytest.raises(ToolAPIError) as exc_info:
            await tool.poll_until(
                url="https://api.example.com/v1/task",
                api_key="test-key",
                params={"task_id": "t2"},
                success_check=lambda d: d.get("status") == "complete",
                failure_check=lambda d: d.get("status") == "failed",
                extract=lambda d: d["result"],
                max_seconds=5,
                initial_delay=0.01,
                max_delay=0.05,
            )
        assert "Task failed" in str(exc_info.value)
        await client.aclose()

    @pytest.mark.asyncio
    @pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
    async def test_poll_timeout_raises(self, httpx_mock: HTTPXMock):
        # Always return pending — will time out; register more than needed
        for _ in range(20):
            httpx_mock.add_response(
                method="GET",
                url="https://api.example.com/v1/task?task_id=t3",
                json={"status": "pending"},
                status_code=200,
            )
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        with pytest.raises(ToolAPIError) as exc_info:
            await tool.poll_until(
                url="https://api.example.com/v1/task",
                api_key="test-key",
                params={"task_id": "t3"},
                success_check=lambda d: d.get("status") == "complete",
                failure_check=lambda d: d.get("status") == "failed",
                extract=lambda d: d["result"],
                max_seconds=0.1,
                initial_delay=0.01,
                max_delay=0.05,
            )
        assert "timed out" in str(exc_info.value).lower()
        await client.aclose()


class TestAPIToolFormatForContext:
    @pytest.mark.asyncio
    async def test_default_passes_through(self):
        client = httpx.AsyncClient()
        tool = FakeAPITool(http=client)
        result = ToolResult(success=True, data="some output")
        assert tool.format_for_context(result) == "some output"
        await client.aclose()
