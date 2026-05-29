"""transcribe_audio tool — transcribe audio files via STT provider."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult
from odigos.tools.gate import ToolGate
from odigos.storage import FILES_DIR

if TYPE_CHECKING:
    from odigos.memory.ingester import DocumentIngester
    from plugins.stt.provider import MoonshineSTT

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".m4a", ".webm", ".flac", ".opus"}


class TranscribeAudioTool(BaseTool):
    """Transcribe an audio file to text using local STT."""

    name = "transcribe_audio"
    gate = ToolGate.plugin("stt")
    category = "analysis"
    description = (
        "Transcribe an audio file (WAV, MP3, OGG, M4A, FLAC, WebM) to text. "
        "Returns the full transcript. Also ingests it into memory for future recall."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "File path to the audio file to transcribe",
            },
        },
        "required": ["source"],
    }

    def __init__(self, stt_provider: MoonshineSTT, ingester: DocumentIngester | None = None) -> None:
        self.stt = stt_provider
        self.ingester = ingester

    _ALLOWED_DIR = FILES_DIR.resolve()

    async def execute(self, params: dict) -> ToolResult:
        source = params.get("source")
        if not source:
            return ToolResult(success=False, data="", error="No source audio path provided")

        resolved = Path(source).resolve()
        try:
            resolved.relative_to(self._ALLOWED_DIR)
        except ValueError:
            return ToolResult(success=False, data="", error="Path outside allowed directory")
        source = str(resolved)

        try:
            transcript = await asyncio.to_thread(self.stt.transcribe_file, source)
        except Exception as e:
            logger.warning("Transcription failed for %s: %s", source, e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))

        if self.ingester and transcript:
            try:
                filename = os.path.basename(source)
                content_hash = hashlib.sha256(transcript.encode()).hexdigest()
                await self.ingester.ingest(
                    text=transcript,
                    filename=filename,
                    file_path=source,
                    file_size=os.path.getsize(source) if os.path.exists(source) else None,
                    content_hash=content_hash,
                )
            except Exception as e:
                logger.warning("Transcript ingestion failed for %s: %s", source, e, exc_info=True)

        return ToolResult(success=True, data=transcript)
