"""Tests for the Agent Browser tool."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.tools.browser import BrowserTool


@pytest.fixture
def browser_tool():
    return BrowserTool(timeout=10)


@pytest.mark.asyncio
async def test_empty_command(browser_tool):
    result = await browser_tool.execute({"command": ""})
    assert not result.success
    assert "Missing required parameter" in result.error


@pytest.mark.asyncio
async def test_missing_command(browser_tool):
    result = await browser_tool.execute({})
    assert not result.success
    assert "Missing required parameter" in result.error


@pytest.mark.asyncio
async def test_malformed_quotes(browser_tool):
    result = await browser_tool.execute({"command": "navigate --url 'unclosed"})
    assert not result.success
    assert "Invalid command syntax" in result.error


@pytest.mark.asyncio
async def test_cli_not_found(browser_tool):
    with patch("odigos.tools.subprocess_tool.asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        result = await browser_tool.execute({"command": "navigate --url 'https://example.com'"})
    assert not result.success
    assert "agent-browser CLI not found" in result.error


@pytest.mark.asyncio
async def test_timeout(browser_tool):
    mock_proc = AsyncMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("odigos.tools.subprocess_tool.asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("odigos.tools.subprocess_tool.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await browser_tool.execute({"command": "navigate --url 'https://slow.com'"})
    assert not result.success
    assert "timed out" in result.error
    mock_proc.kill.assert_called_once()
    mock_proc.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_nonzero_exit(browser_tool):
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"partial output", b"some error")
    mock_proc.returncode = 1

    with patch("odigos.tools.subprocess_tool.asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("odigos.tools.subprocess_tool.asyncio.wait_for", return_value=(b"partial output", b"some error")):
            mock_proc.communicate.return_value = (b"partial output", b"some error")
            result = await browser_tool.execute({"command": "click --selector '#btn'"})
    assert not result.success
    assert "some error" in result.error


@pytest.mark.asyncio
async def test_success(browser_tool):
    mock_proc = AsyncMock()
    mock_proc.returncode = 0

    with patch("odigos.tools.subprocess_tool.asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("odigos.tools.subprocess_tool.asyncio.wait_for", return_value=(b'{"status": "ok"}', b"")):
            result = await browser_tool.execute({"command": "navigate --url 'https://example.com'"})
    assert result.success
    assert '{"status": "ok"}' in result.data


@pytest.mark.asyncio
async def test_subprocess_receives_correct_args():
    tool = BrowserTool(timeout=30)
    mock_proc = AsyncMock()
    mock_proc.returncode = 0

    with patch("odigos.tools.subprocess_tool.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        with patch("odigos.tools.subprocess_tool.asyncio.wait_for", return_value=(b"ok", b"")):
            await tool.execute({"command": "navigate --url 'https://example.com'"})

    mock_exec.assert_called_once_with(
        "agent-browser", "navigate", "--url", "https://example.com",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


@pytest.mark.asyncio
async def test_custom_timeout():
    tool = BrowserTool(timeout=60)
    assert tool._timeout == 60


@pytest.mark.asyncio
async def test_tool_metadata():
    tool = BrowserTool()
    assert tool.name == "run_browser"
    assert "browser" in tool.description.lower()
    assert "command" in tool.parameters_schema["properties"]
