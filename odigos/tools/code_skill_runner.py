from __future__ import annotations

import json
import logging
import os

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class CodeSkillRunner(BaseTool):
    """Wraps a single executable code skill as a tool."""

    def __init__(
        self,
        skill_name: str,
        skill_description: str,
        code_path: str,
        parameters: dict,
        timeout: int = 10,
        allow_network: bool = False,
        skill_md_path: str | None = None,
        verified: bool = False,
    ) -> None:
        self.name = f"skill_{skill_name}"
        self.description = skill_description
        self.parameters_schema = {
            "type": "object",
            "properties": {
                key: val for key, val in parameters.items()
            },
            "required": list(parameters.keys()),
        }
        self._code_path = code_path
        self._timeout = timeout
        self._allow_network = allow_network
        self._skill_md_path = skill_md_path
        self._verified = verified

    async def execute(self, params: dict) -> ToolResult:
        from odigos.providers.sandbox import SandboxProvider

        if not os.path.exists(self._code_path):
            return ToolResult(
                success=False,
                data="",
                error=f"Skill code file not found: {self._code_path}",
            )

        try:
            with open(self._code_path, "r", encoding="utf-8") as f:
                skill_code = f.read()
        except OSError as exc:
            return ToolResult(success=False, data="", error=f"Failed to read skill code: {exc}")

        params_repr = json.dumps(params)
        wrapper = (
            f"{skill_code}\n\n"
            "import json as _json\n"
            f"_params = _json.loads({params_repr!r})\n"
            "_result = run(**_params)\n"
            "print(_json.dumps(_result))\n"
        )

        sandbox = SandboxProvider(timeout=self._timeout, allow_network=self._allow_network)
        result = await sandbox.execute(wrapper)

        if result.timed_out:
            return ToolResult(
                success=False,
                data="",
                error=f"Skill execution timed out after {self._timeout}s",
            )

        if result.exit_code != 0:
            return ToolResult(
                success=False,
                data=result.stdout,
                error=result.stderr or f"Skill exited with code {result.exit_code}",
            )

        output = result.stdout.strip()
        try:
            parsed = json.loads(output)
            data = parsed if isinstance(parsed, str) else json.dumps(parsed)
        except (json.JSONDecodeError, ValueError):
            data = output

        if not self._verified and self._skill_md_path:
            try:
                self._update_verified()
            except Exception as exc:
                logger.warning("Failed to update verified flag in %s: %s", self._skill_md_path, exc)

        return ToolResult(success=True, data=data)

    def _update_verified(self) -> None:
        with open(self._skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.startswith("---"):
            self._verified = True
            return

        # Find closing --- of frontmatter
        end_marker = content.find("\n---", 3)
        if end_marker == -1:
            self._verified = True
            return

        frontmatter = content[3:end_marker]
        body = content[end_marker + 4:]  # skip \n---

        lines = frontmatter.splitlines()
        new_lines = []
        found = False
        for line in lines:
            if line.startswith("verified:"):
                new_lines.append("verified: true")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append("verified: true")

        new_content = "---\n" + "\n".join(new_lines) + "\n---" + body
        with open(self._skill_md_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        self._verified = True
