"""Music generation via Kie.ai Suno API."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

import httpx

from odigos.tools.api_tool import APITool, ToolAPIError
from odigos.tools.base import ToolContract, ToolResult

logger = logging.getLogger(__name__)

KIE_BASE = "https://api.kie.ai/api/v1"

FAILURE_STATES = {
    "CREATE_TASK_FAILED",
    "GENERATE_AUDIO_FAILED",
    "SENSITIVE_WORD_ERROR",
    "CALLBACK_EXCEPTION",
}


class GenerateMusicTool(APITool):
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
                "type": "boolean",
                "description": "Instrumental only, no vocals (default false)",
            },
            "vocal_gender": {
                "type": "string",
                "enum": ["", "m", "f"],
                "description": "Preferred vocal gender",
            },
        },
        "required": ["prompt"],
    }
    API_DOCS = "https://docs.kie.ai/suno-api/generate-music"

    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        model: str = "V5_5",
        max_poll_seconds: int = 180,
        output_dir: str = "",
        db=None,
    ):
        super().__init__(http=http)
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
        # instrumental is now a bool (coerced by executor)
        instrumental = params.get("instrumental", False)
        if isinstance(instrumental, str):
            instrumental = instrumental.lower() == "true"
        vocal_gender = params.get("vocal_gender", "")
        if vocal_gender not in ("m", "f"):
            vocal_gender = ""

        try:
            internal_task_id = uuid.uuid4().hex
            cb_url = self.callback_url(internal_task_id)

            task_id = await self._create_task(
                prompt=prompt, style=style, title=title,
                instrumental=instrumental, vocal_gender=vocal_gender,
                callback_url=cb_url,
            )
            return ToolResult(
                success=True,
                status="pending",
                task_id=task_id,
                data=f"Music generation started for: {(title or prompt)[:80]}. I'll notify you when it's ready.",
                side_effect={
                    "background_task": {
                        "id": internal_task_id,
                        "tool_name": self.name,
                        "external_task_id": task_id,
                        "conversation_id": conversation_id,
                        "arguments": {
                            "prompt": prompt,
                            "style": style,
                            "title": title,
                            "instrumental": instrumental,
                            "vocal_gender": vocal_gender,
                        },
                    }
                },
            )
        except ToolAPIError as e:
            logger.error("Music generation API error: %s", e.message)
            return ToolResult(
                success=False, data="", error=e.message,
                failure_category=e.failure_category,
            )
        except Exception as e:
            logger.error("Music generation failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))

    async def complete_background(self, task_id: str, conversation_id: str) -> ToolResult:
        """Poll once and complete if ready. Called by heartbeat."""
        try:
            status, result = await self.poll_once(
                f"{KIE_BASE}/generate/record-info",
                api_key=self._api_key,
                params={"taskId": task_id},
                success_check=lambda d: (
                    d.get("code") == 200
                    and (d.get("data", {}).get("status") or d.get("data", {}).get("state", ""))
                    == "SUCCESS"
                ),
                failure_check=lambda d: (
                    d.get("code") == 200
                    and (d.get("data", {}).get("status") or d.get("data", {}).get("state", ""))
                    in FAILURE_STATES
                ),
                extract=lambda d: d.get("data", {}).get("response", {}),
            )

            if status == "pending":
                return ToolResult(success=True, status="pending", data="Still processing...")

            if status == "failed":
                return ToolResult(
                    success=False, data="", error="Music generation failed",
                    failure_category="transient",
                )

            # status == "done" — download and store artifacts
            tracks = self._extract_tracks(result)
            if not tracks:
                return ToolResult(
                    success=False, data="",
                    error="No audio tracks returned from generation",
                )

            artifacts = []
            for i, track in enumerate(tracks):
                audio_url = track.get("audio_url") or track.get("audioUrl", "")
                if not audio_url:
                    continue

                track_id = uuid.uuid4().hex
                track_title = track.get("title") or f"track_{i + 1}"
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
            logger.error("Background music completion failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))

    async def complete_from_callback(
        self, task_id: str, conversation_id: str, callback_data: dict,
    ) -> ToolResult:
        """Process callback from Kie.ai when music generation completes.

        Kie.ai callback format (documented from actual payload):
            {"code": 200, "data": {"callbackType": "complete", "data": [
                {"audio_url": "...", "title": "...", "duration": 17.92, ...},
                ...
            ]}}
        Tracks are at: callback_data["data"]["data"]
        """
        try:
            tracks = callback_data.get("data", {}).get("data", [])
            if not isinstance(tracks, list) or not tracks:
                logger.error(
                    "Unexpected callback format. code=%s, data_keys=%s",
                    callback_data.get("code"),
                    list(callback_data.get("data", {}).keys()) if isinstance(callback_data.get("data"), dict) else type(callback_data.get("data")),
                )
                return ToolResult(success=False, data="", error="No tracks in callback data")

            artifacts = []
            for i, track in enumerate(tracks):
                audio_url = track.get("audio_url") or track.get("audioUrl", "")
                if not audio_url:
                    continue

                track_id = uuid.uuid4().hex
                track_title = track.get("title") or f"track_{i + 1}"
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
                return ToolResult(success=False, data="", error="No downloadable audio tracks in callback")

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
            logger.error("Callback music completion failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))

    async def _create_task(
        self,
        prompt: str,
        style: str = "",
        title: str = "",
        instrumental: bool = False,
        vocal_gender: str = "",
        callback_url: str = "",
    ) -> str:
        """Submit music generation task. Returns taskId."""
        custom_mode = bool(style or title)
        payload: dict = {
            "prompt": prompt[:5000],
            "model": self._model,
            "customMode": custom_mode,
            "instrumental": instrumental,
            "callBackUrl": callback_url or "https://localhost/callback",
        }
        if custom_mode:
            if style:
                payload["style"] = style
            if title:
                payload["title"] = title
        if vocal_gender:
            payload["vocalGender"] = vocal_gender

        data = await self.api_post(
            f"{KIE_BASE}/generate",
            payload=payload,
            api_key=self._api_key,
        )
        if data.get("code") != 200:
            raise ToolAPIError(0, data.get("msg", "Create task failed"), "transient")
        return data["data"]["taskId"]

    async def _poll_result(self, task_id: str) -> list[dict]:
        """Poll for music generation completion. Returns track list."""
        raw = await self.poll_until(
            f"{KIE_BASE}/generate/record-info",
            api_key=self._api_key,
            params={"taskId": task_id},
            success_check=lambda d: (
                d.get("code") == 200
                and (d.get("data", {}).get("status") or d.get("data", {}).get("state", ""))
                == "SUCCESS"
            ),
            failure_check=lambda d: (
                d.get("code") == 200
                and (d.get("data", {}).get("status") or d.get("data", {}).get("state", ""))
                in FAILURE_STATES
            ),
            extract=lambda d: d.get("data", {}).get("response", {}),
            max_seconds=self._max_poll,
            initial_delay=5.0,
            max_delay=15.0,
        )
        return self._extract_tracks(raw)

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

        resp = await self.http.get(url, timeout=httpx.Timeout(120))
        resp.raise_for_status()
        await aio.write_bytes(filepath, resp.content)

        logger.info("Downloaded audio: %s (%d bytes)", filepath, os.path.getsize(filepath))
        return filepath

    def format_for_context(self, result: ToolResult) -> str:
        if result.success:
            return result.data
        return f"Music generation failed: {result.error}"
