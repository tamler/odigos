"""speak tool — generate speech audio via TTS provider."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from plugins.tts.provider import PocketTTSProvider

logger = logging.getLogger(__name__)


class SpeakTool(BaseTool):
    """Generate speech audio from text using local TTS."""

    name = "speak"
    description = (
        "Convert text to speech audio. Returns a WAV file path and duration. "
        "Available voices: alba, marius, javert, jean, fantine, cosette, eponine, azelma."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to convert to speech",
            },
            "voice": {
                "type": "string",
                "description": "Voice name (default: config voice). Options: alba, marius, javert, jean, fantine, cosette, eponine, azelma",
            },
        },
        "required": ["text"],
    }

    def __init__(self, tts_provider: PocketTTSProvider) -> None:
        self.tts = tts_provider

    async def execute(self, params: dict) -> ToolResult:
        text = params.get("text")
        if not text:
            return ToolResult(success=False, data="", error="No text provided")

        voice = params.get("voice")

        try:
            filepath, duration_ms = await asyncio.to_thread(
                self.tts.generate_audio, text, voice
            )
        except Exception as e:
            logger.warning("TTS generation failed: %s", e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))

        return ToolResult(
            success=True,
            data=f"Audio generated: {filepath} ({duration_ms}ms)",
            side_effect={"audio_path": filepath, "duration_ms": duration_ms},
        )
