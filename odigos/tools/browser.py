from __future__ import annotations

import shlex

from odigos.security.events import log_security_event
from odigos.tools.base import ToolResult
from odigos.tools.gate import ToolGate
from odigos.tools.subprocess_tool import SubprocessTool
from odigos.tools.url_guard import is_blocked_url

_BROWSER_ALLOWED_SUBCOMMANDS = {
    "navigate", "click", "type", "screenshot", "extract",
    "scroll", "wait", "select", "hover", "back", "forward",
    "refresh", "evaluate", "pdf", "close",
}


class BrowserTool(SubprocessTool):
    """Execute browser automation commands via the agent-browser CLI."""

    name = "run_browser"
    gate = ToolGate.plugin("browser")

    def __init__(self, timeout: int = 120) -> None:
        super().__init__(
            binary_name="agent-browser",
            description=(
                "Control a headless browser to interact with web pages. Supports navigating, "
                "clicking, typing, scrolling, taking screenshots, and extracting page content. "
                "Pass the agent-browser subcommand and arguments. "
                "Example: navigate --url 'https://example.com'"
            ),
            default_timeout=timeout,
            allowed_subcommands=_BROWSER_ALLOWED_SUBCOMMANDS,
            install_hint="npm install -g @anthropic-ai/agent-browser",
        )

    async def execute(self, params: dict) -> ToolResult:
        command = (params.get("command") or "").strip()
        try:
            args = shlex.split(command)
        except ValueError as exc:
            return ToolResult(success=False, data="", error=f"Invalid command syntax: {exc}")
        for i, tok in enumerate(args):
            candidate = None
            if tok in ("--url", "-u") and i + 1 < len(args):
                candidate = args[i + 1]
            elif tok.startswith("--url="):
                candidate = tok.split("=", 1)[1]
            elif "://" in tok:
                candidate = tok
            if candidate and is_blocked_url(candidate):
                log_security_event("ssrf_blocked", candidate)
                return ToolResult(
                    success=False, data="",
                    error=f"Blocked URL (private/internal): {candidate}",
                )
        return await super().execute(params)
