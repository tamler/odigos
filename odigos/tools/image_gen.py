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
from odigos.tools.gate import ToolGate

logger = logging.getLogger(__name__)

KIE_BASE = "https://api.kie.ai/api/v1"
VALID_RATIOS = {"1:1", "4:3", "3:4", "16:9", "9:16"}


class GenerateImageTool(APITool):
    name = "generate_image"
    gate = ToolGate.service("kie_ai")
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

    # Flat per-image cost for Z-Image on Kie.ai (2026-04 pricing).
    # Future: read from ModelConfig.cost_per_unit once capabilities-config lands.
    COST_PER_IMAGE_USD = 0.03

    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        default_ratio: str = "1:1",
        nsfw_filter: bool = True,
        max_poll_seconds: int = 120,
        output_dir: str = "",
        db=None,
        budget_tracker=None,
    ):
        super().__init__(http=http)
        self._api_key = api_key
        self._default_ratio = default_ratio
        self._nsfw_filter = nsfw_filter
        self._max_poll = max_poll_seconds
        from odigos.storage import FILES_DIR
        self._output_dir = output_dir or str(FILES_DIR)
        self._db = db
        self._budget_tracker = budget_tracker

    async def _record_cost(self, conversation_id: str | None, ratio: str) -> None:
        """Record one successful image generation against the budget cap."""
        if not self._budget_tracker:
            return
        try:
            await self._budget_tracker.record_tool_cost(
                self.COST_PER_IMAGE_USD,
                source="kie_image",
                conversation_id=conversation_id,
                tool_name=self.name,
                metadata={"aspect_ratio": ratio},
            )
        except Exception as e:
            logger.warning("Failed to record image cost: %s", e)

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
            internal_task_id = uuid.uuid4().hex
            cb_url = self.callback_url(internal_task_id)

            task_id = await self._create_task(prompt, ratio, callback_url=cb_url)
            return ToolResult(
                success=True,
                status="pending",
                task_id=task_id,
                data=f"Image generation started for: {prompt[:80]}. I'll notify you when it's ready.",
                side_effect={
                    "background_task": {
                        "id": internal_task_id,
                        "tool_name": self.name,
                        "external_task_id": task_id,
                        "conversation_id": conversation_id,
                        "arguments": {"prompt": prompt, "aspect_ratio": ratio},
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

    async def complete_background(self, task_id: str, conversation_id: str) -> ToolResult:
        """Poll once and complete if ready. Called by heartbeat."""
        try:
            status, result = await self.poll_once(
                f"{KIE_BASE}/jobs/recordInfo",
                api_key=self._api_key,
                params={"taskId": task_id},
                success_check=lambda d: d.get("code") == 200 and d.get("data", {}).get("state") == "success",
                failure_check=lambda d: d.get("code") == 200 and d.get("data", {}).get("state") == "fail",
                extract=lambda d: json.loads(d["data"].get("resultJson", "{}")).get("resultUrls", [None])[0],
            )

            if status == "pending":
                return ToolResult(success=True, status="pending", data="Still processing...")

            if status == "failed":
                return ToolResult(
                    success=False, data="", error="Image generation failed",
                    failure_category="transient",
                )

            # status == "done" — download and store artifact
            image_url = result
            if not image_url:
                return ToolResult(success=False, data="", error="No image URL in result")

            artifact_id = uuid.uuid4().hex
            slug = re.sub(r"[^a-z0-9]+", "_", task_id[:20].lower()).strip("_")
            filename = f"bg_{slug}_{artifact_id[:8]}.png"
            filepath = await self._download_image(image_url, filename)
            file_size = os.path.getsize(filepath)

            if self._db:
                now = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    "INSERT INTO artifacts "
                    "(id, conversation_id, filename, content_type, file_size, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (artifact_id, conversation_id, filename, "image/png", file_size, filepath, now),
                )

            await self._record_cost(conversation_id, self._default_ratio)

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
        except Exception as e:
            logger.error("Background image completion failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))

    async def complete_from_callback(
        self, task_id: str, conversation_id: str, callback_data: dict,
    ) -> ToolResult:
        """Process callback from Kie.ai when image generation completes."""
        try:
            # Extract image URL from callback payload — try standard paths
            data_block = callback_data.get("data", callback_data)
            result_json_raw = data_block.get("resultJson", "{}")
            if isinstance(result_json_raw, str):
                result_json = json.loads(result_json_raw)
            else:
                result_json = result_json_raw

            image_url = (result_json.get("resultUrls") or [None])[0]
            if not image_url:
                # Fallback: check alternate field names
                image_url = data_block.get("imageUrl") or data_block.get("image_url")

            if not image_url:
                return ToolResult(success=False, data="", error="No image URL in callback data")

            artifact_id = uuid.uuid4().hex
            slug = re.sub(r"[^a-z0-9]+", "_", task_id[:20].lower()).strip("_")
            filename = f"cb_{slug}_{artifact_id[:8]}.png"
            filepath = await self._download_image(image_url, filename)
            file_size = os.path.getsize(filepath)

            if self._db:
                now = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    "INSERT INTO artifacts "
                    "(id, conversation_id, filename, content_type, file_size, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (artifact_id, conversation_id, filename, "image/png", file_size, filepath, now),
                )

            await self._record_cost(conversation_id, self._default_ratio)

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
        except Exception as e:
            logger.error("Callback image completion failed: %s", e)
            return ToolResult(success=False, data="", error=str(e))

    async def _create_task(self, prompt: str, ratio: str, callback_url: str = "") -> str:
        """Submit image generation task. Returns taskId."""
        payload: dict = {
            "model": "z-image",
            "input": {
                "prompt": prompt,
                "aspect_ratio": ratio,
                "nsfw_checker": self._nsfw_filter,
            },
        }
        if callback_url:
            payload["callBackUrl"] = callback_url
        data = await self.api_post(
            f"{KIE_BASE}/jobs/createTask",
            payload=payload,
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
