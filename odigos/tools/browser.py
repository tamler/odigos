from __future__ import annotations

from odigos.tools.subprocess_tool import SubprocessTool

_BROWSER_ALLOWED_SUBCOMMANDS = {
    "navigate", "click", "type", "screenshot", "extract",
    "scroll", "wait", "select", "hover", "back", "forward",
    "refresh", "evaluate", "pdf", "close",
}


class BrowserTool(SubprocessTool):
    """Execute browser automation commands via the agent-browser CLI."""

    def __init__(self, timeout: int = 120) -> None:
        super().__init__(
            binary_name="agent-browser",
            tool_name="run_browser",
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
