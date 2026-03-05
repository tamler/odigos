from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.providers.base import LLMProvider

logger = logging.getLogger(__name__)

CLASSIFY_PROMPT = """You are an intent classifier. Given the user's message, decide if the assistant needs to search the web or read a specific page to answer well.

Respond with ONLY a JSON object (no markdown, no explanation):
- If web search is needed: {"action": "search", "query": "<optimized search query>", "skill": "<skill or null>"}
- If reading a specific URL is needed: {"action": "scrape", "url": "<the URL>", "skill": "<skill or null>"}
- If processing a document/file is needed: {"action": "document", "path": "<path or URL>", "skill": "<skill or null>"}
- If the user wants to schedule a task or set a reminder: {"action": "schedule", "description": "<what to do>", "delay_seconds": <seconds from now>, "recurrence_seconds": <repeat interval or null>, "skill": "<skill or null>"}
- If code execution is needed: {"action": "code", "code": "<python or shell code>", "language": "python|shell", "skill": "<skill or null>"}
- If no tools are needed: {"action": "respond", "skill": "<skill or null>"}

Available skills (use the name or null if none fits):
- "research-deep-dive": For questions requiring thorough research with multiple sources
- "summarize-page": For reading and summarizing a specific URL
- "general-chat": For casual conversation, opinions, greetings (default)

Search IS needed for: current events, factual questions, looking things up, "find me", "what is", recent news, prices, weather, technical questions the assistant might not know.
Scrape IS needed for: when the user shares a URL and wants to know what it says, "read this", "summarize this page", "what does this link say", any message containing a URL that the user wants analyzed.
Document IS needed for: when the user shares a file attachment, asks about a PDF/document, "read this document", "summarize this PDF", any message with a file attachment or a path to a document.
Schedule IS needed for: "remind me", "in X hours", "later today", "tomorrow morning", "every day at", any time-based request. For delay_seconds, calculate the number of seconds from now (e.g., "in 2 hours" = 7200).
Code IS needed for: math calculations, data processing, running scripts, "calculate", "compute", any request that requires executing code to produce a result.
Neither is needed for: greetings, personal questions, opinions, creative writing, conversation about things already discussed."""


@dataclass
class Plan:
    action: str  # "respond", "search", "scrape", "document", "schedule", "code"
    requires_tools: bool = False
    tool_params: dict = field(default_factory=dict)
    skill: str | None = None
    schedule_seconds: int | None = None
    recurrence_seconds: int | None = None


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
                max_tokens=200,
                temperature=0.0,
            )
            result = _parse_json(response.content)
            action = result.get("action", "respond")
            skill = result.get("skill") or None

            if action == "search":
                query = result.get("query", message_content)
                return Plan(
                    action="search",
                    requires_tools=True,
                    tool_params={"query": query},
                    skill=skill,
                )

            if action == "scrape":
                url = result.get("url", "")
                if url:
                    return Plan(
                        action="scrape",
                        requires_tools=True,
                        tool_params={"url": url},
                        skill=skill,
                    )

            if action == "document":
                path = result.get("path", "")
                if path:
                    return Plan(
                        action="document",
                        requires_tools=True,
                        tool_params={"path": path},
                        skill=skill,
                    )

            if action == "schedule":
                description = result.get("description", message_content)
                delay = result.get("delay_seconds", 0)
                recurrence = result.get("recurrence_seconds")
                return Plan(
                    action="schedule",
                    tool_params={"description": description},
                    skill=skill,
                    schedule_seconds=int(delay) if delay else 0,
                    recurrence_seconds=int(recurrence) if recurrence else None,
                )

            if action == "code":
                code = result.get("code", "")
                language = result.get("language", "python")
                if code:
                    return Plan(
                        action="code",
                        requires_tools=True,
                        tool_params={"code": code, "language": language},
                        skill=skill,
                    )

            return Plan(action="respond", skill=skill)

        except (json.JSONDecodeError, KeyError, RuntimeError):
            logger.warning("Intent classification failed, falling back to respond")
            return Plan(action="respond")


def _parse_json(text: str) -> dict:
    """Extract and parse JSON from LLM output, handling markdown code blocks."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise json.JSONDecodeError("No JSON object found", text, 0)
