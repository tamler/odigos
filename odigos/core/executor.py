from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from odigos.core.context import ContextAssembler
from odigos.core.planner import Plan
from odigos.db import Database
from odigos.providers.base import LLMProvider, LLMResponse

if TYPE_CHECKING:
    from odigos.core.goal_store import GoalStore
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
        goal_store: GoalStore | None = None,
        db: Database | None = None,
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.goal_store = goal_store
        self.db = db

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

        # Handle remind action (no LLM call)
        if plan.action == "remind" and self.goal_store:
            description = plan.tool_params.get("description", "")
            due_seconds = int(plan.tool_params.get("due_at_seconds", 0))
            recurrence = plan.tool_params.get("recurrence")
            await self.goal_store.create_reminder(
                description=description,
                due_seconds=due_seconds,
                recurrence=recurrence,
                conversation_id=conversation_id,
            )
            if due_seconds > 0:
                if due_seconds >= 3600:
                    time_str = f"{due_seconds // 3600} hour{'s' if due_seconds >= 7200 else ''}"
                elif due_seconds >= 60:
                    time_str = f"{due_seconds // 60} minute{'s' if due_seconds >= 120 else ''}"
                else:
                    time_str = f"{due_seconds} second{'s' if due_seconds != 1 else ''}"
                confirmation = f"Reminder set for {time_str} from now: {description}"
            else:
                confirmation = f"Reminder set: {description}"
            if recurrence:
                confirmation += f" (recurring: {recurrence})"
            return ExecuteResult(
                response=LLMResponse(content=confirmation, model="system", tokens_in=0, tokens_out=0, cost_usd=0.0)
            )

        # Handle todo action (no LLM call)
        if plan.action == "todo" and self.goal_store:
            description = plan.tool_params.get("description", "")
            delay = int(plan.tool_params.get("delay_seconds", 0))
            await self.goal_store.create_todo(
                description=description,
                delay_seconds=delay,
                conversation_id=conversation_id,
            )
            if delay > 0:
                if delay >= 3600:
                    time_str = f"{delay // 3600} hour{'s' if delay >= 7200 else ''}"
                elif delay >= 60:
                    time_str = f"{delay // 60} minute{'s' if delay >= 120 else ''}"
                else:
                    time_str = f"{delay} second{'s' if delay != 1 else ''}"
                confirmation = f"Got it, I'll do that in {time_str}: {description}"
            else:
                confirmation = f"Todo added: {description}"
            return ExecuteResult(
                response=LLMResponse(content=confirmation, model="system", tokens_in=0, tokens_out=0, cost_usd=0.0)
            )

        # Handle goal action (no LLM call)
        if plan.action == "goal" and self.goal_store:
            description = plan.tool_params.get("description", "")
            await self.goal_store.create_goal(description=description)
            confirmation = f"Goal noted: {description}"
            return ExecuteResult(
                response=LLMResponse(content=confirmation, model="system", tokens_in=0, tokens_out=0, cost_usd=0.0)
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
                    # Log tool execution
                    await self._log_action(
                        conversation_id, "tool", tool_name,
                        {"success": result.success, "error": result.error},
                    )
                except Exception:
                    logger.exception("Tool %s raised an exception", tool_name)
                    await self._log_action(
                        conversation_id, "tool", tool_name,
                        {"success": False, "error": "exception"},
                    )

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

    async def _log_action(
        self, conversation_id: str, action_type: str, action_name: str, details: dict,
    ) -> None:
        if not self.db:
            return
        try:
            await self.db.execute(
                "INSERT INTO action_log (id, conversation_id, action_type, action_name, details_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), conversation_id, action_type, action_name, json.dumps(details)),
            )
        except Exception:
            logger.debug("Failed to log action", exc_info=True)
