"""Google Workspace plugin.

Registers the run_gws tool when gws.enabled is true and the gws CLI is installed.
Install CLI: npm install -g @googleworkspace/cli
"""
import logging
import shutil

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.gws.enabled:
        return

    if not shutil.which("gws"):
        logger.warning(
            "GWS enabled but gws CLI not found. "
            "Install: npm install -g @googleworkspace/cli"
        )
        return

    from odigos.tools.gws import GWSTool

    gws_tool = GWSTool(timeout=settings.gws.timeout)
    ctx.register_tool(gws_tool)
    logger.info("Google Workspace plugin loaded (gws CLI)")
