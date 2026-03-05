import pytest
import pytest_asyncio
from odigos.providers.sandbox import SandboxProvider, SandboxResult


@pytest_asyncio.fixture
async def sandbox():
    return SandboxProvider(timeout=5, max_memory_mb=512, allow_network=False)


@pytest.mark.asyncio
async def test_python_hello_world(sandbox):
    result = await sandbox.execute("print('hello')", language="python")
    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.timed_out is False


@pytest.mark.asyncio
async def test_shell_echo(sandbox):
    result = await sandbox.execute("echo hello", language="shell")
    assert result.exit_code == 0
    assert "hello" in result.stdout


@pytest.mark.asyncio
async def test_python_stderr(sandbox):
    result = await sandbox.execute("import sys; sys.stderr.write('err')", language="python")
    assert "err" in result.stderr


@pytest.mark.asyncio
async def test_python_syntax_error(sandbox):
    result = await sandbox.execute("def", language="python")
    assert result.exit_code != 0


@pytest.mark.asyncio
async def test_timeout_kills_process(sandbox):
    sb = SandboxProvider(timeout=1, max_memory_mb=512)
    result = await sb.execute("import time; time.sleep(10); print('done')", language="python")
    assert result.timed_out is True
    assert result.exit_code != 0


@pytest.mark.asyncio
async def test_output_truncation(sandbox):
    sb = SandboxProvider(timeout=5, max_memory_mb=512, max_output_chars=50)
    result = await sb.execute("print('x' * 200)", language="python")
    assert len(result.stdout) <= 80  # 50 + truncation notice


@pytest.mark.asyncio
async def test_unsupported_language(sandbox):
    result = await sandbox.execute("console.log('hi')", language="javascript")
    assert result.exit_code != 0
    assert "Unsupported" in result.stderr


@pytest.mark.asyncio
async def test_shell_pipefail(sandbox):
    result = await sandbox.execute("false", language="shell")
    assert result.exit_code != 0
