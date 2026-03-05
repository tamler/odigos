from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from odigos.core.context import ContextAssembler
from odigos.db import Database
from odigos.providers.base import LLMProvider, LLMResponse, ToolCall

if TYPE_CHECKING:
    from odigos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_TOOL_TURNS = 25


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
        db: Database | None = None,
        max_tool_turns: int = MAX_TOOL_TURNS,
    ) -> None:
        self.provider = provider
        self.context_assembler = context_assembler
        self.tool_registry = tool_registry
        self.db = db
        self._max_tool_turns = max_tool_turns

    async def execute(
        self,
        conversation_id: str,
        message_content: str,
        abort_event: asyncio.Event | None = None,
    ) -> ExecuteResult:
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

        for turn in range(self._max_tool_turns):
            # Check abort flag
            if abort_event and abort_event.is_set():
                logger.info("Run aborted at turn %d", turn)
                break

            # Call LLM
            response = await self.provider.complete(messages, tools=tools)
            total_tokens_in += response.tokens_in
            total_tokens_out += response.tokens_out
            total_cost += response.cost_usd
            last_response = response

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
        else:
            logger.warning("Hit max tool turns (%d) for conversation %s", self._max_tool_turns, conversation_id)

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
            await self._log_action(conversation_id, "tool", tool_call.name, {"success": False, "error": "unknown tool"})
            return error

        try:
            result = await tool.execute(tool_call.arguments)
            await self._log_action(
                conversation_id, "tool", tool_call.name,
                {"success": result.success, "error": result.error},
            )
            if result.success:
                return result.data
            else:
                return f"Error: {result.error}"
        except Exception as e:
            logger.exception("Tool %s raised an exception", tool_call.name)
            await self._log_action(
                conversation_id, "tool", tool_call.name,
                {"success": False, "error": str(e)},
            )
            return f"Error: Tool execution failed: {e}"

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
