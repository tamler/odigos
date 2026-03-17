import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from odigos.providers.sandbox import SandboxResult
from odigos.tools.code import CodeTool


@pytest_asyncio.fixture
async def mock_sandbox():
    sb = MagicMock()
    sb.execute = AsyncMock(
        return_value=SandboxResult(stdout="42\n", stderr="", exit_code=0, timed_out=False)
    )
    return sb


@pytest_asyncio.fixture
async def code_tool(mock_sandbox):
    return CodeTool(sandbox=mock_sandbox)


@pytest.mark.asyncio
async def test_tool_name(code_tool):
    assert code_tool.name == "run_code"


@pytest.mark.asyncio
async def test_execute_python(code_tool, mock_sandbox):
    result = await code_tool.execute({"code": "print(42)", "language": "python"})
    assert result.success is True
    assert "42" in result.data
    mock_sandbox.execute.assert_called_once_with("print(42)", language="python", pre_files=None)


@pytest.mark.asyncio
async def test_execute_shell(code_tool, mock_sandbox):
    result = await code_tool.execute({"code": "echo hi", "language": "shell"})
    assert result.success is True
    mock_sandbox.execute.assert_called_once_with("echo hi", language="shell", pre_files=None)


@pytest.mark.asyncio
async def test_defaults_to_python(code_tool, mock_sandbox):
    await code_tool.execute({"code": "print(1)"})
    mock_sandbox.execute.assert_called_once_with("print(1)", language="python", pre_files=None)


@pytest.mark.asyncio
async def test_missing_code_returns_error(code_tool):
    result = await code_tool.execute({})
    assert result.success is False
    assert "code" in result.error.lower()


@pytest.mark.asyncio
async def test_execution_failure(mock_sandbox):
    mock_sandbox.execute = AsyncMock(
        return_value=SandboxResult(stdout="", stderr="NameError", exit_code=1, timed_out=False)
    )
    tool = CodeTool(sandbox=mock_sandbox)
    result = await tool.execute({"code": "bad_code"})
    assert result.success is False
    assert "NameError" in result.error


@pytest.mark.asyncio
async def test_timeout_failure(mock_sandbox):
    mock_sandbox.execute = AsyncMock(
        return_value=SandboxResult(stdout="", stderr="timed out", exit_code=-1, timed_out=True)
    )
    tool = CodeTool(sandbox=mock_sandbox)
    result = await tool.execute({"code": "while True: pass"})
    assert result.success is False
    assert "timed out" in result.error.lower()
