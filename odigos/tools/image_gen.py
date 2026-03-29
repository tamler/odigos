"""Image generation via Kie.ai Z-Image API."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

KIE_BASE = "https://api.kie.ai/api/v1"
VALID_RATIOS = {"1:1", "4:3", "3:4", "16:9", "9:16"}


class GenerateImageTool(BaseTool):
    name = "generate_image"
    description = (
        "Generate an image from a text description using Z-Image AI. "
        "Provide a detailed prompt describing the image you want. "
        "The prompt should include subject, setting, lighting, "
        "style, and composition details for best results. "
        "Supports aspect ratios: 1:1, 4:3, 3:4, 16:9, 9:16."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "Detailed image description. Include subject, "
                    "setting, lighting, style, composition. "
                    "Max 1000 characters."
                ),
            },
            "aspect_ratio": {
                "type": "string",
                "description": (
                    "Image aspect ratio: 1:1, 4:3, 3:4, 16:9, "
                    "or 9:16. Default: 1:1"
                ),
            },
        },
        "required": ["prompt"],
    }

    def __init__(
        self,
        api_key: str,
        default_ratio: str = "1:1",
        nsfw_filter: bool = True,
        max_poll_seconds: int = 120,
        output_dir: str = "data/files",
        db=None,
    ):
        self._api_key = api_key
        self._default_ratio = default_ratio
        self._nsfw_filter = nsfw_filter
        self._max_poll = max_poll_seconds
        self._output_dir = output_dir
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        conversation_id = params.pop("_conversation_id", None)
        prompt = (params.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(
                success=False, data="", error="No prompt provided"
            )

        if len(prompt) > 1000:
            prompt = prompt[:1000]

        ratio = params.get("aspect_ratio", self._default_ratio)
        if ratio not in VALID_RATIOS:
            ratio = self._default_ratio

        try:
            task_id = await self._create_task(prompt, ratio)
            if not task_id:
                return ToolResult(
                    success=False,
                    data="",
                    error="Failed to create image task",
                )

            image_url = await self._poll_result(task_id)
            if not image_url:
                return ToolResult(
                    success=False,
                    data="",
                    error="Image generation timed out or failed",
                )

            artifact_id = uuid.uuid4().hex
            filename = f"generated_{artifact_id[:8]}.png"
            filepath = await self._download_image(
                image_url, filename,
            )
            file_size = os.path.getsize(filepath)

            # Register in artifacts database
            if self._db:
                now = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    "INSERT INTO artifacts "
                    "(id, conversation_id, filename, content_type, "
                    "file_size, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (artifact_id, conversation_id, filename,
                     "image/png", file_size, now),
                )

            return ToolResult(
                success=True,
                data=f"Image generated: {filename}"
                f" ({file_size} bytes)",
                side_effect={
                    "artifact": {
                        "id": artifact_id,
                        "filename": filename,
                        "content_type": "image/png",
                        "file_size": file_size,
                        "download_url":
                            f"/api/artifacts/"
                            f"{artifact_id}/download",
                        "path": filepath,
                    }
                },
            )
        except Exception as e:
            logger.error("Image generation failed: %s", e)
            return ToolResult(
                success=False, data="", error=str(e),
            )

    async def _create_task(
        self, prompt: str, ratio: str,
    ) -> str | None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{KIE_BASE}/jobs/createTask",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "z-image",
                    "input": {
                        "prompt": prompt,
                        "aspect_ratio": ratio,
                        "nsfw_checker": self._nsfw_filter,
                    },
                },
            )
            data = resp.json()
            if data.get("code") == 200:
                return data["data"]["taskId"]
            logger.error(
                "Kie.ai create failed: %s",
                data.get("msg"),
            )
            return None

    async def _poll_result(
        self, task_id: str,
    ) -> str | None:
        """Poll for task completion with exponential backoff."""
        async with httpx.AsyncClient(timeout=30) as client:
            delay = 2.0
            elapsed = 0.0
            while elapsed < self._max_poll:
                await asyncio.sleep(delay)
                elapsed += delay

                resp = await client.get(
                    f"{KIE_BASE}/jobs/recordInfo",
                    headers={
                        "Authorization": (
                            f"Bearer {self._api_key}"
                        ),
                    },
                    params={"taskId": task_id},
                )
                data = resp.json()
                if data.get("code") != 200:
                    continue

                info = data.get("data", {})
                state = info.get("state", "")

                if state == "success":
                    result_json = info.get(
                        "resultJson", "{}"
                    )
                    result = json.loads(result_json)
                    urls = result.get("resultUrls", [])
                    if urls:
                        return urls[0]
                    return None
                elif state == "fail":
                    logger.error(
                        "Image gen failed: %s",
                        info.get("failMsg", "unknown"),
                    )
                    return None

                delay = min(delay * 1.5, 10.0)

        return None

    async def _download_image(
        self, url: str, filename: str,
    ) -> str:
        """Download image and save to output directory."""
        os.makedirs(self._output_dir, exist_ok=True)
        filepath = os.path.join(self._output_dir, filename)

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)

        logger.info(
            "Downloaded image: %s (%d bytes)",
            filepath,
            os.path.getsize(filepath),
        )
        return filepath
