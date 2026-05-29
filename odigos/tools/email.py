"""Email tools using imap-tools (IMAP) and smtplib (SMTP).

Full capabilities: check inbox, search, read full messages, send with
CC/BCC/HTML/attachments. Works with any IMAP/SMTP provider.
"""
from __future__ import annotations

import asyncio
import email.mime.multipart
import email.mime.text
import logging
import smtplib
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolContract, ToolResult
from odigos.tools.content_filter_helper import filter_external_content
from odigos.tools.gate import ToolGate

if TYPE_CHECKING:
    from odigos.config import EmailConfig

logger = logging.getLogger(__name__)


class CheckEmailTool(BaseTool):
    name = "check_email"
    gate = ToolGate.config("email.imap_host")
    category = "communication"
    contract = ToolContract(timeout_seconds=30, max_retries={"transient": 2, "input": 0, "permission": 0, "unavailable": 0, "unknown": 1})
    description = (
        "Check the email inbox for new messages. Returns subject, sender, date, preview, and UID. "
        "Use when the user asks about their email. "
        "Do not use for searching old emails — use search_email instead."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max emails to fetch (default 10)"},
            "unread_only": {"type": "string", "enum": ["true", "false"], "description": "Only unread emails (default 'true')"},
            "folder": {"type": "string", "description": "Folder to check (default INBOX)"},
        },
    }

    def __init__(self, email_config: "EmailConfig") -> None:
        self._config = email_config

    async def execute(self, params: dict) -> ToolResult:
        if not self._config.imap_host:
            return ToolResult(success=False, data="", error="Email not configured")
        params.pop("_conversation_id", None)
        params.pop("_goal_id", None)
        try:
            unread_only = str(params.get("unread_only", "true")).lower() == "true"
            return await asyncio.to_thread(
                self._fetch, params.get("limit", 10), unread_only, params.get("folder", "INBOX"),
            )
        except Exception as e:
            return ToolResult(success=False, data="", error=f"Email check failed: {e}")

    def _fetch(self, limit: int, unread_only: bool, folder: str) -> ToolResult:
        from imap_tools import MailBox, AND
        with MailBox(self._config.imap_host, self._config.imap_port).login(
            self._config.username, self._config.password, initial_folder=folder
        ) as mb:
            criteria = AND(seen=False) if unread_only else "ALL"
            msgs = list(mb.fetch(criteria, limit=limit, reverse=True, mark_seen=False))
            if not msgs:
                return ToolResult(success=True, data="No new emails.")
            lines = [f"Found {len(msgs)} email(s):\n"]
            for msg in msgs:
                lines.append("---")
                lines.append(f"From: {msg.from_}")
                lines.append(f"Subject: {msg.subject}")
                lines.append(f"Date: {msg.date}")
                lines.append(f"Preview: {(msg.text or msg.html or '')[:300]}")
                if msg.attachments:
                    lines.append(f"Attachments: {', '.join(a.filename for a in msg.attachments)}")
                lines.append(f"UID: {msg.uid}")
                lines.append("")
            return filter_external_content("\n".join(lines), "email inbox")


class SearchEmailTool(BaseTool):
    name = "search_email"
    gate = ToolGate.config("email.imap_host")
    category = "communication"
    contract = ToolContract(timeout_seconds=30)
    description = (
        "Search emails by sender, subject, keyword, or date range. "
        "Use to find specific emails. Do not use for checking latest unread — use check_email."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "from_address": {"type": "string", "description": "Filter by sender address"},
            "subject": {"type": "string", "description": "Filter by subject"},
            "keyword": {"type": "string", "description": "Search in body text"},
            "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
            "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"},
            "folder": {"type": "string", "description": "Folder to search (default INBOX)"},
            "limit": {"type": "integer", "description": "Max results (default 10)"},
        },
    }

    def __init__(self, email_config: "EmailConfig") -> None:
        self._config = email_config

    async def execute(self, params: dict) -> ToolResult:
        if not self._config.imap_host:
            return ToolResult(success=False, data="", error="Email not configured")
        params.pop("_conversation_id", None)
        params.pop("_goal_id", None)
        try:
            return await asyncio.to_thread(self._search, params)
        except Exception as e:
            return ToolResult(success=False, data="", error=f"Email search failed: {e}")

    def _search(self, params: dict) -> ToolResult:
        from imap_tools import MailBox, AND
        from datetime import date
        folder = params.get("folder", "INBOX")
        limit = params.get("limit", 10)
        kwargs = {}
        if params.get("from_address"):
            kwargs["from_"] = params["from_address"]
        if params.get("subject"):
            kwargs["subject"] = params["subject"]
        if params.get("keyword"):
            kwargs["body"] = params["keyword"]
        if params.get("date_from"):
            y, m, d = params["date_from"].split("-")
            kwargs["date_gte"] = date(int(y), int(m), int(d))
        if params.get("date_to"):
            y, m, d = params["date_to"].split("-")
            kwargs["date_lt"] = date(int(y), int(m), int(d))
        criteria = AND(**kwargs) if kwargs else "ALL"
        with MailBox(self._config.imap_host, self._config.imap_port).login(
            self._config.username, self._config.password, initial_folder=folder
        ) as mb:
            msgs = list(mb.fetch(criteria, limit=limit, reverse=True, mark_seen=False))
            if not msgs:
                return ToolResult(success=True, data="No emails matching your search.")
            lines = [f"Found {len(msgs)} result(s):\n"]
            for msg in msgs:
                lines.append(f"**{msg.subject}** from {msg.from_} ({msg.date}) [UID: {msg.uid}]")
                preview = (msg.text or "")[:150]
                if preview:
                    lines.append(f"  {preview}")
                lines.append("")
            return filter_external_content("\n".join(lines), "email search")


