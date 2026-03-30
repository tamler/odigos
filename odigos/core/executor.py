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
    from odigos.core.evaluator import Evaluator
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


import random

_TOOL_STATUS_MAP: dict[str, list[str]] = {
    "generate_image": [
        "Painting something up...",
        "Conjuring pixels...",
        "Firing up the art studio...",
        "Crafting your image...",
        "Bringing your vision to life...",
    ],
    "web_search": [
        "Searching the web...",
        "Digging through the internet...",
        "Scouring the web...",
        "Looking that up...",
    ],
    "web_scrape": [
        "Reading that page...",
        "Pulling content...",
        "Grabbing the details...",
    ],
    "run_code": [
        "Running some code...",
        "Crunching numbers...",
        "Executing...",
    ],
    "check_email": [
        "Checking your inbox...",
        "Peeking at emails...",
    ],
    "send_email": [
        "Sending that off...",
        "Dispatching your message...",
    ],
    "check_calendar": [
        "Checking your schedule...",
        "Looking at your calendar...",
    ],
    "process_document": [
        "Reading that document...",
        "Digesting the content...",
        "Processing the file...",
    ],
    "remember_fact": [
        "Noted. Committing to memory...",
        "Saving that...",
    ],
    "remember_fact": [
        "Noted. Committing to memory...",
        "Saving that...",
    ],
    "decompose_query": [
        "Breaking this down...",
        "Planning the approach...",
    ],
    "manage_files": [
        "Working with files...",
        "Accessing the file...",
    ],
    "translate": [
        "Translating...",
    ],
    "lookup_fact": [
        "Looking that up...",
        "Checking the encyclopedia...",
    ],
    "process_image": [
        "Processing the image...",
        "Looking at that image...",
        "Reading the image...",
    ],
    "create_artifact": [
        "Creating your file...",
        "Putting it together...",
    ],
    "search_workspace": [
        "Searching your workspace...",
    ],
}

_GENERIC_STATUSES = [
    "Working on it...",
    "On it...",
    "One moment...",
    "Handling that...",
]


def _friendly_tool_status(tool_name: str) -> str:
    options = _TOOL_STATUS_MAP.get(tool_name, _GENERIC_STATUSES)
    return random.choice(options)


