from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odigos.core.context import ContextAssembler
from odigos.core.planner import Plan
from odigos.providers.base import LLMProvider, LLMResponse

if TYPE_CHECKING:
    from odigos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Executor:
    """Runs the plan -- calls tools then LLM with results in context.

    Two-pass pattern:
    1. If plan requires tools, execute the tool and get results
    2. Call LLM with tool results injected into the system prompt
    """

    def __init__(
        self,
        provider: LLMProvider,
        context_assembler: ContextAssembler,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler
        self.tool_registry = tool_registry

    async def execute(
        self,
        conversation_id: str,
        message_content: str,
        plan: Plan | None = None,
    ) -> LLMResponse:
        if plan is None:
            plan = Plan(action="respond")

        tool_context = ""

        # If plan requires a tool, execute it
        if plan.action == "search" and self.tool_registry:
            tool = self.tool_registry.get("web_search")
            if tool:
                try:
                    result = await tool.execute(plan.tool_params)
                    if result.success:
                        tool_context = result.data
                    else:
                        logger.warning("Tool web_search failed: %s", result.error)
                except Exception:
                    logger.exception("Tool web_search raised an exception")

        messages = await self.context_assembler.build(
            conversation_id, message_content, tool_context=tool_context
        )
        return await self.provider.complete(messages)
