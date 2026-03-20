"""Email tools: check inbox (IMAP) and send email (SMTP)."""

from __future__ import annotations

import email
import email.mime.multipart
import email.mime.text
import email.mime.base
import email.utils
import imaplib
import logging
import smtplib
from email.header import decode_header
from pathlib import Path
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.config import EmailConfig

logger = logging.getLogger(__name__)


def _decode_header_value(value: str | None) -> str:
    """Decode an email header value (handles encoded words)."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _extract_text(msg: email.message.Message) -> str:
    """Extract plain text content from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        # Fallback to HTML if no plain text
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")[:2000]
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


class CheckEmailTool(BaseTool):
    name = "check_email"
    description = (
        "Check the email inbox for new messages. Returns a summary of unread emails "
        "including sender, subject, date, and a preview of the content. "
        "Use this to stay on top of incoming communications."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of emails to fetch (default: 10)",
            },
            "unread_only": {
                "type": "boolean",
                "description": "Only fetch unread emails (default: true)",
            },
        },
    }

    def __init__(self, email_config: EmailConfig) -> None:
        self._config = email_config

    async def execute(self, params: dict) -> ToolResult:
        if not self._config.enabled or not self._config.imap_host:
            return ToolResult(success=False, data="", error="Email not configured")

        limit = params.get("limit", 10)
        unread_only = params.get("unread_only", True)

        try:
            import asyncio
            result = await asyncio.to_thread(
                self._fetch_emails, limit, unread_only,
            )
            return result
        except Exception as e:
            logger.warning("Email check failed: %s", e)
            return ToolResult(success=False, data="", error=f"Failed to check email: {e}")

    def _fetch_emails(self, limit: int, unread_only: bool) -> ToolResult:
        """Synchronous IMAP fetch (run in thread)."""
        conn = imaplib.IMAP4_SSL(self._config.imap_host, self._config.imap_port)
        try:
            conn.login(self._config.username, self._config.password)
            conn.select("INBOX")

            search_criteria = "UNSEEN" if unread_only else "ALL"
            _, msg_ids = conn.search(None, search_criteria)
            ids = msg_ids[0].split()

            if not ids:
                return ToolResult(success=True, data="No new emails in inbox.")

            # Take the most recent N
            recent_ids = ids[-limit:]
            lines = [f"Found {len(ids)} {'unread ' if unread_only else ''}email(s). Showing {len(recent_ids)}:\n"]

            for msg_id in reversed(recent_ids):  # newest first
                _, data = conn.fetch(msg_id, "(RFC822)")
                raw = data[0][1]
                msg = email.message_from_bytes(raw)

                sender = _decode_header_value(msg.get("From"))
                subject = _decode_header_value(msg.get("Subject"))
                date = msg.get("Date", "")
                body = _extract_text(msg)[:500]

                lines.append(f"---")
                lines.append(f"From: {sender}")
                lines.append(f"Subject: {subject}")
                lines.append(f"Date: {date}")
                lines.append(f"Preview: {body[:300]}")
                lines.append("")

            return ToolResult(success=True, data="\n".join(lines))
        finally:
            try:
                conn.logout()
            except Exception:
                pass


class SendEmailTool(BaseTool):
    name = "send_email"
    description = (
        "Send an email. Provide recipient, subject, and body. "
        "The email will be sent from the agent's configured email address. "
        "Use this to respond to emails, send updates, or communicate on behalf of the user."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line",
            },
            "body": {
                "type": "string",
                "description": "Email body (plain text)",
            },
            "reply_to": {
                "type": "string",
                "description": "Optional: message ID to reply to (for threading)",
            },
        },
        "required": ["to", "subject", "body"],
    }

    def __init__(self, email_config: EmailConfig) -> None:
        self._config = email_config

    async def execute(self, params: dict) -> ToolResult:
        if not self._config.enabled or not self._config.smtp_host:
            return ToolResult(success=False, data="", error="Email not configured")

        to = params.get("to", "").strip()
        subject = params.get("subject", "").strip()
        body = params.get("body", "").strip()
        reply_to = params.get("reply_to")

        if not to or not subject or not body:
            return ToolResult(success=False, data="", error="to, subject, and body are required")

        # Basic email validation
        if "@" not in to or "." not in to.split("@")[-1]:
            return ToolResult(success=False, data="", error=f"Invalid email address: {to}")

        try:
            import asyncio
            await asyncio.to_thread(
                self._send_email, to, subject, body, reply_to,
            )
            logger.info("Email sent to %s: %s", to, subject[:50])
            return ToolResult(
                success=True,
                data=f"Email sent to {to} with subject: {subject}",
            )
        except Exception as e:
            logger.warning("Email send failed: %s", e)
            return ToolResult(success=False, data="", error=f"Failed to send email: {e}")

    def _send_email(self, to: str, subject: str, body: str, reply_to: str | None) -> None:
        """Synchronous SMTP send (run in thread)."""
        msg = email.mime.multipart.MIMEMultipart()
        msg["From"] = self._config.address
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)

        if reply_to:
            msg["In-Reply-To"] = reply_to
            msg["References"] = reply_to

        msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(self._config.smtp_host, self._config.smtp_port) as server:
            server.starttls()
            server.login(self._config.username, self._config.password)
            server.send_message(msg)
