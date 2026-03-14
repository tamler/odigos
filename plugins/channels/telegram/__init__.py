"""Telegram bot channel plugin.

Registers the Telegram channel when telegram_bot_token is configured.
Loaded in phase 2 (after AgentService is available).
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.telegram_bot_token:
        logger.info("Telegram plugin skipped: no telegram_bot_token configured")
        return {"status": "available", "error_message": "No telegram_bot_token configured"}

    if not ctx.service:
        logger.warning("Telegram plugin skipped: AgentService not available (wrong loading phase?)")
        return {"status": "error", "error_message": "AgentService not available"}

    from odigos.channels.telegram import TelegramChannel

    telegram_channel = TelegramChannel(
        token=settings.telegram_bot_token,
        service=ctx.service,
        mode=settings.telegram.mode,
        webhook_url=settings.telegram.webhook_url,
    )
    ctx.register_channel("telegram", telegram_channel)
    logger.info("Telegram channel plugin loaded")
