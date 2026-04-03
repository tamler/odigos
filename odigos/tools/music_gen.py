"""Music generation via Kie.ai Suno API."""
from __future__ import annotations

import asyncio
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
        timeout_seconds=240,
        max_retries={"transient": 2, "input": 0, "permission": 0, "unavailable": 0, "unknown": 1},
    )
    description = (
        "Generate a music track from lyrics or a description. "
        "Returns playable audio. For lyrics review before generating, "
        "write them to a notebook first and let the user edit."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Lyrics or description of the music to generate (max 5000 chars)",
            },
            "style": {
                "type": "string",
                "description": "Musical style/genre (e.g., 'indie folk, acoustic'). Max 1000 chars.",
            },
            "title": {
                "type": "string",
                "description": "Song title (max 80 chars)",
            },
            "instrumental": {
                "type": "string",
                "enum": ["true", "false"],
                "description": "Instrumental only, no vocals (default 'false')",
            },
            "vocal_gender": {
                "type": "string",
                "enum": ["", "m", "f"],
                "description": "Preferred vocal gender",
            },
        },
        "required": ["prompt"],
    }

    def __init__(
        self,
        api_key: str,
        provider: str = "suno",
        task_type: str = "suno_music",
        model: str = "V5_5",
        max_poll_seconds: int = 180,
        output_dir: str = "",
        db=None,
    ):
        self._api_key = api_key
        self._model = model
        self._max_poll = max_poll_seconds
        from odigos.storage import FILES_DIR
        self._output_dir = output_dir or str(FILES_DIR)
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        conversation_id = params.pop("_conversation_id", None)
        prompt = (params.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(success=False, data="", error="No prompt provided")

        style = (params.get("style") or "").strip()[:1000]
        title = (params.get("title") or "").strip()[:80]
        instrumental = str(params.get("instrumental", "false")).lower() == "true"
        vocal_gender = params.get("vocal_gender", "")
        if vocal_gender not in ("m", "f"):
            vocal_gender = ""

        try:
            task_id = await self._create_task(
                prompt=prompt, style=style, title=title,
                instrumental=instrumental, vocal_gender=vocal_gender,
            )
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

            artifacts = []
            for i, track in enumerate(tracks):
                # API uses both audio_url (callback) and audioUrl (poll)
                audio_url = track.get("audio_url") or track.get("audioUrl", "")
                if not audio_url:
                    continue

                track_id = uuid.uuid4().hex
                track_title = track.get("title") or title or f"track_{i + 1}"
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
                    "title": track_title,
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
                summary_parts.append(f"{art['filename']}{dur_str}")

            return ToolResult(
                success=True,
                data="Generated tracks: " + ", ".join(summary_parts),
                side_effect={"artifacts": artifacts},
            )
        except Exception as e:
            logger.error("Music generation failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))

    async def _create_task(
        self,
        prompt: str,
        style: str = "",
        title: str = "",
        instrumental: bool = False,
        vocal_gender: str = "",
    ) -> str | None:
        """Submit music generation task to Kie.ai API.

        See: https://docs.kie.ai/suno-api/generate-music
        """
        custom_mode = bool(style or title)

        payload: dict = {
            "prompt": prompt[:5000],
            "model": self._model,
            "customMode": custom_mode,
            "instrumental": instrumental,
            "callBackUrl": "",
        }
        if custom_mode:
            if style:
                payload["style"] = style
            if title:
                payload["title"] = title
        if vocal_gender:
            payload["vocalGender"] = vocal_gender

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    f"{KIE_BASE}/generate",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                data = resp.json()
            except Exception as e:
                logger.error("Kie.ai request failed: %s", e)
                return None

            if data.get("code") == 200:
                return data["data"]["taskId"]

            logger.error(
                "Kie.ai create failed (code %s): %s",
                data.get("code"), data.get("msg"),
            )
            return None

    async def _poll_result(self, task_id: str) -> list[dict]:
        """Poll for music generation completion."""
        async with httpx.AsyncClient(timeout=30) as client:
            delay = 5.0
            elapsed = 0.0
            while elapsed < self._max_poll:
                await asyncio.sleep(delay)
                elapsed += delay

                try:
                    resp = await client.get(
                        f"{KIE_BASE}/generate/record-info",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        params={"taskId": task_id},
                    )
                    data = resp.json()
                except Exception as e:
                    logger.warning("Poll failed: %s", e)
                    delay = min(delay * 1.5, 15.0)
                    continue

                if data.get("code") != 200:
                    delay = min(delay * 1.5, 15.0)
                    continue

                info = data.get("data", {})
                status = info.get("status") or info.get("state", "")

                if status == "SUCCESS":
                    return self._extract_tracks(info.get("response", {}))

                if status in (
                    "CREATE_TASK_FAILED", "GENERATE_AUDIO_FAILED",
                    "SENSITIVE_WORD_ERROR", "CALLBACK_EXCEPTION",
                ):
                    logger.error("Music gen failed: %s", info.get("errorMessage", status))
                    return []

                delay = min(delay * 1.5, 15.0)

        return []

    @staticmethod
    def _extract_tracks(response: object) -> list[dict]:
        """Extract audio tracks from API response."""
        if isinstance(response, list):
            return [t for t in response if isinstance(t, dict) and (t.get("audioUrl") or t.get("audio_url"))]
        if isinstance(response, dict):
            for value in response.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    tracks = [t for t in value if t.get("audioUrl") or t.get("audio_url")]
                    if tracks:
                        return tracks
        return []

    async def _download_audio(self, url: str, filename: str) -> str:
        """Download audio file and save to output directory."""
        from odigos import aio
        os.makedirs(self._output_dir, exist_ok=True)
        filepath = os.path.join(self._output_dir, filename)

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            await aio.write_bytes(filepath, resp.content)

        logger.info("Downloaded audio: %s (%d bytes)", filepath, os.path.getsize(filepath))
        return filepath
