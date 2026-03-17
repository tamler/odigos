from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from odigos.core.context import ContextAssembler, estimate_tokens
from odigos.db import Database
from odigos.providers.base import LLMProvider, LLMResponse, ToolCall

if TYPE_CHECKING:
    from odigos.core.approval import ApprovalGate
    from odigos.core.budget import BudgetStatus, BudgetTracker
    from odigos.core.classifier import QueryAnalysis
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
        approval_gate: ApprovalGate | None = None,
        reasoning_model: str = "",
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.db = db
        self._max_tool_turns = max_tool_turns
        self.budget_tracker = budget_tracker
        self.tracer = tracer
        self.approval_gate = approval_gate
        self._reasoning_model = reasoning_model
        self._active_skill_name: str | None = None
        self._active_skill_tools: set[str] = set()
        self._pending_skill_prompt: str | None = None

    async def execute(
        self,
        conversation_id: str,
        message_content: str,
        abort_event: asyncio.Event | None = None,
        *,
        query_analysis: QueryAnalysis | None = None,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> ExecuteResult:
        start_time = time.monotonic()
        tools_used: set[str] = set()

        # Reset active skill state
        self._active_skill_name = None
        self._active_skill_tools = set()
        self._pending_skill_prompt = None

        # Emit classification status
        if status_callback and query_analysis:
            await status_callback(f"Classified as {query_analysis.classification}")

        # Build initial context
        messages = await self.context_assembler.build(
            conversation_id, message_content, query_analysis=query_analysis
        )

        # Get tool definitions if tools are available
        tools = None
        if self.tool_registry and self.tool_registry.list():
            tools = self.tool_registry.tool_definitions()

        # Count context tokens for efficiency tracking
        context_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)

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

            # Call LLM -- use reasoning model for complex/document queries
            model_kwargs: dict = {}
            if query_analysis and query_analysis.classification in ("document_query", "complex", "planning"):
                if self._reasoning_model:
                    model_kwargs["model"] = self._reasoning_model
            try:
                response = await self.provider.complete(messages, tools=tools, **model_kwargs)
            except Exception as e:
                logger.error("LLM call failed at turn %d: %s", turn, e)
                if last_response is not None:
                    # We have a partial result from earlier turns, return it
                    break
                # No response at all -- return a graceful system message
                last_response = LLMResponse(
                    content="I'm having trouble reaching my language model right now. Please try again in a moment.",
                    model="system",
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                )
                break
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
                tools_used.add(tc.name)
                if status_callback:
                    await status_callback(f"Using {tc.name}...")
                result_content = await self._execute_tool(
                    conversation_id, tc, message_content=message_content,
                )
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

        # Log query analysis to query_log
        duration_ms = (time.monotonic() - start_time) * 1000
        if query_analysis and self.db:
            try:
                await self.db.execute(
                    "INSERT INTO query_log (id, conversation_id, classification, classifier_tier, "
                    "classifier_confidence, entities, search_queries, sub_questions, tools_used, "
                    "duration_ms, context_tokens, response_tokens, total_tokens, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), conversation_id, query_analysis.classification,
                     query_analysis.tier, query_analysis.confidence,
                     json.dumps(query_analysis.entities), json.dumps(query_analysis.search_queries),
                     json.dumps(query_analysis.sub_questions), json.dumps(sorted(tools_used)),
                     int(duration_ms), context_tokens, total_tokens_out,
                     total_tokens_in + total_tokens_out,
                     datetime.now(timezone.utc).isoformat()),
                )
            except Exception:
                logger.warning("Failed to log query", exc_info=True)

        # Log skill usage
        if self.db:
            for tool_name in tools_used:
                skill_name = None
                skill_type = "text"
                if tool_name.startswith("skill_"):
                    skill_name = tool_name[6:]  # strip "skill_" prefix
                    skill_type = "code"
                elif tool_name == "activate_skill":
                    skill_name = "activated"
                    skill_type = "text"

                if skill_name:
                    try:
                        await self.db.execute(
                            "INSERT INTO skill_usage (id, conversation_id, skill_name, skill_type, created_at) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (str(uuid.uuid4()), conversation_id, skill_name, skill_type,
                             datetime.now(timezone.utc).isoformat()),
                        )
                    except Exception:
                        logger.debug("Failed to log skill usage for %s", skill_name, exc_info=True)

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

    async def _execute_tool(
        self, conversation_id: str, tool_call: ToolCall, *, message_content: str = "",
    ) -> str:
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

        # Approval gate check
        if self.approval_gate and self.approval_gate.requires_approval(tool_call.name):
            decision = await self.approval_gate.request(
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
                conversation_id=conversation_id,
            )
            if decision != "approved":
                msg = f"Action not approved ({decision}). The user declined: {tool_call.name}"
                await self._emit_trace(
                    conversation_id, "tool_result",
                    {"tool": tool_call.name, "success": False, "error": f"approval_{decision}"},
                )
                return msg

        t0 = time.monotonic()
        try:
            args = {**tool_call.arguments, "_conversation_id": conversation_id}
            result = await tool.execute(args)
            duration = time.monotonic() - t0
            await self._emit_trace(
                conversation_id, "tool_result",
                {"tool": tool_call.name, "success": result.success, "error": result.error, "duration_ms": round(duration * 1000)},
            )

            # Detect skill activation from structured side_effect
            if result.side_effect and result.side_effect.get("skill_activation"):
                self._active_skill_name = result.side_effect["skill_name"]
                self._active_skill_tools = set(result.side_effect.get("skill_tools", []))
                self._pending_skill_prompt = result.side_effect["skill_prompt"]
                return result.data

            # Persist decomposed plan
            if (
                tool_call.name == "decompose_query"
                and result.side_effect
                and "plan_steps" in result.side_effect
                and self.db
            ):
                try:
                    now = datetime.now(timezone.utc).isoformat()
                    await self.db.execute(
                        "INSERT INTO task_plans (id, conversation_id, steps, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (str(uuid.uuid4()), conversation_id,
                         json.dumps(result.side_effect["plan_steps"]), now, now),
                    )
                except Exception:
                    logger.debug("Could not persist task plan", exc_info=True)

            # Log tool errors for cross-conversation learning
            if not result.success and self.db:
                try:
                    error_type = "unknown"
                    error_msg = result.error or ""
                    lower_err = error_msg.lower()
                    if "timeout" in lower_err:
                        error_type = "timeout"
                    elif "not found" in lower_err or "not_found" in lower_err:
                        error_type = "not_found"
                    elif "permission" in lower_err:
                        error_type = "permission"
                    elif "validation" in lower_err or "invalid" in lower_err:
                        error_type = "validation"
                    await self.db.execute(
                        "INSERT INTO tool_errors (id, tool_name, error_type, error_message, query_context, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (str(uuid.uuid4()), tool_call.name, error_type,
                         error_msg[:500], message_content[:200],
                         datetime.now(timezone.utc).isoformat()),
                    )
                except Exception:
                    logger.debug("Could not log tool error", exc_info=True)

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
