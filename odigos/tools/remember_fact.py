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

    def __init__(self, db: Database, provider=None, embedder=None, background_model: str = "") -> None:
        self.db = db
        self.provider = provider
        self.embedder = embedder
        self._background_model = background_model

    async def execute(self, params: dict) -> ToolResult:
        fact = params.get("fact", "").strip()
        if not fact:
            return ToolResult(success=False, data="", error="Fact text is required")

        category = params.get("category", "general")

        try:
            from odigos.memory.fact_checker import check_and_store_fact
            result = await check_and_store_fact(
                self.db,
                fact,
                category=category,
                source="user_stated",
                confidence=1.0,
                provider=self.provider,
                embedder=self.embedder,
                model=self._background_model,
            )

            # Backup user data to disk
            try:
                from odigos.core.data_export import export_user_data
                await export_user_data(self.db)
            except Exception:
                pass

            msg = result["message"]
            if result["replaced"]:
                msg += f"\n(Replaced contradicting fact: {result['replaced']})"
            return ToolResult(success=True, data=msg)
        except Exception as e:
            logger.error("Failed to save fact: %s", e, exc_info=True)
            return ToolResult(success=False, data="", error=f"Failed to save fact: {e}")