class ReadEmailTool(BaseTool):
    name = "read_email"
    gate = ToolGate.config("email.imap_host")
    category = "communication"
    contract = ToolContract(timeout_seconds=30)
    description = (
        "Read the full content of a specific email by its UID. "
        "Use after check_email or search_email to read the complete message."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "uid": {"type": "string", "description": "Email UID from check_email or search_email"},
            "folder": {"type": "string", "description": "Folder (default INBOX)"},
            "mark_read": {"type": "string", "enum": ["true", "false"], "description": "Mark as read (default 'true')"},
        },
        "required": ["uid"],
    }

    def __init__(self, email_config: "EmailConfig") -> None:
        self._config = email_config

    async def execute(self, params: dict) -> ToolResult:
        if not self._config.imap_host:
            return ToolResult(success=False, data="", error="Email not configured")
        params.pop("_conversation_id", None)
        params.pop("_goal_id", None)
        try:
            return await asyncio.to_thread(self._read, params)
        except Exception as e:
            return ToolResult(success=False, data="", error=f"Email read failed: {e}")

    def _read(self, params: dict) -> ToolResult:
        from imap_tools import MailBox, AND
        uid = params.get("uid", "")
        folder = params.get("folder", "INBOX")
        mark_read = str(params.get("mark_read", "true")).lower() == "true"
        with MailBox(self._config.imap_host, self._config.imap_port).login(
            self._config.username, self._config.password, initial_folder=folder
        ) as mb:
            msgs = list(mb.fetch(f"UID {uid}", mark_seen=mark_read))
            if not msgs:
                return ToolResult(success=False, data="", error=f"Email UID {uid} not found")
            msg = msgs[0]
            lines = [
                f"From: {msg.from_}",
                f"To: {', '.join(msg.to)}",
                f"Subject: {msg.subject}",
                f"Date: {msg.date}",
            ]
            if msg.cc:
                lines.append(f"CC: {', '.join(msg.cc)}")
            lines.append("")
            lines.append((msg.text or msg.html or "(no body)")[:4000])
            if msg.attachments:
                lines.append(f"\nAttachments ({len(msg.attachments)}):")
                for att in msg.attachments:
                    lines.append(f"  - {att.filename} ({att.content_type}, {len(att.payload)} bytes)")
            return filter_external_content("\n".join(lines), "email message")


class SendEmailTool(BaseTool):
    name = "send_email"
    gate = ToolGate.config("email.imap_host")
    category = "communication"
    description = (
        "Send an email with optional CC, BCC, and HTML body. "
        "Use to respond to emails or send messages on behalf of the user."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient(s), comma-separated"},
            "subject": {"type": "string", "description": "Subject line"},
            "body": {"type": "string", "description": "Plain text body"},
            "html": {"type": "string", "description": "HTML body (optional, alongside plain text)"},
            "cc": {"type": "string", "description": "CC recipients, comma-separated"},
            "bcc": {"type": "string", "description": "BCC recipients, comma-separated"},
            "reply_to": {"type": "string", "description": "Message-ID to reply to (threading)"},
        },
        "required": ["to", "subject", "body"],
    }

    def __init__(self, email_config: "EmailConfig") -> None:
        self._config = email_config

    async def execute(self, params: dict) -> ToolResult:
        if not self._config.smtp_host:
            return ToolResult(success=False, data="", error="Email not configured")
        params.pop("_conversation_id", None)
        params.pop("_goal_id", None)
        to = params.get("to", "").strip()
        subject = params.get("subject", "").strip()
        body = params.get("body", "").strip()
        if not to or not subject or not body:
            return ToolResult(success=False, data="", error="to, subject, and body required")
        from email_validator import validate_email, EmailNotValidError
        recipients = [r.strip() for r in to.split(",")]
        for r in recipients:
            try:
                validate_email(r, check_deliverability=False)
            except EmailNotValidError as e:
                return ToolResult(success=False, data="", error=f"Invalid email: {r} ({e})")
        try:
            await asyncio.to_thread(self._send, params, recipients)
            return ToolResult(success=True, data=f"Email sent to {to}")
        except Exception as e:
            return ToolResult(success=False, data="", error=f"Send failed: {e}")

    def _send(self, params: dict, recipients: list[str]) -> None:
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["From"] = self._config.address or self._config.username
        msg["To"] = params["to"]
        msg["Subject"] = params["subject"]
        if params.get("cc"):
            msg["Cc"] = params["cc"]
            recipients.extend(r.strip() for r in params["cc"].split(","))
        if params.get("reply_to"):
            msg["In-Reply-To"] = params["reply_to"]
            msg["References"] = params["reply_to"]
        msg.attach(email.mime.text.MIMEText(params["body"], "plain"))
        if params.get("html"):
            msg.attach(email.mime.text.MIMEText(params["html"], "html"))
        bcc = [r.strip() for r in params.get("bcc", "").split(",") if r.strip()]
        port = self._config.smtp_port
        if port == 465:
            with smtplib.SMTP_SSL(self._config.smtp_host, port) as server:
                server.login(self._config.username, self._config.password)
                server.sendmail(msg["From"], recipients + bcc, msg.as_string())
        else:
            with smtplib.SMTP(self._config.smtp_host, port) as server:
                server.starttls()
                server.login(self._config.username, self._config.password)
                server.sendmail(msg["From"], recipients + bcc, msg.as_string())
