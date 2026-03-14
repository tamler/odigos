"""Agent tools for contact card generation and import."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.core.cards import CardManager


class GenerateCardTool(BaseTool):
    name = "generate_card"
    description = (
        "Generate a contact card to share with another agent or user. "
        "The card contains a scoped API key for establishing a relationship."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "description": "Card type: connect (full mesh), subscribe (feed only), invite (spawned agent)",
                "enum": ["connect", "subscribe", "invite"],
            },
            "expires_in_days": {
                "type": "integer",
                "description": "Optional: card expires after this many days",
            },
        },
        "required": ["type"],
    }

    def __init__(self, card_manager: CardManager) -> None:
        self.card_manager = card_manager

    async def execute(self, params: dict) -> ToolResult:
        card_type = params.get("type")
        if not card_type:
            return ToolResult(success=False, data="", error="Missing required parameter: type")

        if card_type not in ("connect", "subscribe", "invite"):
            return ToolResult(success=False, data="", error=f"Invalid card type: {card_type}")

        expires_in_days = params.get("expires_in_days")

        card = await self.card_manager.generate_card(
            card_type=card_type,
            expires_in_days=expires_in_days,
        )

        yaml_str = self.card_manager.card_to_yaml(card)
        compact = self.card_manager.card_to_compact(card)

        return ToolResult(
            success=True,
            data=json.dumps({
                "card": card,
                "yaml": yaml_str,
                "compact": compact,
            }),
        )


class ImportCardTool(BaseTool):
    name = "import_card"
    description = (
        "Import a contact card received from another agent. "
        "Accepts YAML or compact (odigos-card:...) format."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "card_data": {
                "type": "string",
                "description": "The card data: YAML string or compact odigos-card:... token",
            },
        },
        "required": ["card_data"],
    }

    def __init__(self, card_manager: CardManager) -> None:
        self.card_manager = card_manager

    async def execute(self, params: dict) -> ToolResult:
        card_data = params.get("card_data")
        if not card_data:
            return ToolResult(success=False, data="", error="Missing required parameter: card_data")

        result = await self.card_manager.import_card(card_data)

        if result["status"] == "rejected":
            return ToolResult(success=False, data=json.dumps(result), error=result.get("reason", "Card rejected"))

        return ToolResult(success=True, data=json.dumps(result))
