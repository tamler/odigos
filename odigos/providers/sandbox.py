from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import tempfile
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
    """Runs code in a sandboxed subprocess with resource limits.

    Isolation strategy (best available, in order):
    1. bubblewrap (bwrap) -- mount namespace, no access to /app or host fs
    2. unshare --net -- network namespace only (needs CAP_SYS_ADMIN)
    3. ulimit only -- CPU/memory limits, no filesystem isolation (dev fallback)
    """

    _isolation: str | None = None  # "bwrap", "unshare", or "ulimit"

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
        if SandboxProvider._isolation is None:
            SandboxProvider._isolation = self._detect_isolation()

    @staticmethod
    def _detect_isolation() -> str:
        """Probe available isolation mechanisms at startup."""
        import subprocess

        # Try bubblewrap first (best isolation)
        if _IS_LINUX and shutil.which("bwrap"):
            try:
                # Use symlinks for /lib and /lib64 (they're often symlinks in slim images)
                probe_cmd = [
                    "bwrap",
                    "--ro-bind", "/usr", "/usr",
                    "--ro-bind", "/bin", "/bin",
                    "--symlink", "/usr/lib", "/lib",
                    "--proc", "/proc", "--dev", "/dev",
                    "--tmpfs", "/tmp", "--unshare-all",
                    "true",
                ]
                result = subprocess.run(
                    probe_cmd,
                    capture_output=True, timeout=5,
                )
                if result.returncode == 0:
                    logger.info("Sandbox isolation: bubblewrap (bwrap)")
                    return "bwrap"
            except Exception:
                pass

        # Try unshare (network isolation only)
        if _IS_LINUX:
            try:
                result = subprocess.run(
                    ["unshare", "--net", "true"],
                    capture_output=True, timeout=3,
                )
                if result.returncode == 0:
                    logger.info("Sandbox isolation: unshare (network only)")
                    return "unshare"
            except Exception:
                pass

        level = "warning" if _IS_LINUX else "info"
        getattr(logger, level)(
            "Sandbox isolation: ulimit only (no filesystem isolation). "
            "Install bubblewrap for proper sandboxing: apt-get install bubblewrap"
        )
        return "ulimit"

    async def execute(self, code: str, language: str = "python") -> SandboxResult:
        """Run code in an isolated subprocess."""
        if language not in ("python", "shell"):
            return SandboxResult(
                stdout="",
                stderr=f"Unsupported language: {language}",
                exit_code=1,
                timed_out=False,
            )

        with tempfile.TemporaryDirectory(prefix="odigos_sandbox_") as tmpdir:
            env = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": tmpdir,
                "TMPDIR": tmpdir,
                "LANG": "C.UTF-8",
            }

            if language == "python":
                cmd = self._build_python_cmd(code, tmpdir)
            else:
                cmd = self._build_shell_cmd(code, tmpdir)

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=tmpdir,
                    env=env,
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

    def _build_python_cmd(self, code: str, tmpdir: str) -> list[str]:
        inner = ["python3", "-c", code]
        return self._wrap_isolation(inner, tmpdir)

    def _build_shell_cmd(self, code: str, tmpdir: str) -> list[str]:
        inner = ["bash", "-c", f"set -euo pipefail; {code}"]
        return self._wrap_isolation(inner, tmpdir)

    def _wrap_isolation(self, inner_cmd: list[str], tmpdir: str) -> list[str]:
        """Wrap command with the best available isolation."""
        memory_kb = self.max_memory_mb * 1024
        ulimit_prefix = [
            "bash", "-c",
            f"ulimit -t {self.timeout} -v {memory_kb}; exec \"$@\"",
            "--",
        ]

        if self._isolation == "bwrap":
            # Full filesystem isolation: only /usr, /lib, /bin, /proc, /dev
            # User code has NO access to /app, /etc, /home, or host filesystem
            bwrap = [
                "bwrap",
                "--ro-bind", "/usr", "/usr",
                "--ro-bind", "/bin", "/bin",
                "--symlink", "/usr/lib", "/lib",
                "--symlink", "/usr/lib64", "/lib64",
                "--proc", "/proc",
                "--dev", "/dev",
                "--tmpfs", "/tmp",
                "--bind", tmpdir, "/sandbox",
                "--chdir", "/sandbox",
                "--unshare-all",
                "--die-with-parent",
                "--new-session",
            ]
            # Bind Python stdlib and site-packages
            # Python is in /usr/local in the Docker image
            if shutil.which("python3"):
                import sys
                prefix = sys.prefix
                if prefix.startswith("/usr/local"):
                    bwrap.extend(["--ro-bind", "/usr/local", "/usr/local"])
            # Also bind /lib and /lib64 if they're real directories (not symlinks)
            import os
            for libdir in ("/lib", "/lib64"):
                if os.path.isdir(libdir) and not os.path.islink(libdir):
                    bwrap.extend(["--ro-bind", libdir, libdir])
            if not self.allow_network:
                bwrap.append("--unshare-net")
            return [*bwrap, *ulimit_prefix, *inner_cmd]

        if self._isolation == "unshare" and not self.allow_network:
            return ["unshare", "--net", *ulimit_prefix, *inner_cmd]

        # Fallback: ulimit only
        return [*ulimit_prefix, *inner_cmd]

    def _truncate(self, text: str) -> str:
        if len(text) > self.max_output_chars:
            return text[: self.max_output_chars] + "\n[output truncated]"
        return text
