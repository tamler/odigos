from __future__ import annotations

import asyncio
import logging
import platform
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_IS_LINUX = platform.system() == "Linux"


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


class SandboxProvider:
    """Runs code in a sandboxed subprocess with resource limits."""

    def __init__(
        self,
        timeout: int = 5,
        max_memory_mb: int = 512,
        allow_network: bool = False,
        max_output_chars: int = 4000,
    ) -> None:
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.allow_network = allow_network
        self.max_output_chars = max_output_chars

    async def execute(self, code: str, language: str = "python") -> SandboxResult:
        """Run code in a sandboxed subprocess."""
        if language == "python":
            cmd = self._build_python_cmd(code)
        elif language == "shell":
            cmd = self._build_shell_cmd(code)
        else:
            return SandboxResult(
                stdout="",
                stderr=f"Unsupported language: {language}",
                exit_code=1,
                timed_out=False,
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout + 5
            )
            stdout = self._truncate(stdout_bytes.decode(errors="replace"))
            stderr = self._truncate(stderr_bytes.decode(errors="replace"))
            return SandboxResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode or 0,
                timed_out=False,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(
                stdout="",
                stderr="Execution timed out",
                exit_code=-1,
                timed_out=True,
            )
        except Exception as e:
            logger.exception("Sandbox execution failed")
            return SandboxResult(
                stdout="",
                stderr=str(e),
                exit_code=-1,
                timed_out=False,
            )

    def _build_python_cmd(self, code: str) -> list[str]:
        limits = self._resource_prefix()
        return [*limits, "python3", "-c", code]

    def _build_shell_cmd(self, code: str) -> list[str]:
        limits = self._resource_prefix()
        return [*limits, "bash", "-c", f"set -euo pipefail; {code}"]

    def _resource_prefix(self) -> list[str]:
        """Build ulimit + optional unshare prefix."""
        memory_kb = self.max_memory_mb * 1024
        parts = [
            "bash", "-c",
            f"ulimit -t {self.timeout} -v {memory_kb}; exec \"$@\"",
            "--",
        ]
        if _IS_LINUX and not self.allow_network:
            return ["unshare", "--net", *parts]
        if not _IS_LINUX:
            logger.debug("Skipping unshare on %s (not Linux)", platform.system())
        return parts

    def _truncate(self, text: str) -> str:
        if len(text) > self.max_output_chars:
            return text[: self.max_output_chars] + "\n[output truncated]"
        return text
