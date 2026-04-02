"""Music generation via Kie.ai Suno API (two-step: draft then submit)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx

from odigos.tools.base import BaseTool, ToolContract, ToolResult

logger = logging.getLogger(__name__)

KIE_BASE = "https://api.kie.ai/api/v1"


class GenerateMusicTool(BaseTool):
    name = "generate_music"
    category = "create"
    contract = ToolContract(
        timeout_seconds=30,
        max_retries={"transient": 0, "input": 0, "permission": 0, "unavailable": 0, "unknown": 0},
    )
    description = (
        "Create a song or music track. Generates an editable draft with lyrics, "
        "style, and settings. The user can review and edit before submitting for "
        "generation."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Song description or lyrics",
            },
            "style": {
                "type": "string",
                "description": "Musical style/genre (e.g., 'indie folk, acoustic')",
            },
            "title": {
                "type": "string",
                "description": "Song title",
            },
            "instrumental": {
                "type": "boolean",
                "description": "Instrumental only, no vocals (default false)",
            },
            "vocal_gender": {
                "type": "string",
                "enum": ["", "male", "female"],
                "description": "Preferred vocal gender",
            },
        },
        "required": ["prompt"],
    }

    def __init__(self, db=None):
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        conversation_id = params.pop("_conversation_id", None)
        prompt = (params.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(
                success=False, data="", error="No prompt provided",
            )

        style = (params.get("style") or "").strip()
        title = (params.get("title") or "").strip()
        instrumental = params.get("instrumental", False)
        vocal_gender = params.get("vocal_gender", "")

        # Build the song draft artifact
        artifact_id = uuid.uuid4().hex
        song_data = {
            "lyrics": prompt,
            "style": style,
            "title": title,
            "model": "V5",
            "instrumental": bool(instrumental),
            "vocal_gender": vocal_gender,
            "negative_tags": "",
        }

        filename = f"draft_{artifact_id[:16]}.song.json"

        try:
            from odigos.storage import FILES_DIR
            os.makedirs(str(FILES_DIR), exist_ok=True)
            filepath = os.path.join(str(FILES_DIR), filename)
            with open(filepath, "w") as f:
                json.dump(song_data, f, indent=2)

            file_size = os.path.getsize(filepath)

            if self._db:
                now = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    "INSERT INTO artifacts "
                    "(id, conversation_id, filename, content_type, "
                    "file_size, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (artifact_id, conversation_id, filename,
                     "application/json", file_size, filepath, now),
                )

            display_title = title or "Untitled"
            display_style = style or "auto"

            return ToolResult(
                success=True,
                data=(
                    f"Song draft created: \"{display_title}\" "
                    f"(style: {display_style}). "
                    f"Artifact: {filename}"
                ),
                side_effect={
                    "artifact": {
                        "id": artifact_id,
                        "filename": filename,
                        "content_type": "application/json",
                        "file_size": file_size,
                        "download_url": f"/api/artifacts/{artifact_id}/download",
                        "path": filepath,
                    },
                    "needs_confirmation": True,
                },
            )
        except Exception as e:
            logger.error("Music draft creation failed: %s", e)
            return ToolResult(
                success=False, data="", error=str(e),
            )


class SubmitMusicTool(BaseTool):
    name = "submit_music"
    category = "create"
    contract = ToolContract(
        timeout_seconds=240,
        max_retries={"transient": 2, "input": 0, "permission": 0, "unavailable": 0, "unknown": 1},
    )
    description = (
        "Submit a music draft for generation. Call after the user has reviewed "
        "and approved the song draft artifact."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "artifact_id": {
                "type": "string",
                "description": "The ID of the .song.json artifact to submit",
            },
        },
        "required": ["artifact_id"],
    }

    def __init__(
        self,
        api_key: str,
        max_poll_seconds: int = 180,
        output_dir: str = "",
        db=None,
    ):
        self._api_key = api_key
        self._max_poll = max_poll_seconds
        from odigos.storage import FILES_DIR
        self._output_dir = output_dir or str(FILES_DIR)
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        conversation_id = params.pop("_conversation_id", None)
        artifact_id = (params.get("artifact_id") or "").strip()
        if not artifact_id:
            return ToolResult(
                success=False, data="", error="No artifact_id provided",
            )

        # Read the song draft
        try:
            song_data = await self._load_draft(artifact_id)
            if song_data is None:
                return ToolResult(
                    success=False, data="",
                    error=f"Song draft not found: {artifact_id}",
                )
        except Exception as e:
            return ToolResult(
                success=False, data="",
                error=f"Failed to read song draft: {e}",
            )

        try:
            task_id = await self._create_task(song_data)
            if not task_id:
                return ToolResult(
                    success=False, data="",
                    error="Failed to create music generation task",
                )

            tracks = await self._poll_result(task_id)
            if not tracks:
                return ToolResult(
                    success=False, data="",
                    error="Music generation timed out or failed",
                )

            # Download and register each track
            artifacts = []
            for i, track in enumerate(tracks):
                audio_url = track.get("audioUrl", "")
                if not audio_url:
                    continue

                track_id = uuid.uuid4().hex
                track_title = track.get("title", f"track_{i + 1}")
                safe_title = "".join(
                    c if c.isalnum() or c in "-_ " else ""
                    for c in track_title
                ).strip().replace(" ", "_")
                filename = f"{safe_title}_{track_id[:12]}.mp3"

                filepath = await self._download_audio(audio_url, filename)
                file_size = os.path.getsize(filepath)

                if self._db:
                    now = datetime.now(timezone.utc).isoformat()
                    await self._db.execute(
                        "INSERT INTO artifacts "
                        "(id, conversation_id, filename, content_type, "
                        "file_size, file_path, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (track_id, conversation_id, filename,
                         "audio/mpeg", file_size, filepath, now),
                    )

                artifacts.append({
                    "id": track_id,
                    "filename": filename,
                    "content_type": "audio/mpeg",
                    "file_size": file_size,
                    "download_url": f"/api/artifacts/{track_id}/download",
                    "path": filepath,
                    "title": track.get("title", ""),
                    "duration": track.get("duration", 0),
                })

            if not artifacts:
                return ToolResult(
                    success=False, data="",
                    error="No audio tracks returned from generation",
                )

            summary_parts = []
            for art in artifacts:
                duration = art.get("duration", 0)
                dur_str = f" ({duration:.0f}s)" if duration else ""
                summary_parts.append(
                    f"{art['filename']}{dur_str}"
                )
            summary = "Generated tracks: " + ", ".join(summary_parts)

            return ToolResult(
                success=True,
                data=summary,
                side_effect={
                    "artifacts": artifacts,
                },
            )
        except Exception as e:
            logger.error("Music generation failed: %s", e)
            return ToolResult(
                success=False, data="", error=str(e),
            )

    async def _load_draft(self, artifact_id: str) -> dict | None:
        """Load a .song.json draft by artifact ID."""
        if self._db:
            row = await self._db.fetchone(
                "SELECT file_path FROM artifacts WHERE id = ?",
                (artifact_id,),
            )
            if row:
                filepath = row[0] if isinstance(row, tuple) else row["file_path"]
                with open(filepath) as f:
                    return json.load(f)

        # Fallback: scan output dir for matching file
        for fname in os.listdir(self._output_dir):
            if artifact_id[:16] in fname and fname.endswith(".song.json"):
                with open(os.path.join(self._output_dir, fname)) as f:
                    return json.load(f)

        return None

    async def _create_task(self, song_data: dict) -> str | None:
        """Submit music generation task to Kie.ai Suno API."""
        prompt = song_data.get("lyrics", "")
        style = song_data.get("style", "")
        title = song_data.get("title", "")
        model = song_data.get("model", "V5")
        instrumental = song_data.get("instrumental", False)
        vocal_gender = song_data.get("vocal_gender", "")
        negative_tags = song_data.get("negative_tags", "")

        # Use custom mode when style or title is provided (lyrics-based)
        custom_mode = bool(style or title)

        payload = {
            "model": "suno",
            "taskType": "suno_music",
            "input": {
                "prompt": prompt,
                "style": style,
                "title": title,
                "model": model,
                "customMode": custom_mode,
                "instrumental": instrumental,
                "negativeTags": negative_tags,
                "vocalGender": vocal_gender,
            },
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{KIE_BASE}/generate",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            data = resp.json()
            if data.get("code") == 200:
                return data["data"]["taskId"]
            logger.error(
                "Kie.ai Suno create failed: %s",
                data.get("msg"),
            )
            return None

    async def _poll_result(self, task_id: str) -> list[dict] | None:
        """Poll for music generation completion with exponential backoff."""
        async with httpx.AsyncClient(timeout=30) as client:
            delay = 3.0
            elapsed = 0.0
            while elapsed < self._max_poll:
                await asyncio.sleep(delay)
                elapsed += delay

                resp = await client.get(
                    f"{KIE_BASE}/generate/record-info",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                    },
                    params={"taskId": task_id},
                )
                data = resp.json()
                if data.get("code") != 200:
                    continue

                info = data.get("data", {})
                state = info.get("state", "")

                if state == "SUCCESS":
                    response = info.get("response", [])
                    if response:
                        return response
                    return None
                elif state in (
                    "CREATE_TASK_FAILED",
                    "GENERATE_AUDIO_FAILED",
                    "SENSITIVE_WORD_ERROR",
                    "CALLBACK_EXCEPTION",
                ):
                    logger.error(
                        "Music gen failed with state: %s",
                        state,
                    )
                    return None

                # PENDING, TEXT_SUCCESS, FIRST_SUCCESS -- keep polling
                delay = min(delay * 1.5, 15.0)

        return None

    async def _download_audio(self, url: str, filename: str) -> str:
        """Download audio file and save to output directory."""
        os.makedirs(self._output_dir, exist_ok=True)
        filepath = os.path.join(self._output_dir, filename)

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)

        logger.info(
            "Downloaded audio: %s (%d bytes)",
            filepath,
            os.path.getsize(filepath),
        )
        return filepath
