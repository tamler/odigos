from __future__ import annotations

from odigos.tools.subprocess_tool import SubprocessTool

_GWS_ALLOWED_SUBCOMMANDS = {
    "gmail", "calendar", "drive", "sheets", "docs", "slides",
    "forms", "chat", "admin", "tasks", "people", "vault",
}


class GWSTool(SubprocessTool):
    """Execute Google Workspace commands via the gws CLI."""

    def __init__(self, timeout: int = 30) -> None:
        super().__init__(
            binary_name="gws",
            tool_name="run_gws",
            description=(
                "Run a Google Workspace CLI command. Supports Gmail, Calendar, Drive, "
                "Sheets, and all other Workspace APIs. Pass the gws subcommand and arguments. "
                "Example: drive files list --params '{\"pageSize\": 5}'"
            ),
            default_timeout=timeout,
            allowed_subcommands=_GWS_ALLOWED_SUBCOMMANDS,
            install_hint="npm install -g @googleworkspace/cli",
        )
