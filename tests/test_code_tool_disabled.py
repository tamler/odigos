import pytest

from odigos.providers.sandbox import SandboxResult


class _DisabledSandbox:
    async def execute(self, code, language="python", pre_files=None):
        return SandboxResult(
            stdout="",
            stderr="Code execution disabled: filesystem isolation (bubblewrap) is required but unavailable.",
            exit_code=-1,
            timed_out=False,
        )


@pytest.mark.asyncio
async def test_code_tool_reports_disabled_clearly():
    from odigos.tools.code import CodeTool

    tool = CodeTool(sandbox=_DisabledSandbox(), db=None)
    res = await tool.execute({"code": "print(1)", "language": "python"})
    assert res.success is False
    assert "disabled" in (res.error or "").lower()
    # Must be pre-classified as a non-retryable category so the executor
    # does not retry a fail-closed sandbox.
    assert res.failure_category == "unavailable"
