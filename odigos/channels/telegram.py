import logging
import os
import tempfile
from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, MessageHandler, filters

from odigos.channels.base import Channel, UniversalMessage
from odigos.core.agent import Agent

logger = logging.getLogger(__name__)

DOCUMENT_DIR = os.path.join(tempfile.gettempdir(), "odigos")


class TelegramChannel(Channel):
    """Telegram bot channel using python-telegram-bot v21+."""

    def __init__(
        self,
        token: str,
        agent: Agent,
        mode: str = "polling",
        webhook_url: str = "",
        scheduler=None,
        heartbeat=None,
    ) -> None:
        self.token = token
        self.agent = agent
        self.mode = mode
        self.webhook_url = webhook_url
        self._app: Application | None = None
        self.scheduler = scheduler
        self.heartbeat = heartbeat

    async def start(self) -> None:
        """Build and start the Telegram bot."""
        self._app = Application.builder().token(self.token).build()

        from telegram.ext import CommandHandler
        self._app.add_handler(CommandHandler("tasks", self._handle_tasks_command))
        self._app.add_handler(CommandHandler("cancel", self._handle_cancel_command))
        self._app.add_handler(CommandHandler("stop", self._handle_stop_command))
        self._app.add_handler(CommandHandler("start", self._handle_start_command))

        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        self._app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))

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

    async def send_message(self, chat_id: int, text: str) -> None:
        """Send a message to a specific chat."""
        if self._app:
            await self._app.bot.send_message(chat_id=chat_id, text=text)

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
            await update.effective_message.reply_text("Something went wrong. Please try again.")

    async def _handle_document(self, update: Update, context) -> None:
        """Handle incoming document/file messages."""
        if not update.effective_message or not update.effective_message.document:
            return

        try:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action=ChatAction.TYPING
            )
        except Exception:
            pass

        doc = update.effective_message.document
        os.makedirs(DOCUMENT_DIR, exist_ok=True)
        file_path = os.path.join(
            DOCUMENT_DIR, doc.file_name or f"file_{update.effective_message.message_id}"
        )

        try:
            tg_file = await context.bot.get_file(doc.file_id)
            await tg_file.download_to_drive(file_path)
        except Exception:
            logger.exception("Failed to download document")
            await update.effective_message.reply_text(
                "Failed to download the file. Please try again."
            )
            return

        content = update.effective_message.caption or "Process this document"

        message = UniversalMessage(
            id=str(update.effective_message.message_id),
            channel="telegram",
            sender=str(update.effective_user.id),
            content=content,
            timestamp=datetime.now(timezone.utc),
            metadata={
                "chat_id": update.effective_chat.id,
                "username": getattr(update.effective_user, "username", None),
                "file_path": file_path,
            },
        )

        try:
            response = await self.agent.handle_message(message)
            await update.effective_message.reply_text(response)
        except Exception:
            logger.exception("Error handling document message")
            await update.effective_message.reply_text(
                "Something went wrong. Please try again."
            )

    async def _handle_tasks_command(self, update: Update, context) -> None:
        """List pending tasks."""
        if not self.scheduler:
            await update.effective_message.reply_text("Task scheduler not available.")
            return
        tasks = await self.scheduler.list_pending(limit=10)
        if not tasks:
            await update.effective_message.reply_text("No pending tasks.")
            return
        lines = []
        for t in tasks:
            sched = t.get("scheduled_at", "now")[:16] if t.get("scheduled_at") else "ASAP"
            lines.append(f"- [{t['id'][:8]}] {t['description']} (at {sched})")
        await update.effective_message.reply_text("Pending tasks:\n" + "\n".join(lines))

    async def _handle_cancel_command(self, update: Update, context) -> None:
        """Cancel a task by ID."""
        if not self.scheduler:
            await update.effective_message.reply_text("Task scheduler not available.")
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /cancel <task_id>")
            return
        task_id_input = context.args[0]
        # Support prefix matching for truncated IDs shown by /tasks
        tasks = await self.scheduler.list_pending()
        matches = [t for t in tasks if t["id"].startswith(task_id_input)]
        if len(matches) == 1:
            task_id = matches[0]["id"]
            await self.scheduler.cancel(task_id)
            await update.effective_message.reply_text(f"Task {task_id[:8]} cancelled.")
        elif len(matches) > 1:
            await update.effective_message.reply_text(
                f"Ambiguous ID '{task_id_input[:8]}' matches {len(matches)} tasks. Use more characters."
            )
        else:
            # Try exact match (might be completed/failed task)
            result = await self.scheduler.cancel(task_id_input)
            if result:
                await update.effective_message.reply_text(f"Task {task_id_input[:8]} cancelled.")
            else:
                await update.effective_message.reply_text(
                    f"Task {task_id_input[:8]} not found or already completed."
                )

    async def _handle_stop_command(self, update: Update, context) -> None:
        """Pause the heartbeat."""
        if self.heartbeat:
            self.heartbeat.paused = True
            await update.effective_message.reply_text("Heartbeat paused.")
        else:
            await update.effective_message.reply_text("Heartbeat not available.")

    async def _handle_start_command(self, update: Update, context) -> None:
        """Resume the heartbeat."""
        if self.heartbeat:
            self.heartbeat.paused = False
            await update.effective_message.reply_text("Heartbeat resumed.")
        else:
            await update.effective_message.reply_text("Heartbeat not available.")
