"""Notification tool -- push messages to the user across all channels."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.core.notifier import Notifier

logger = logging.getLogger(__name__)


class NotifyTool(BaseTool):
    """Send a notification to the user across all connected channels."""

    name = "send_notification"
    description = (
        "Send a notification message to the user. Use for important updates: "
        "task completions, warnings, reminders, or anything the user should know "
        "without waiting for them to ask. Don't overuse -- only notify when "
        "the information is timely and actionable."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The notification message to send.",
            },
            "priority": {
                "type": "string",
                "enum": ["info", "warning", "urgent"],
                "description": "Notification priority. info=general update, warning=needs attention, urgent=action required.",
            },
        },
        "required": ["message"],
    }

    def __init__(self, notifier: Notifier) -> None:
        self._notifier = notifier

    async def execute(self, params: dict) -> ToolResult:
        message = params.get("message")
        if not message:
            return ToolResult(success=False, data="", error="No message provided")

        priority = params.get("priority", "info")
        title = {
            "info": "Update",
            "warning": "Warning",
            "urgent": "Action Required",
        }.get(priority, "Update")

        try:
            await self._notifier.notify(title=title, body=message)
            return ToolResult(success=True, data=f"Notification sent: {message}")
        except Exception as e:
            return ToolResult(success=False, data="", error=str(e))
