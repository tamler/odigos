from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.providers.sandbox import SandboxProvider

logger = logging.getLogger(__name__)


class CodeTool(BaseTool):
    """Execute Python or shell code in a sandboxed environment."""

    name = "run_code"
    description = "Execute Python or shell code in a sandboxed environment with resource limits"
    parameters_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Code to execute"},
            "language": {"type": "string", "description": "Programming language (python or shell)"},
        },
        "required": ["code"],
    }

    def __init__(self, sandbox: SandboxProvider) -> None:
        self.sandbox = sandbox

    async def execute(self, params: dict) -> ToolResult:
        code = params.get("code", "")
        if not code:
            return ToolResult(success=False, data="", error="No code provided")

        language = params.get("language", "python")

        result = await self.sandbox.execute(code, language=language)

        if result.timed_out:
            return ToolResult(
                success=False,
                data=result.stdout,
                error=f"Code execution timed out. stderr: {result.stderr}",
            )

        if result.exit_code != 0:
            return ToolResult(
                success=False,
                data=result.stdout,
                error=result.stderr or f"Process exited with code {result.exit_code}",
            )

        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]: {result.stderr}"
        return ToolResult(success=True, data=output)
