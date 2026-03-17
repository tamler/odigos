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

    def __init__(self, sandbox: SandboxProvider, db=None) -> None:
        self.sandbox = sandbox
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        code = params.get("code", "")
        if not code:
            return ToolResult(success=False, data="", error="No code provided")

        language = params.get("language", "python")
        pre_files = None

        # Prepare document helpers for Python execution
        if language == "python" and self._db:
            from odigos.tools.doc_helpers import prepare_doc_files, DOC_PREAMBLE
            files, has_docs = await prepare_doc_files(self._db)
            if has_docs:
                pre_files = files
                code = DOC_PREAMBLE + "\n" + code

        result = await self.sandbox.execute(code, language=language, pre_files=pre_files)

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
