"""Plugin: logs tool call and result events via the tracer."""
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


def register(ctx):
    tracer = ctx.tracer
    if not tracer:
        return
    tracer.subscribe("tool_call", on_tool_call)
    tracer.subscribe("tool_result", on_tool_result)
