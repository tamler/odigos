"""Agent Browser automation plugin.

Registers the run_browser tool when browser.enabled is true and agent-browser CLI is installed.
Install CLI: npm install -g @anthropic-ai/agent-browser
"""
import logging
import shutil

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.browser.enabled:
        return

    if not shutil.which("agent-browser"):
        logger.warning(
            "Browser enabled but agent-browser CLI not found. "
            "Install: npm install -g @anthropic-ai/agent-browser"
        )
        return

    from odigos.tools.browser import BrowserTool

    browser_tool = BrowserTool(timeout=settings.browser.timeout)
    ctx.register_tool(browser_tool)
    logger.info("Agent Browser plugin loaded")
