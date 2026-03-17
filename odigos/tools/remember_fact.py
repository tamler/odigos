from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)


class RememberFactTool(BaseTool):
    name = "remember_fact"
    description = (
        "Save an explicit fact about the user for future reference. "
        "Use when the user says 'remember that...', 'I prefer...', 'I am...', "
        "or any personal information they want you to retain."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "The fact to remember"},
            "category": {
                "type": "string",
                "enum": [
                    "personal",
                    "professional",
                    "preference",
                    "technical",
                    "location",
                    "general",
                ],
                "description": "Category of the fact",
            },
        },
        "required": ["fact"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        fact = params.get("fact", "").strip()
        if not fact:
            return ToolResult(success=False, data="", error="Fact text is required")

        category = params.get("category", "general")
        now = datetime.now(timezone.utc).isoformat()
        fact_id = uuid.uuid4().hex

        try:
            # Check for duplicate/similar facts (exact match)
            existing = await self.db.fetch_one(
                "SELECT id FROM user_facts WHERE fact = ?", (fact,)
            )
            if existing:
                # Update the existing fact's timestamp
                await self.db.execute(
                    "UPDATE user_facts SET updated_at = ?, confidence = 1.0, "
                    "source = 'user_stated' WHERE id = ?",
                    (now, existing["id"]),
                )
                return ToolResult(
                    success=True,
                    data=f"Updated existing fact: {fact}",
                )

            await self.db.execute(
                "INSERT INTO user_facts (id, fact, category, source, confidence, created_at, updated_at) "
                "VALUES (?, ?, ?, 'user_stated', 1.0, ?, ?)",
                (fact_id, fact, category, now, now),
            )
            return ToolResult(
                success=True,
                data=f"Remembered: {fact} [{category}]",
            )
        except Exception as e:
            logger.error("Failed to save fact: %s", e, exc_info=True)
            return ToolResult(success=False, data="", error=f"Failed to save fact: {e}")
