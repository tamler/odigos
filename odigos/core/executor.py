from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from odigos.core.context import ContextAssembler
from odigos.core.planner import Plan
from odigos.providers.base import LLMProvider, LLMResponse

if TYPE_CHECKING:
    from odigos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ExecuteResult:
    """Result from executor: LLM response + optional metadata from tool execution."""

    response: LLMResponse
    scrape_metadata: dict | None = None


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
    ) -> ExecuteResult:
        if plan is None:
            plan = Plan(action="respond")

        tool_context = ""
        scrape_metadata = None

        # Map plan actions to tool names
        _ACTION_TOOLS = {
            "search": "web_search",
            "scrape": "read_page",
        }

        tool_name = _ACTION_TOOLS.get(plan.action)
        if tool_name and self.tool_registry:
            tool = self.tool_registry.get(tool_name)
            if tool:
                try:
                    result = await tool.execute(plan.tool_params)
                    if result.success:
                        tool_context = result.data
                        if plan.action == "scrape":
                            scrape_metadata = {
                                "url": plan.tool_params.get("url", ""),
                                "title": "",
                                "content": tool_context,
                            }
                    else:
                        logger.warning("Tool %s failed: %s", tool_name, result.error)
                except Exception:
                    logger.exception("Tool %s raised an exception", tool_name)

        messages = await self.context_assembler.build(
            conversation_id, message_content, tool_context=tool_context
        )
        response = await self.provider.complete(messages)
        return ExecuteResult(response=response, scrape_metadata=scrape_metadata)
