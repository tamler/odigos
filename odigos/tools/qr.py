"""QR code generation tool."""
from __future__ import annotations

import logging
import secrets
from pathlib import Path

from odigos.storage import FILES_DIR
from odigos.core.capabilities import record_degraded
from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class QRCodeTool(BaseTool):
    """Generate QR codes from text, URLs, or structured data."""

    name = "generate_qr"
    category = "create"
    description = (
        "Generate a QR code image from text, a URL, WiFi credentials, contact info, "
        "or any data. Returns a downloadable PNG image. "
        "Use when the user wants to share a link, WiFi password, or contact via QR. "
        "Do not use for general image creation — use generate_image for that."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": (
                    "Content to encode. Plain text, URL, or structured format. "
                    "For WiFi: 'WIFI:T:WPA;S:NetworkName;P:Password;;' "
                    "For vCard: 'BEGIN:VCARD\\nVERSION:3.0\\nFN:Name\\nTEL:+1234567890\\nEND:VCARD'"
                ),
            },
            "size": {
                "type": "integer",
                "description": "Image size in pixels (default 400, min 100, max 2000).",
            },
        },
        "required": ["data"],
    }

    def __init__(self, db=None):
        self._db = db

    async def execute(self, params: dict) -> ToolResult:
        data = params.get("data", "").strip()
        params.pop("_conversation_id", None)
        params.pop("_goal_id", None)
        if not data:
            return ToolResult(success=False, data="", error="No data provided")

        try:
            import qrcode
            from PIL import Image
        except ImportError as e:
            record_degraded("qrcode", e)
            return ToolResult(success=False, data="", error="qrcode library not installed")

        size = min(max(params.get("size", 400), 100), 2000)

        try:
            qr = qrcode.QRCode(box_size=10, border=2)
            qr.add_data(data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            img = img.resize((size, size), Image.NEAREST)

            FILES_DIR.mkdir(parents=True, exist_ok=True)
            file_id = secrets.token_hex(8)
            filename = f"qrcode_{file_id}.png"
            filepath = FILES_DIR / filename
            img.save(str(filepath))

            file_size = filepath.stat().st_size

            if self._db:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    "INSERT OR IGNORE INTO artifacts "
                    "(id, filename, content_type, file_size, file_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (file_id, filename, "image/png", file_size, str(filepath), now),
                )

            preview = data[:100] + "..." if len(data) > 100 else data
            return ToolResult(
                success=True,
                data=f"QR code generated for: {preview}",
                side_effect={
                    "artifact": {
                        "id": file_id,
                        "filename": filename,
                        "content_type": "image/png",
                        "file_size": file_size,
                        "download_url": f"/api/artifacts/{file_id}/download",
                    },
                },
            )
        except Exception as e:
            return ToolResult(success=False, data="", error=str(e))
