from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from odigos.core.context import ContextAssembler
from odigos.db import Database
from odigos.providers.base import LLMProvider, LLMResponse, ToolCall

if TYPE_CHECKING:
    from odigos.core.budget import BudgetStatus, BudgetTracker
    from odigos.core.trace import Tracer
    from odigos.skills.registry import SkillRegistry
    from odigos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_TOOL_TURNS = 25

_INPUT_RATE_PER_M = 3.0
_OUTPUT_RATE_PER_M = 15.0


def _estimate_cost(tokens_in: int, tokens_out: int) -> float:
    """Conservative token-based cost estimate for budget safety checks."""
    return (tokens_in * _INPUT_RATE_PER_M + tokens_out * _OUTPUT_RATE_PER_M) / 1_000_000


@dataclass
class ExecuteResult:
    """Result from executor: LLM response + metadata."""
    response: LLMResponse


class Executor:
    """ReAct-style agentic loop engine.

    Calls LLM with tool definitions. If the LLM responds with tool_calls,
    executes them and feeds results back. Repeats until the LLM responds
    with no tool_calls or MAX_TOOL_TURNS is reached.
    """

    def __init__(
        self,
        provider: LLMProvider,
        context_assembler: ContextAssembler,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        db: Database | None = None,
        max_tool_turns: int = MAX_TOOL_TURNS,
        budget_tracker: BudgetTracker | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.db = db
        self._max_tool_turns = max_tool_turns
        self.budget_tracker = budget_tracker
        self.tracer = tracer

    async def execute(
        self,
        conversation_id: str,
        message_content: str,
        abort_event: asyncio.Event | None = None,
    ) -> ExecuteResult:
        # Reset active skill state
        self._active_skill_name: str | None = None
        self._active_skill_tools: set[str] = set()
        self._pending_skill_prompt: str | None = None

        # Build initial context
        messages = await self.context_assembler.build(
            conversation_id, message_content
        )

        # Get tool definitions if tools are available
        tools = None
        if self.tool_registry and self.tool_registry.list():
            tools = self.tool_registry.tool_definitions()

        # Aggregate token/cost tracking
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        last_response: LLMResponse | None = None
        run_estimated_cost = 0.0
        budget_warning: BudgetStatus | None = None

        for turn in range(self._max_tool_turns):
            # Check abort flag
            if abort_event and abort_event.is_set():
                logger.info("Run aborted at turn %d", turn)
                break

            # Budget check with running estimate
            if self.budget_tracker:
                status = await self.budget_tracker.check_budget(extra_cost=run_estimated_cost)
                if not status.within_budget:
                    logger.warning("Budget exceeded mid-run at turn %d", turn)
                    budget_msg = "\n\n---\nI've hit my spending limit mid-task. Stopping here."
                    if last_response is None:
                        last_response = LLMResponse(
                            content="I've hit my spending limit mid-task.",
                            model="system", tokens_in=0, tokens_out=0, cost_usd=0.0,
                        )
                    else:
                        last_response = LLMResponse(
                            content=(last_response.content or "") + budget_msg,
                            model=last_response.model,
                            tokens_in=last_response.tokens_in,
                            tokens_out=last_response.tokens_out,
                            cost_usd=last_response.cost_usd,
                            generation_id=last_response.generation_id,
                            tool_calls=None,
                        )
                    break
                if status.warning:
                    budget_warning = status

            # Call LLM
            response = await self.provider.complete(messages, tools=tools)
            total_tokens_in += response.tokens_in
            total_tokens_out += response.tokens_out
            total_cost += response.cost_usd
            last_response = response
            run_estimated_cost += _estimate_cost(response.tokens_in, response.tokens_out)

            # If no tool calls, we're done
            if not response.tool_calls:
                break

            # Append assistant message (with tool calls) to context
            assistant_msg: dict = {"role": "assistant", "content": response.content or ""}
            if response.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in response.tool_calls
                ]
            messages.append(assistant_msg)

            # Execute each tool call and append results
            for tc in response.tool_calls:
                result_content = await self._execute_tool(conversation_id, tc)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_content,
                })

            # Check for skill activation -- inject system message
            if self._pending_skill_prompt:
                messages.append({
                    "role": "system",
                    "content": f"[Active skill instructions]:\n\n{self._pending_skill_prompt}",
                })
                self._pending_skill_prompt = None
        else:
            logger.warning("Hit max tool turns (%d) for conversation %s", self._max_tool_turns, conversation_id)

        # Append budget warning to response if triggered
        if budget_warning and last_response and last_response.content and not last_response.tool_calls:
            pct = max(
                budget_warning.daily_spend / budget_warning.daily_limit * 100 if budget_warning.daily_limit > 0 else 0,
                budget_warning.monthly_spend / budget_warning.monthly_limit * 100 if budget_warning.monthly_limit > 0 else 0,
            )
            last_response = LLMResponse(
                content=(
                    f"{last_response.content}\n\n---\n"
                    f"Note: I've used {pct:.0f}% of my budget for this period "
                    f"(${budget_warning.daily_spend:.2f}/${budget_warning.daily_limit:.2f} daily)."
                ),
                model=last_response.model,
                tokens_in=last_response.tokens_in,
                tokens_out=last_response.tokens_out,
                cost_usd=last_response.cost_usd,
                generation_id=last_response.generation_id,
                tool_calls=last_response.tool_calls,
            )

        # Build aggregated response
        if last_response is None:
            last_response = LLMResponse(
                content="I couldn't process that request.",
                model="system", tokens_in=0, tokens_out=0, cost_usd=0.0,
            )

        aggregated = LLMResponse(
            content=last_response.content,
            model=last_response.model,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost_usd=total_cost,
            generation_id=last_response.generation_id,
            tool_calls=last_response.tool_calls,
        )

        return ExecuteResult(response=aggregated)

    async def _execute_tool(self, conversation_id: str, tool_call: ToolCall) -> str:
        """Execute a single tool call and return the result string."""
        if not self.tool_registry:
            return "Error: No tool registry available"

        tool = self.tool_registry.get(tool_call.name)
        if not tool:
            error = f"Error: Unknown tool '{tool_call.name}'"
            logger.warning(error)
            await self._emit_trace(conversation_id, "tool_result", {"tool": tool_call.name, "success": False, "error": "unknown tool"})
            return error

        await self._emit_trace(conversation_id, "tool_call", {
            "tool": tool_call.name,
            "arguments": tool_call.arguments,
        })

        t0 = time.monotonic()
        try:
            args = {**tool_call.arguments, "_conversation_id": conversation_id}
            result = await tool.execute(args)
            duration = time.monotonic() - t0
            await self._emit_trace(
                conversation_id, "tool_result",
                {"tool": tool_call.name, "success": result.success, "error": result.error, "duration_ms": round(duration * 1000)},
            )

            # Detect skill activation from structured payload
            if tool_call.name == "activate_skill" and result.success:
                try:
                    payload = json.loads(result.data)
                    if payload.get("__skill_activation__"):
                        self._active_skill_name = payload["skill_name"]
                        self._active_skill_tools = set(payload.get("skill_tools", []))
                        self._pending_skill_prompt = payload["skill_prompt"]
                        return payload.get("message", result.data)
                except (json.JSONDecodeError, KeyError):
                    pass

            if result.success:
                return result.data
            else:
                return f"Error: {result.error}"
        except Exception as e:
            duration = time.monotonic() - t0
            logger.exception("Tool %s raised an exception", tool_call.name)
            await self._emit_trace(
                conversation_id, "tool_result",
                {"tool": tool_call.name, "success": False, "error": str(e), "duration_ms": round(duration * 1000)},
            )
            return f"Error: Tool execution failed: {e}"

    async def _emit_trace(
        self, conversation_id: str, event_type: str, data: dict,
    ) -> None:
        """Emit a trace event with skill context."""
        if self._active_skill_name and data.get("tool") != "activate_skill":
            data["active_skill"] = self._active_skill_name
            tool_name = data.get("tool", "")
            if tool_name and tool_name not in self._active_skill_tools:
                data["skill_mismatch"] = True
                data["expected_tools"] = sorted(self._active_skill_tools)
                logger.info(
                    "Tool mismatch: %s called during skill '%s' (expected: %s)",
                    tool_name, self._active_skill_name, self._active_skill_tools,
                )

        if self.tracer:
            await self.tracer.emit(event_type, conversation_id, data)