@dataclass
class ExecuteResult:
    """Result from executor: LLM response + metadata."""
    response: LLMResponse
    suggested_actions: list[str] | None = None


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
        background_model: str = "",
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
        self._background_model = background_model
        self.evaluator: Evaluator | None = None
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
        context_metadata: dict | None = None,
        stream_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> ExecuteResult:
        start_time = time.monotonic()
        tools_used: set[str] = set()

        # Reset active skill state
        self._active_skill_name = None
        self._active_skill_tools = set()
        self._pending_skill_prompt = None
        self._pending_suggested_actions: list[str] | None = None

        # Build initial context
        messages = await self.context_assembler.build(
            conversation_id, message_content,
            query_analysis=query_analysis,
            context_metadata=context_metadata,
        )

        # Load routing rules and get filtered tool definitions
        from odigos.core.routing import load_routing_rules
        routing = load_routing_rules()

        tools = None
        if self.tool_registry and self.tool_registry.list():
            classification = query_analysis.classification if query_analysis else None
            tools = self.tool_registry.tool_definitions(
                classification=classification, routing_rules=routing,
            )

        # Count context tokens for efficiency tracking
        context_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)

        # Aggregate token/cost tracking
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        last_response: LLMResponse | None = None
        run_estimated_cost = 0.0
        budget_warning: BudgetStatus | None = None
        prev_turn_calls: set[str] = set()

        # Budget-aware strategy: throttle when near limits
        effective_max_turns = self._max_tool_turns
        budget_throttled = False

        for turn in range(effective_max_turns):
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
                if status.warning and not budget_throttled:
                    budget_warning = status
                    budget_throttled = True
                    effective_max_turns = min(effective_max_turns, turn + 5)
                    messages.append({
                        "role": "system",
                        "content": (
                            "Budget is near its limit. Be concise -- respond in 2-3 sentences. "
                            "Avoid tool calls unless strictly necessary."
                        ),
                    })
                    logger.info("Budget throttle engaged at turn %d, max turns capped at %d", turn, effective_max_turns)

            # Call LLM -- use reasoning model for complex queries, downgrade on budget warning
            model_kwargs: dict = {}
            if budget_throttled and self._background_model:
                model_kwargs["model"] = self._background_model
            elif query_analysis and query_analysis.classification in ("document_query", "complex", "planning"):
                if self._reasoning_model:
                    model_kwargs["model"] = self._reasoning_model
            try:
                # Use streaming when a stream_callback is provided
                if stream_callback and hasattr(self.provider, "stream_complete"):
                    response = None
                    async for chunk_text, final_response in self.provider.stream_complete(
                        messages, tools=tools, **model_kwargs
                    ):
                        if chunk_text is not None:
                            await stream_callback(chunk_text)
                        if final_response is not None:
                            response = final_response
                    if response is None:
                        raise RuntimeError("Streaming completed without final response")
                else:
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
            # Execute tool calls -- parallel when multiple, sequential when single
            goal_id = (context_metadata or {}).get("goal_id")
            MAX_TOOL_RESULT = 4000

            async def _run_tool(tc):
                tools_used.add(tc.name)
                if status_callback:
                    await status_callback(_friendly_tool_status(tc.name))
                result_content = await self._execute_tool(
                    conversation_id, tc, message_content=message_content, goal_id=goal_id,
                )
                if len(result_content) > MAX_TOOL_RESULT:
                    result_content = result_content[:MAX_TOOL_RESULT] + f"\n\n[Truncated — {len(result_content)} chars total. Use file tool to read full content if needed.]"
                if self.evaluator:
                    try:
                        await self.evaluator.evaluate_tool_output(
                            tc.name, tc.arguments, result_content, message_content,
                        )
                    except Exception:
                        logger.debug("Tool eval failed for %s", tc.name, exc_info=True)
                return tc, result_content

            if len(response.tool_calls) > 1:
                results = await asyncio.gather(
                    *[_run_tool(tc) for tc in response.tool_calls],
                    return_exceptions=True,
                )
                for r in results:
                    if isinstance(r, Exception):
                        logger.error("Parallel tool execution failed: %s", r)
                        continue
                    tc, result_content = r
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_content})
            else:
                tc, result_content = await _run_tool(response.tool_calls[0])
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_content})

            # Stuck detection: warn if identical tool calls as previous turn
            current_turn_calls = {
                f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True)}"
                for tc in response.tool_calls
            }
            if current_turn_calls and current_turn_calls == prev_turn_calls:
                messages.append({
                    "role": "system",
                    "content": "You are repeating the same tool calls. Try a different approach.",
                })
                logger.warning("Stuck detection triggered at turn %d", turn)
            prev_turn_calls = current_turn_calls

            # Dual-loop reasoning: verify after plan step updates
            plan_tools = {"decompose_query", "check_plan", "update_plan"}
            used_plan_tools = {tc.name for tc in response.tool_calls} & plan_tools
            if used_plan_tools and "update_plan" in used_plan_tools:
                messages.append({
                    "role": "system",
                    "content": "Before proceeding to the next step, verify the result of the current step is correct and complete.",
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

        # Check for canary token leak (system prompt exfiltration)
        content = last_response.content or ""
        try:
            from odigos.personality.prompt_builder import CANARY_TOKEN
            if CANARY_TOKEN in content:
                logger.warning("CANARY TOKEN DETECTED in LLM output -- possible prompt exfiltration")
                content = content.replace(CANARY_TOKEN, "[REDACTED]")
        except Exception:
            pass

        aggregated = LLMResponse(
            content=content,
            model=last_response.model,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost_usd=total_cost,
            generation_id=last_response.generation_id,
            tool_calls=last_response.tool_calls,
        )

        return ExecuteResult(response=aggregated, suggested_actions=self._pending_suggested_actions)

    async def _execute_tool(
        self, conversation_id: str, tool_call: ToolCall, *, message_content: str = "",
        goal_id: str | None = None,
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

        from odigos.core.failure import classify as classify_failure, should_retry
        from odigos.tools.base import ToolContract

        contract = getattr(tool, "contract", None) or ToolContract()
        args = {**tool_call.arguments, "_conversation_id": conversation_id, "_goal_id": goal_id}
        attempt = 0

        while True:
            t0 = time.monotonic()
            result = None
            exception = None

            try:
                result = await asyncio.wait_for(
                    tool.execute(args),
                    timeout=contract.timeout_seconds,
                )
                duration = time.monotonic() - t0
            except asyncio.TimeoutError:
                duration = time.monotonic() - t0
                exception = TimeoutError(f"Tool {tool_call.name} timed out after {contract.timeout_seconds}s")
            except Exception as e:
                duration = time.monotonic() - t0
                exception = e

            # Classify the failure
            if exception:
                category = classify_failure(exception=exception)
                error_msg = str(exception)
                logger.warning("Tool %s failed (attempt %d, %s): %s", tool_call.name, attempt + 1, category, error_msg)
            elif result and not result.success:
                category = result.failure_category or classify_failure(error_msg=result.error)
                error_msg = result.error or "Unknown error"
            else:
                category = None
                error_msg = None

            # Retry transient/unknown failures if contract allows
            if category and should_retry(category, attempt, contract.max_retries):
                attempt += 1
                backoff = contract.retry_backoff_base * (2 ** (attempt - 1))
                logger.info("Retrying %s in %.1fs (attempt %d, %s)", tool_call.name, backoff, attempt, category)
                await asyncio.sleep(backoff)
                continue

            # No more retries -- emit trace and process result
            await self._emit_trace(
                conversation_id, "tool_result",
                {
                    "tool": tool_call.name,
                    "success": result.success if result else False,
                    "error": error_msg,
                    "duration_ms": round(duration * 1000),
                    "attempts": attempt + 1,
                    "failure_category": category,
                },
            )

            # Handle exceptions (no result object)
            if exception:
                if self.db:
                    try:
                        await self.db.execute(
                            "INSERT INTO tool_errors (id, tool_name, error_type, error_message, query_context, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (str(uuid.uuid4()), tool_call.name, category or "unknown",
                             str(exception)[:500], message_content[:200],
                             datetime.now(timezone.utc).isoformat()),
                        )
                    except Exception:
                        logger.debug("Could not log tool error", exc_info=True)
                return f"Error: Tool execution failed: {exception}"

            # Process successful result
            if result.side_effect and result.side_effect.get("suggested_actions"):
                self._pending_suggested_actions = result.side_effect["suggested_actions"]

            if result.side_effect and result.side_effect.get("skill_activation"):
                self._active_skill_name = result.side_effect["skill_name"]
                self._active_skill_tools = set(result.side_effect.get("skill_tools", []))
                self._pending_skill_prompt = result.side_effect["skill_prompt"]
                return result.data

            # Persist decomposed plan or attach substeps to parent
            if tool_call.name == "decompose_query" and result.side_effect and self.db:
                await self._persist_plan(conversation_id, result, message_content)

            # Log tool errors
            if not result.success and self.db:
                try:
                    await self.db.execute(
                        "INSERT INTO tool_errors (id, tool_name, error_type, error_message, query_context, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (str(uuid.uuid4()), tool_call.name, category or "unknown",
                         (result.error or "")[:500], message_content[:200],
                         datetime.now(timezone.utc).isoformat()),
                    )
                except Exception:
                    logger.debug("Could not log tool error", exc_info=True)

            if result.success:
                return result.data
            return f"Error: {result.error}"

    async def _persist_plan(
        self, conversation_id: str, result: "ToolResult", message_content: str,
    ) -> None:
        """Persist a decomposed plan or attach substeps to an existing plan."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            if "plan_steps" in result.side_effect:
                plan_id = str(uuid.uuid4())
                plan_steps = result.side_effect["plan_steps"]
                contract_json: str | None = None
                if self.evaluator:
                    try:
                        contract = await self.evaluator.generate_sprint_contract(
                            goal=message_content, steps=plan_steps,
                        )
                        contract_json = json.dumps(contract)
                    except Exception:
                        logger.debug("Sprint contract gen failed", exc_info=True)
                await self.db.execute(
                    "INSERT INTO task_plans "
                    "(id, conversation_id, steps, sprint_contract, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (plan_id, conversation_id, json.dumps(plan_steps), contract_json, now, now),
                )
            elif "substeps" in result.side_effect and "parent_step" in result.side_effect:
                parent_step = str(result.side_effect["parent_step"])
                substeps = result.side_effect["substeps"]
                substeps = [s for s in substeps if isinstance(s, dict) and "step" in s and "task" in s]
                if substeps:
                    row = await self.db.fetch_one(
                        "SELECT id, steps FROM task_plans WHERE conversation_id = ? "
                        "ORDER BY updated_at DESC LIMIT 1",
                        (conversation_id,),
                    )
                    if row:
                        steps = json.loads(row["steps"])
                        for s in steps:
                            if str(s["step"]) == parent_step:
                                s["substeps"] = substeps
                                break
                        await self.db.execute(
                            "UPDATE task_plans SET steps = ?, updated_at = ? WHERE id = ?",
                            (json.dumps(steps), now, row["id"]),
                        )
        except Exception:
            logger.debug("Could not persist task plan", exc_info=True)

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
