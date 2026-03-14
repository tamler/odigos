import logging
import os
import tempfile
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from odigos.channels.base import Channel, UniversalMessage
from odigos.core.agent_service import AgentService

logger = logging.getLogger(__name__)

DOCUMENT_DIR = os.path.join(tempfile.gettempdir(), "odigos")


class TelegramChannel(Channel):
    """Telegram bot channel using python-telegram-bot v21+."""

    channel_name = "telegram"

    def __init__(
        self,
        token: str,
        service: AgentService,
        mode: str = "polling",
        webhook_url: str = "",
    ) -> None:
        self.token = token
        self.service = service
        self.mode = mode
        self.webhook_url = webhook_url
        self._app: Application | None = None

    async def start(self) -> None:
        """Build and start the Telegram bot."""
        self._app = Application.builder().token(self.token).build()

        from telegram.ext import CommandHandler
        self._app.add_handler(CommandHandler("goals", self._handle_goals_command))
        self._app.add_handler(CommandHandler("todos", self._handle_todos_command))
        self._app.add_handler(CommandHandler("reminders", self._handle_reminders_command))
        self._app.add_handler(CommandHandler("cancel", self._handle_cancel_command))
        self._app.add_handler(CommandHandler("stop", self._handle_stop_command))
        self._app.add_handler(CommandHandler("start", self._handle_start_command))
        self._app.add_handler(CommandHandler("status", self._handle_status_command))

        self._app.add_handler(CallbackQueryHandler(self._handle_approval_callback, pattern=r"^approve:"))
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

    async def send_message(self, chat_id_or_conv: int | str, text: str) -> None:
        """Send a message. Accepts chat_id (int) or conversation_id (str like 'telegram:123')."""
        if not self._app:
            return
        if isinstance(chat_id_or_conv, str):
            chat_id = self._parse_chat_id(chat_id_or_conv)
            if chat_id is None:
                return
        else:
            chat_id = chat_id_or_conv
        await self._app.bot.send_message(chat_id=chat_id, text=text)

    @staticmethod
    def _parse_chat_id(conversation_id: str) -> int | None:
        parts = conversation_id.split(":", 1)
        if len(parts) == 2 and parts[0] == "telegram":
            try:
                return int(parts[1])
            except ValueError:
                return None
        return None

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
            response = await self.service.handle_message(message)
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
            response = await self.service.handle_message(message)
            await update.effective_message.reply_text(response)
        except Exception:
            logger.exception("Error handling document message")
            await update.effective_message.reply_text(
                "Something went wrong. Please try again."
            )

    async def _handle_goals_command(self, update: Update, context) -> None:
        """List active goals."""
        goals = await self.service.list_goals()
        if not goals:
            await update.effective_message.reply_text("No active goals.")
            return
        lines = []
        for g in goals:
            note = f" -- {g['progress_note']}" if g.get("progress_note") else ""
            lines.append(f"- [{g['id'][:8]}] {g['description']}{note}")
        await update.effective_message.reply_text("Active goals:\n" + "\n".join(lines))

    async def _handle_todos_command(self, update: Update, context) -> None:
        """List pending todos."""
        todos = await self.service.list_todos()
        if not todos:
            await update.effective_message.reply_text("No pending todos.")
            return
        lines = []
        for t in todos:
            sched = t.get("scheduled_at", "now")[:16] if t.get("scheduled_at") else "ASAP"
            lines.append(f"- [{t['id'][:8]}] {t['description']} (at {sched})")
        await update.effective_message.reply_text("Pending todos:\n" + "\n".join(lines))

    async def _handle_reminders_command(self, update: Update, context) -> None:
        """List pending reminders."""
        reminders = await self.service.list_reminders()
        if not reminders:
            await update.effective_message.reply_text("No pending reminders.")
            return
        lines = []
        for r in reminders:
            due = r.get("due_at", "")[:16] if r.get("due_at") else "now"
            recur = f" (recurring: {r['recurrence']})" if r.get("recurrence") else ""
            lines.append(f"- [{r['id'][:8]}] {r['description']} (due {due}){recur}")
        await update.effective_message.reply_text("Pending reminders:\n" + "\n".join(lines))

    async def _handle_cancel_command(self, update: Update, context) -> None:
        """Cancel a goal, todo, or reminder by ID."""
        if not context.args:
            await update.effective_message.reply_text("Usage: /cancel <id>")
            return
        item_id = context.args[0]
        # Support prefix matching
        for table_method in [self.service.list_goals, self.service.list_todos, self.service.list_reminders]:
            items = await table_method()
            matches = [i for i in items if i["id"].startswith(item_id)]
            if len(matches) == 1:
                await self.service.cancel_item(matches[0]["id"])
                await update.effective_message.reply_text(f"Cancelled: {matches[0]['id'][:8]}")
                return
            elif len(matches) > 1:
                await update.effective_message.reply_text(
                    f"Ambiguous ID '{item_id[:8]}' matches {len(matches)} items. Use more characters."
                )
                return
        # Try exact match
        result = await self.service.cancel_item(item_id)
        if result:
            await update.effective_message.reply_text(f"Cancelled: {item_id[:8]}")
        else:
            await update.effective_message.reply_text(f"Item {item_id[:8]} not found or already completed.")

    async def _handle_stop_command(self, update: Update, context) -> None:
        """Pause the heartbeat."""
        if self.service.heartbeat_paused is not None:
            self.service.pause_heartbeat()
            await update.effective_message.reply_text("Heartbeat paused.")
        else:
            await update.effective_message.reply_text("Heartbeat not available.")

    async def _handle_start_command(self, update: Update, context) -> None:
        """Resume the heartbeat."""
        if self.service.heartbeat_paused is not None:
            self.service.resume_heartbeat()
            await update.effective_message.reply_text("Heartbeat resumed.")
        else:
            await update.effective_message.reply_text("Heartbeat not available.")

    async def notify(self, title: str, body: str, conversation_id: str | None = None) -> None:
        """Send a notification to a Telegram chat."""
        if not self._app:
            return
        text = f"{title}\n\n{body}" if title else body
        if conversation_id:
            chat_id = self._parse_chat_id(conversation_id)
            if chat_id is not None:
                await self._app.bot.send_message(chat_id=chat_id, text=text[:4096])
        # If no conversation_id, we cannot broadcast to Telegram (no known chat IDs)

    async def send_approval_request(
        self, approval_id: str, tool_name: str, conversation_id: str, arguments: dict,
    ) -> None:
        """Send an inline keyboard asking the user to approve or deny a tool call."""
        if not self._app:
            return

        chat_id = self._parse_chat_id(conversation_id)
        if chat_id is None:
            return

        import json
        args_summary = json.dumps(arguments, indent=2)
        if len(args_summary) > 500:
            args_summary = args_summary[:500] + "\n..."

        text = (
            f"Approval needed: {tool_name}\n\n"
            f"{args_summary}\n\n"
            "Allow this action?"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Approve", callback_data=f"approve:{approval_id}:approved"),
                InlineKeyboardButton("Deny", callback_data=f"approve:{approval_id}:denied"),
            ]
        ])

        await self._app.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=keyboard,
        )

    async def _handle_approval_callback(self, update: Update, context) -> None:
        """Handle inline keyboard button presses for approval requests."""
        query = update.callback_query
        if not query or not query.data:
            return

        await query.answer()

        parts = query.data.split(":")
        if len(parts) != 3:
            return

        _, approval_id, decision = parts
        if decision not in ("approved", "denied"):
            return

        if self.service.resolve_approval(approval_id, decision):
            status = "Approved" if decision == "approved" else "Denied"
            await query.edit_message_text(f"{status}.")
        else:
            await query.edit_message_text("This approval request has expired.")

    async def _handle_status_command(self, update: Update, context) -> None:
        """Show agent status: budget, tasks, heartbeat."""
        lines = []

        # Budget
        status = await self.service.check_budget()
        daily_pct = (status.daily_spend / status.daily_limit * 100) if status.daily_limit else 0
        monthly_pct = (status.monthly_spend / status.monthly_limit * 100) if status.monthly_limit else 0
        lines.append("Budget:")
        lines.append(f"  Daily: ${status.daily_spend:.4f} / ${status.daily_limit:.2f} ({daily_pct:.0f}%)")
        lines.append(f"  Monthly: ${status.monthly_spend:.4f} / ${status.monthly_limit:.2f} ({monthly_pct:.0f}%)")
        if not status.within_budget:
            lines.append("  ** OVER BUDGET **")
        elif status.warning:
            lines.append("  ** Approaching limit **")

        # Goals/Todos/Reminders
        goals = await self.service.list_goals()
        todos = await self.service.list_todos()
        reminders = await self.service.list_reminders()
        lines.append(f"\nGoals: {len(goals)} active")
        lines.append(f"Todos: {len(todos)} pending")
        lines.append(f"Reminders: {len(reminders)} pending")

        # Heartbeat
        hb = self.service.heartbeat_paused
        if hb is not None:
            hb_status = "paused" if hb else "running"
            lines.append(f"Heartbeat: {hb_status}")
        else:
            lines.append("Heartbeat: not configured")

        await update.effective_message.reply_text("\n".join(lines))
