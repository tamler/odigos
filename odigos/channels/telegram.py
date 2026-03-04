import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, MessageHandler, filters

from odigos.channels.base import Channel, UniversalMessage
from odigos.core.agent import Agent

logger = logging.getLogger(__name__)


class TelegramChannel(Channel):
    """Telegram bot channel using python-telegram-bot v21+."""

    def __init__(
        self,
        token: str,
        agent: Agent,
        mode: str = "polling",
        webhook_url: str = "",
    ) -> None:
        self.token = token
        self.agent = agent
        self.mode = mode
        self.webhook_url = webhook_url
        self._app: Application | None = None

    async def start(self) -> None:
        """Build and start the Telegram bot."""
        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text)
        )

        await self._app.initialize()

        if self.mode == "webhook" and self.webhook_url:
            await self._app.bot.set_webhook(self.webhook_url)
            logger.info("Telegram bot started in webhook mode")
        else:
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot started in polling mode")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._app:
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            if self._app.running:
                await self._app.stop()
            await self._app.shutdown()

    async def _handle_text(self, update: Update, context) -> None:
        """Handle incoming text messages."""
        if not update.effective_message or not update.effective_message.text:
            return

        # Show typing indicator
        try:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action=ChatAction.TYPING
            )
        except Exception:
            pass  # typing indicator is best-effort

        # Convert to UniversalMessage
        message = UniversalMessage(
            id=str(update.effective_message.message_id),
            channel="telegram",
            sender=str(update.effective_user.id),
            content=update.effective_message.text,
            timestamp=datetime.now(timezone.utc),
            metadata={
                "chat_id": update.effective_chat.id,
                "username": getattr(update.effective_user, "username", None),
            },
        )

        try:
            response = await self.agent.handle_message(message)
            await update.effective_message.reply_text(response)
        except Exception:
            logger.exception("Error handling message")
            await update.effective_message.reply_text(
                "Something went wrong. Please try again."
            )
