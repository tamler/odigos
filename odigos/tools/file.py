from __future__ import annotations

import logging
from pathlib import Path

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MAX_READ_SIZE = 500_000  # 500KB


class FileTool(BaseTool):
    """Read, write, and list files within configured allowed paths."""

    name = "file"
    description = (
        "Read, write, or list files. Operations: read (returns text content), "
        "write (creates or overwrites a file), list (shows directory contents). "
        "Only works within allowed directories."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "write", "list"],
                "description": "The file operation to perform",
            },
            "path": {
                "type": "string",
                "description": "File or directory path",
            },
            "content": {
                "type": "string",
                "description": "Content to write (only for write operation)",
            },
        },
        "required": ["operation", "path"],
    }

    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        self._allowed = [
            Path(p).expanduser().resolve() for p in (allowed_paths or ["data/files"])
        ]

    def _validate_path(self, path_str: str) -> tuple[Path, str | None]:
        """Resolve path and check it's within allowed directories."""
        try:
            resolved = Path(path_str).expanduser().resolve()
        except (ValueError, OSError) as e:
            return Path(), f"Invalid path: {e}"

        for allowed in self._allowed:
            try:
                resolved.relative_to(allowed)
                return resolved, None
            except ValueError:
                continue

        return resolved, f"Path not within allowed directories: {self._allowed}"

    async def execute(self, params: dict) -> ToolResult:
        operation = params.get("operation", "").strip()
        path_str = params.get("path", "").strip()

        if not operation:
            return ToolResult(success=False, data="", error="Missing required parameter: operation")
        if not path_str:
            return ToolResult(success=False, data="", error="Missing required parameter: path")

        resolved, err = self._validate_path(path_str)
        if err:
            return ToolResult(success=False, data="", error=err)

        if operation == "read":
            return await self._read(resolved)
        elif operation == "write":
            content = params.get("content", "")
            return await self._write(resolved, content)
        elif operation == "list":
            return await self._list(resolved)
        else:
            return ToolResult(success=False, data="", error=f"Unknown operation: {operation}")

    async def _read(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, data="", error=f"File not found: {path}")
        if not path.is_file():
            return ToolResult(success=False, data="", error=f"Not a file: {path}")
        try:
            data = path.read_bytes()
            if b"\x00" in data[:8192]:
                return ToolResult(success=False, data="", error="Binary file — cannot read as text")
            if len(data) > MAX_READ_SIZE:
                text = data[:MAX_READ_SIZE].decode("utf-8", errors="replace")
                return ToolResult(success=True, data=text + "\n\n[truncated]")
            return ToolResult(success=True, data=data.decode("utf-8", errors="replace"))
        except Exception as e:
            return ToolResult(success=False, data="", error=str(e))

    async def _write(self, path: Path, content: str) -> ToolResult:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _, err = self._validate_path(str(path.parent.resolve()))
            if err:
                return ToolResult(success=False, data="", error=err)
            path.write_text(content)
            return ToolResult(success=True, data=f"Written {len(content)} chars to {path}")
        except Exception as e:
            return ToolResult(success=False, data="", error=str(e))

    async def _list(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, data="", error=f"Directory not found: {path}")
        if not path.is_dir():
            return ToolResult(success=False, data="", error=f"Not a directory: {path}")
        lines = []
        for entry in sorted(path.iterdir()):
            if entry.is_file():
                size = entry.stat().st_size
                lines.append(f"  {entry.name}  ({size} bytes)")
            elif entry.is_dir():
                lines.append(f"  {entry.name}/")
        if not lines:
            return ToolResult(success=True, data="(empty directory)")
        return ToolResult(success=True, data="\n".join(lines))
