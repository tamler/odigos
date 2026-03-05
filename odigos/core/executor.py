from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from odigos.core.context import ContextAssembler
from odigos.core.planner import Plan
from odigos.providers.base import LLMProvider, LLMResponse

if TYPE_CHECKING:
    from odigos.core.scheduler import TaskScheduler
    from odigos.skills.registry import SkillRegistry
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
        skill_registry: SkillRegistry | None = None,
        scheduler: TaskScheduler | None = None,
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.scheduler = scheduler

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

        # Handle schedule action directly (no LLM call needed)
        if plan.action == "schedule" and self.scheduler:
            description = plan.tool_params.get("description", "")
            await self.scheduler.create(
                description=description,
                delay_seconds=plan.schedule_seconds or 0,
                recurrence_seconds=plan.recurrence_seconds,
                conversation_id=conversation_id,
            )
            if plan.recurrence_seconds:
                interval = plan.recurrence_seconds
                unit = "seconds"
                if interval >= 3600:
                    interval = interval // 3600
                    unit = "hour" if interval == 1 else "hours"
                elif interval >= 60:
                    interval = interval // 60
                    unit = "minute" if interval == 1 else "minutes"
                confirmation = f"Scheduled recurring task: {description} (every {interval} {unit})"
            elif plan.schedule_seconds and plan.schedule_seconds > 0:
                delay = plan.schedule_seconds
                if delay >= 3600:
                    time_str = f"{delay // 3600} hour{'s' if delay >= 7200 else ''}"
                elif delay >= 60:
                    time_str = f"{delay // 60} minute{'s' if delay >= 120 else ''}"
                else:
                    time_str = f"{delay} second{'s' if delay != 1 else ''}"
                confirmation = f"Got it, I'll do that in {time_str}: {description}"
            else:
                confirmation = f"Task scheduled: {description}"

            return ExecuteResult(
                response=LLMResponse(
                    content=confirmation,
                    model="system",
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                )
            )

        # Map plan actions to tool names
        _ACTION_TOOLS = {
            "search": "web_search",
            "scrape": "read_page",
            "document": "read_document",
            "code": "run_code",
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

        # Apply skill system prompt if a skill is selected
        if plan.skill and self.skill_registry:
            skill = self.skill_registry.get(plan.skill)
            if skill:
                messages[0]["content"] = skill.system_prompt

        response = await self.provider.complete(messages)
        return ExecuteResult(response=response, scrape_metadata=scrape_metadata)
