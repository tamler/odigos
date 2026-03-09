"""Sample plugin: logs tool call and result events.

This plugin demonstrates the hook system. Each plugin exports a `hooks` dict
mapping event type strings to async callback functions.

Callback signature: async def callback(event_type, conversation_id, data) -> None
"""
import logging

logger = logging.getLogger("plugin.log_tools")


async def on_tool_call(event_type, conversation_id, data):
    logger.info(
        "[%s] Tool called: %s args=%s",
        conversation_id, data.get("tool"), data.get("arguments"),
    )


async def on_tool_result(event_type, conversation_id, data):
    logger.info(
        "[%s] Tool result: %s success=%s duration=%sms",
        conversation_id, data.get("tool"), data.get("success"), data.get("duration_ms"),
    )


hooks = {
    "tool_call": on_tool_call,
    "tool_result": on_tool_result,
}
