"""Web platform access via opencli-rs (optional, auto-detected)."""
from __future__ import annotations

import asyncio
import logging
import shutil

from odigos.tools.base import BaseTool, ToolContract, ToolResult
from odigos.tools.gate import ToolGate

logger = logging.getLogger(__name__)

OPENCLI_BIN = shutil.which("opencli-rs") or shutil.which("opencli")

PLATFORMS = [
    "twitter", "reddit", "youtube", "hackernews", "bilibili", "zhihu",
    "weibo", "douban", "xiaohongshu", "medium", "substack", "linkedin",
    "facebook", "instagram", "tiktok", "wikipedia", "arxiv", "stackoverflow",
    "devto", "lobsters", "bbc", "google", "yahoo-finance", "xueqiu",
    "notion", "discord", "cursor", "jike", "weread",
]


class WebPlatformTool(BaseTool):
    name = "web_platform"
    gate = ToolGate.config("opencli")
    category = "search"
    contract = ToolContract(timeout_seconds=30)
    description = (
        "Access 55+ web platforms (Twitter/X, Reddit, YouTube, HackerNews, "
        "Wikipedia, LinkedIn, Instagram, TikTok, Yahoo Finance, etc.) via opencli-rs. "
        "Search content, read feeds, check trending topics, get stock quotes. "
        "Uses your browser's logged-in sessions — no API keys needed."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "platform": {
                "type": "string",
                "enum": PLATFORMS,
                "description": "Target platform",
            },
            "command": {
                "type": "string",
                "description": (
                    "Subcommand and options, e.g. 'search --query AI agents', "
                    "'hot --limit 10', 'timeline', 'quote --symbol AAPL'"
                ),
            },
        },
        "required": ["platform", "command"],
    }

    async def execute(self, params: dict) -> ToolResult:
        params.pop("_conversation_id", None)
        params.pop("_goal_id", None)

        if not OPENCLI_BIN:
            return ToolResult(success=False, data="", error="opencli-rs not installed")

        platform = params.get("platform", "")
        command = params.get("command", "")
        if not platform or not command:
            return ToolResult(success=False, data="", error="platform and command required")

        if platform not in PLATFORMS:
            return ToolResult(success=False, data="", error=f"Unknown platform: {platform}")

        import shlex

        from odigos.tools.arg_guard import ArgGuardError, reject_dangerous_args
        try:
            args = shlex.split(command)
        except ValueError as exc:
            return ToolResult(success=False, data="", error=f"Invalid command syntax: {exc}")
        try:
            reject_dangerous_args(args)
        except ArgGuardError as exc:
            return ToolResult(success=False, data="", error=str(exc))
        # Always request JSON for structured output
        if "--format" not in args:
            args.extend(["--format", "json"])

        try:
            proc = await asyncio.create_subprocess_exec(
                OPENCLI_BIN, platform, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=25)

            if proc.returncode != 0:
                err = stderr.decode().strip() or f"Exit code {proc.returncode}"
                return ToolResult(success=False, data="", error=err[:500])

            output = stdout.decode().strip()
            if len(output) > 8000:
                output = output[:8000] + "\n\n[Truncated]"

            return ToolResult(success=True, data=output)

        except asyncio.TimeoutError:
            return ToolResult(success=False, data="", error="Command timed out (25s)")
        except Exception as e:
            return ToolResult(success=False, data="", error=str(e)[:500])
