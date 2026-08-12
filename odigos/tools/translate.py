"""Translation tool using Google Translate via deep-translator."""
from __future__ import annotations

import asyncio
import logging

from odigos.core.capabilities import record_degraded
from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class TranslateTool(BaseTool):
    name = "translate_text"
    category = "media"
    description = (
        "Translate text between languages. Auto-detects the source "
        "language if not specified. Supports 100+ languages."
        " Do not use for language detection alone — use analyze_text with action language instead."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to translate",
            },
            "target": {
                "type": "string",
                "description": (
                    "Target language code (e.g., 'en', 'es', 'fr', "
                    "'de', 'ja', 'zh-cn', 'ar'). Default: 'en'"
                ),
            },
            "source": {
                "type": "string",
                "description": (
                    "Source language code. Leave empty for "
                    "auto-detection."
                ),
            },
        },
        "required": ["text"],
    }

    async def execute(self, params: dict) -> ToolResult:
        text = params.get("text", "").strip()
        if not text:
            return ToolResult(
                success=False, data="", error="No text provided"
            )

        target = params.get("target", "en").strip()
        source = params.get("source", "auto").strip() or "auto"

        try:
            from deep_translator import GoogleTranslator

            translator = GoogleTranslator(
                source=source, target=target
            )
            translated = await asyncio.to_thread(
                translator.translate, text
            )

            output = (
                f"Translation ({source} -> {target}):\n\n"
                f"{translated}"
            )

            return ToolResult(success=True, data=output)
        except ImportError as e:
            record_degraded("deep-translator", e)
            return ToolResult(
                success=False,
                data="",
                error="deep-translator not installed",
            )
        except Exception as e:
            logger.warning("Translation failed: %s", e)
            return ToolResult(
                success=False, data="", error=str(e)
            )
