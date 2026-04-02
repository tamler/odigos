"""Audio processing tool using FFmpeg."""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import tempfile
from pathlib import Path

from odigos.storage import FILES_DIR
from odigos.tools.base import BaseTool, ToolContract, ToolResult

logger = logging.getLogger(__name__)

ALLOWED_DIR = os.path.realpath(str(FILES_DIR))
MAX_INPUT_SIZE = 100 * 1024 * 1024  # 100 MB

AUDIO_EXTENSIONS = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
    "flac": "audio/flac",
}


def _safe_path(path: str, base: str | None = None) -> str:
    """Resolve path and verify it is within allowed directory."""
    base = base or ALLOWED_DIR
    if os.path.isabs(path):
        resolved = os.path.realpath(path)
    else:
        resolved = os.path.realpath(os.path.join(base, path))
    allowed = os.path.realpath(base)
    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        raise ValueError("Path outside allowed directory")
    return resolved


def _content_type_for(ext: str) -> str:
    return AUDIO_EXTENSIONS.get(ext, "application/octet-stream")


async def _run_ffmpeg(*args: str) -> tuple[int, str, str]:
    """Run an ffmpeg command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


class ProcessAudioTool(BaseTool):
    name = "process_audio"
    category = "create"
    contract = ToolContract(timeout_seconds=120)
    description = (
        "Process audio files locally using FFmpeg. Convert formats, trim, "
        "normalize volume, concatenate files, or extract audio from video. "
        "No API calls -- completely free and instant."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["convert", "trim", "normalize", "concat", "extract_audio"],
                "description": "What to do with the audio",
            },
            "input_file": {
                "type": "string",
                "description": "Input file path or artifact filename",
            },
            "output_format": {
                "type": "string",
                "enum": ["mp3", "wav", "ogg", "m4a", "flac"],
                "description": "Output format (for convert action)",
            },
            "start_time": {
                "type": "string",
                "description": "Start time for trim (e.g., '00:00:30' or '30')",
            },
            "end_time": {
                "type": "string",
                "description": "End time for trim (e.g., '00:01:00' or '60')",
            },
            "input_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Multiple input files for concat action",
            },
        },
        "required": ["action"],
    }

    def __init__(self, db=None):
        self._db = db

    def _resolve_input(self, path: str) -> str:
        """Resolve an input file, checking FILES_DIR first for artifact names."""
        candidate = os.path.join(ALLOWED_DIR, path)
        if os.path.isfile(candidate):
            return _safe_path(candidate)
        return _safe_path(path)

    def _validate_input(self, resolved: str) -> str | None:
        """Return an error string if the input is invalid, else None."""
        if not os.path.isfile(resolved):
            return f"File not found: {resolved}"
        size = os.path.getsize(resolved)
        if size > MAX_INPUT_SIZE:
            return f"File too large: {size / (1024 * 1024):.1f} MB (max 100 MB)"
        return None

    def _output_path(self, prefix: str, ext: str) -> tuple[str, str, str]:
        """Generate output path in FILES_DIR. Returns (file_id, filename, full_path)."""
        file_id = secrets.token_hex(8)
        filename = f"{prefix}_{file_id[:8]}.{ext}"
        full_path = os.path.join(ALLOWED_DIR, filename)
        return file_id, filename, full_path

    async def _register_artifact(
        self, file_id: str, filename: str, filepath: str, ext: str,
    ) -> dict:
        """Register the output file as an artifact in the DB."""
        file_size = os.path.getsize(filepath)
        content_type = _content_type_for(ext)

        if self._db:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "INSERT OR IGNORE INTO artifacts "
                "(id, filename, content_type, file_size, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (file_id, filename, content_type, file_size, filepath, now),
            )

        return {
            "artifact": {
                "id": file_id,
                "filename": filename,
                "content_type": content_type,
                "file_size": file_size,
                "download_url": f"/api/artifacts/{file_id}/download",
            },
        }

    async def execute(self, params: dict) -> ToolResult:
        params.pop("_conversation_id", None)
        params.pop("_goal_id", None)

        action = params.get("action", "")
        if not action:
            return ToolResult(success=False, data="", error="action is required")

        if not shutil.which("ffmpeg"):
            return ToolResult(
                success=False, data="",
                error="FFmpeg is not installed or not in PATH",
            )

        FILES_DIR.mkdir(parents=True, exist_ok=True)

        try:
            if action == "convert":
                return await self._convert(params)
            elif action == "trim":
                return await self._trim(params)
            elif action == "normalize":
                return await self._normalize(params)
            elif action == "concat":
                return await self._concat(params)
            elif action == "extract_audio":
                return await self._extract_audio(params)
            else:
                return ToolResult(
                    success=False, data="", error=f"Unknown action: {action}",
                )
        except ValueError as e:
            return ToolResult(success=False, data="", error=str(e))
        except Exception as e:
            logger.warning("Audio processing failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))

    async def _convert(self, params: dict) -> ToolResult:
        input_file = params.get("input_file", "")
        output_format = params.get("output_format", "")
        if not input_file:
            return ToolResult(success=False, data="", error="input_file is required for convert")
        if not output_format:
            return ToolResult(
                success=False, data="", error="output_format is required for convert",
            )

        resolved_in = self._resolve_input(input_file)
        err = self._validate_input(resolved_in)
        if err:
            return ToolResult(success=False, data="", error=err)

        file_id, filename, out_path = self._output_path("converted", output_format)

        rc, _, stderr = await _run_ffmpeg(
            "-i", resolved_in, "-y", out_path,
        )
        if rc != 0:
            return ToolResult(success=False, data="", error=f"FFmpeg error: {stderr[-500:]}")

        side_effect = await self._register_artifact(file_id, filename, out_path, output_format)
        return ToolResult(
            success=True,
            data=f"Converted to {output_format.upper()}: {filename}",
            side_effect=side_effect,
        )

    async def _trim(self, params: dict) -> ToolResult:
        input_file = params.get("input_file", "")
        start_time = params.get("start_time", "")
        end_time = params.get("end_time", "")
        if not input_file:
            return ToolResult(success=False, data="", error="input_file is required for trim")
        if not start_time and not end_time:
            return ToolResult(
                success=False, data="",
                error="At least one of start_time or end_time is required for trim",
            )

        resolved_in = self._resolve_input(input_file)
        err = self._validate_input(resolved_in)
        if err:
            return ToolResult(success=False, data="", error=err)

        ext = Path(resolved_in).suffix.lstrip(".") or "mp3"
        file_id, filename, out_path = self._output_path("trimmed", ext)

        args = ["-i", resolved_in]
        if start_time:
            args.extend(["-ss", start_time])
        if end_time:
            args.extend(["-to", end_time])
        args.extend(["-c", "copy", "-y", out_path])

        rc, _, stderr = await _run_ffmpeg(*args)
        if rc != 0:
            return ToolResult(success=False, data="", error=f"FFmpeg error: {stderr[-500:]}")

        time_desc = ""
        if start_time and end_time:
            time_desc = f" from {start_time} to {end_time}"
        elif start_time:
            time_desc = f" from {start_time}"
        elif end_time:
            time_desc = f" to {end_time}"

        side_effect = await self._register_artifact(file_id, filename, out_path, ext)
        return ToolResult(
            success=True,
            data=f"Trimmed audio{time_desc}: {filename}",
            side_effect=side_effect,
        )

    async def _normalize(self, params: dict) -> ToolResult:
        input_file = params.get("input_file", "")
        if not input_file:
            return ToolResult(success=False, data="", error="input_file is required for normalize")

        resolved_in = self._resolve_input(input_file)
        err = self._validate_input(resolved_in)
        if err:
            return ToolResult(success=False, data="", error=err)

        ext = Path(resolved_in).suffix.lstrip(".") or "mp3"
        file_id, filename, out_path = self._output_path("normalized", ext)

        rc, _, stderr = await _run_ffmpeg(
            "-i", resolved_in, "-af", "loudnorm", "-y", out_path,
        )
        if rc != 0:
            return ToolResult(success=False, data="", error=f"FFmpeg error: {stderr[-500:]}")

        side_effect = await self._register_artifact(file_id, filename, out_path, ext)
        return ToolResult(
            success=True,
            data=f"Normalized audio (EBU R128): {filename}",
            side_effect=side_effect,
        )

    async def _concat(self, params: dict) -> ToolResult:
        input_files = params.get("input_files", [])
        if not input_files or len(input_files) < 2:
            return ToolResult(
                success=False, data="",
                error="At least 2 input_files are required for concat",
            )

        resolved_files = []
        for f in input_files:
            resolved = self._resolve_input(f)
            err = self._validate_input(resolved)
            if err:
                return ToolResult(success=False, data="", error=err)
            resolved_files.append(resolved)

        ext = Path(resolved_files[0]).suffix.lstrip(".") or "mp3"
        file_id, filename, out_path = self._output_path("concat", ext)

        # Write concat list to a temp file
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="ffconcat_")
        try:
            with os.fdopen(tmp_fd, "w") as f:
                for rfile in resolved_files:
                    escaped = rfile.replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")

            rc, _, stderr = await _run_ffmpeg(
                "-f", "concat", "-safe", "0", "-i", tmp_path,
                "-c", "copy", "-y", out_path,
            )
        finally:
            os.unlink(tmp_path)

        if rc != 0:
            return ToolResult(success=False, data="", error=f"FFmpeg error: {stderr[-500:]}")

        side_effect = await self._register_artifact(file_id, filename, out_path, ext)
        return ToolResult(
            success=True,
            data=f"Concatenated {len(resolved_files)} files: {filename}",
            side_effect=side_effect,
        )

    async def _extract_audio(self, params: dict) -> ToolResult:
        input_file = params.get("input_file", "")
        output_format = params.get("output_format", "mp3")
        if not input_file:
            return ToolResult(
                success=False, data="", error="input_file is required for extract_audio",
            )

        resolved_in = self._resolve_input(input_file)
        err = self._validate_input(resolved_in)
        if err:
            return ToolResult(success=False, data="", error=err)

        file_id, filename, out_path = self._output_path("extracted", output_format)

        # Map output format to codec
        codec_map = {
            "mp3": "libmp3lame",
            "wav": "pcm_s16le",
            "ogg": "libvorbis",
            "m4a": "aac",
            "flac": "flac",
        }
        codec = codec_map.get(output_format, "libmp3lame")

        rc, _, stderr = await _run_ffmpeg(
            "-i", resolved_in, "-vn", "-acodec", codec, "-y", out_path,
        )
        if rc != 0:
            return ToolResult(success=False, data="", error=f"FFmpeg error: {stderr[-500:]}")

        side_effect = await self._register_artifact(file_id, filename, out_path, output_format)
        return ToolResult(
            success=True,
            data=f"Extracted audio as {output_format.upper()}: {filename}",
            side_effect=side_effect,
        )
