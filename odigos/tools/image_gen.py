"""Image generation via Kie.ai Z-Image API."""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import httpx

from odigos.tools.api_tool import APITool, ToolAPIError
from odigos.tools.base import ToolContract, ToolResult

logger = logging.getLogger(__name__)

KIE_BASE = "https://api.kie.ai/api/v1"
VALID_RATIOS = {"1:1", "4:3", "3:4", "16:9", "9:16"}


class GenerateImageTool(APITool):
    name = "generate_image"
    category = "create"
    contract = ToolContract(
        timeout_seconds=180,
        max_retries={"transient": 2, "input": 0, "permission": 0, "unavailable": 0, "unknown": 1},
    )
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
                "enum": ["1:1", "4:3", "3:4", "16:9", "9:16"],
                "description": (
                    "Image aspect ratio: 1:1, 4:3, 3:4, 16:9, "
                    "or 9:16. Default: 1:1"
                ),
            },
        },
        "required": ["prompt"],
    }
    API_DOCS = "https://docs.kie.ai/api/z-image"

    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        default_ratio: str = "1:1",
        nsfw_filter: bool = True,
        max_poll_seconds: int = 120,
        output_dir: str = "",
        db=None,
    ):
        super().__init__(http=http)
        self._api_key = api_key
        self._default_ratio = default_ratio
        self._nsfw_filter = nsfw_filter
        self._max_poll = max_poll_seconds
        from odigos.storage import FILES_DIR
        self._output_dir = output_dir or str(FILES_DIR)
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        conversation_id = params.pop("_conversation_id", None)
        prompt = (params.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(success=False, data="", error="No prompt provided")

        if len(prompt) > 1000:
            prompt = prompt[:1000]

        ratio = params.get("aspect_ratio", self._default_ratio)
        if ratio not in VALID_RATIOS:
            ratio = self._default_ratio

        try:
            task_id = await self._create_task(prompt, ratio)
            image_url = await self._poll_result(task_id)

            artifact_id = uuid.uuid4().hex
            slug = re.sub(r"[^a-z0-9]+", "_", prompt[:60].lower()).strip("_")
            filename = f"{slug}_{artifact_id[:8]}.png"
            filepath = await self._download_image(image_url, filename)
            file_size = os.path.getsize(filepath)

            if self._db:
                now = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    "INSERT INTO artifacts "
                    "(id, conversation_id, filename, content_type, "
                    "file_size, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (artifact_id, conversation_id, filename,
                     "image/png", file_size, filepath, now),
                )

            return ToolResult(
                success=True,
                data=f"Image generated: {filename} ({file_size} bytes)",
                side_effect={
                    "artifact": {
                        "id": artifact_id,
                        "filename": filename,
                        "content_type": "image/png",
                        "file_size": file_size,
                        "download_url": f"/api/artifacts/{artifact_id}/download",
                        "path": filepath,
                    }
                },
            )
        except ToolAPIError as e:
            logger.error("Image generation API error: %s", e.message)
            return ToolResult(
                success=False, data="", error=e.message,
                failure_category=e.failure_category,
            )
        except Exception as e:
            logger.error("Image generation failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))

    async def _create_task(self, prompt: str, ratio: str) -> str:
        """Submit image generation task. Returns taskId."""
        data = await self.api_post(
            f"{KIE_BASE}/jobs/createTask",
            payload={
                "model": "z-image",
                "input": {
                    "prompt": prompt,
                    "aspect_ratio": ratio,
                    "nsfw_checker": self._nsfw_filter,
                },
            },
            api_key=self._api_key,
        )
        if data.get("code") != 200:
            raise ToolAPIError(0, data.get("msg", "Create task failed"), "transient")
        return data["data"]["taskId"]

    async def _poll_result(self, task_id: str) -> str:
        """Poll for task completion. Returns image URL."""
        return await self.poll_until(
            f"{KIE_BASE}/jobs/recordInfo",
            api_key=self._api_key,
            params={"taskId": task_id},
            success_check=lambda d: (
                d.get("code") == 200
                and d.get("data", {}).get("state") == "success"
            ),
            failure_check=lambda d: (
                d.get("code") == 200
                and d.get("data", {}).get("state") == "fail"
            ),
            extract=lambda d: json.loads(
                d["data"].get("resultJson", "{}")
            ).get("resultUrls", [None])[0],
            max_seconds=self._max_poll,
            initial_delay=2.0,
            max_delay=10.0,
        )

    async def _download_image(self, url: str, filename: str) -> str:
        """Download image and save to output directory."""
        os.makedirs(self._output_dir, exist_ok=True)
        filepath = os.path.join(self._output_dir, filename)

        resp = await self.http.get(url, timeout=httpx.Timeout(60))
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)

        logger.info("Downloaded image: %s (%d bytes)", filepath, os.path.getsize(filepath))
        return filepath

    def format_for_context(self, result: ToolResult) -> str:
        if result.success:
            return result.data
        return f"Image generation failed: {result.error}"
