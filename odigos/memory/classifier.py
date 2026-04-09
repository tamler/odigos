"""Classify content into structured memory types."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    memory_type: str = "general"
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    context_description: str = ""


class MemoryClassifier:
    VALID_TYPES = {
        "fact", "preference", "task", "idea", "entity",
        "experience", "correction", "summary", "general",
    }

    def __init__(self, llm_client, prompts_dir: str = "data/prompts") -> None:
        self._llm = llm_client
        self._prompts_dir = Path(prompts_dir)

    async def classify(self, content: str) -> ClassificationResult:
        prompt = self._load_prompt("memory_classify.md")
        filled = prompt.format(content=content[:2000])
        try:
            response = await self._llm.complete(
                messages=[{"role": "system", "content": filled}],
                temperature=0.2, max_tokens=500,
            )
            parsed = self._parse_json(response.content)
            return self._to_result(parsed, content)
        except Exception:
            logger.debug("Classification failed, using defaults", exc_info=True)
            return ClassificationResult(memory_type="general", context_description=content[:200])

    async def classify_document(self, filename: str, first_chunk: str) -> ClassificationResult:
        content = f"Document: {filename}\n\n{first_chunk[:1000]}"
        return await self.classify(content)

    def _to_result(self, parsed: dict, fallback_content: str) -> ClassificationResult:
        memory_type = parsed.get("memory_type", "general")
        if memory_type not in self.VALID_TYPES:
            memory_type = "general"
        return ClassificationResult(
            memory_type=memory_type,
            keywords=parsed.get("keywords", [])[:5],
            tags=parsed.get("tags", [])[:3],
            context_description=parsed.get("context_description", fallback_content[:200]),
        )

    def _load_prompt(self, filename: str) -> str:
        path = self._prompts_dir / filename
        if path.exists():
            return path.read_text()
        logger.warning("Prompt not found: %s", path)
        return "Classify this content:\n{content}"

    @staticmethod
    def _parse_json(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text, count=1)
            text = re.sub(r"\n?```\s*$", "", text.rstrip())
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse classifier JSON: %s", text[:200])
            return {}
