from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

CLASSIFY_PROMPT = """You are an intent classifier. Given the user's message, decide if the assistant needs to search the web to answer well.

Respond with ONLY a JSON object (no markdown, no explanation):
- If web search is needed: {"action": "search", "query": "<optimized search query>"}
- If no search is needed: {"action": "respond"}

Search IS needed for: current events, factual questions, looking things up, "find me", "what is", recent news, prices, weather, technical questions the assistant might not know.
Search is NOT needed for: greetings, personal questions, opinions, creative writing, math, conversation about things already discussed."""


@dataclass
class Plan:
    action: str  # "respond" or "search"
    requires_tools: bool = False
    tool_params: dict = field(default_factory=dict)


class Planner:
    """Decides what actions to take for a given message.

    Uses a cheap LLM call to classify intent and extract search queries.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def plan(self, message_content: str) -> Plan:
        try:
            response = await self.provider.complete(
                [
                    {"role": "system", "content": CLASSIFY_PROMPT},
                    {"role": "user", "content": message_content},
                ],
                max_tokens=100,
                temperature=0.0,
            )
            result = json.loads(response.content.strip())
            action = result.get("action", "respond")

            if action == "search":
                query = result.get("query", message_content)
                return Plan(action="search", requires_tools=True, tool_params={"query": query})

            return Plan(action="respond")

        except (json.JSONDecodeError, KeyError, RuntimeError):
            logger.warning("Intent classification failed, falling back to respond")
            return Plan(action="respond")
