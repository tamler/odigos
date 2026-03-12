from __future__ import annotations

import json
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.core.agent_client import AgentClient


class MessagePeerTool(BaseTool):
    name = "message_peer"
    description = (
        "Send a message to a peer agent. Use this to communicate, "
        "request help, share knowledge, or delegate tasks to other agents."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "peer": {
                "type": "string",
                "description": "Name of the peer agent to message",
            },
            "message": {
                "type": "string",
                "description": "The message content to send",
            },
            "message_type": {
                "type": "string",
                "description": "Type of message: message, help_request, knowledge_share, task_delegation, status",
                "default": "message",
            },
        },
        "required": ["peer", "message"],
    }

    def __init__(self, peer_client: AgentClient) -> None:
        self.peer_client = peer_client

    async def execute(self, params: dict) -> ToolResult:
        peer = params.get("peer")
        message = params.get("message")

        if not peer:
            return ToolResult(success=False, data="", error="Missing required parameter: peer")
        if not message:
            return ToolResult(success=False, data="", error="Missing required parameter: message")

        message_type = params.get("message_type", "message")

        try:
            result = await self.peer_client.send(
                peer, message, message_type=message_type, metadata=None,
            )
        except ValueError as exc:
            return ToolResult(success=False, data=str(exc), error=str(exc))

        return ToolResult(success=True, data=json.dumps(result))
