"""Image processing tool using Pillow."""
from __future__ import annotations

import asyncio
import logging
import os

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

from odigos.storage import FILES_DIR
ALLOWED_DIR = os.path.realpath(str(FILES_DIR))


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


def _default_output(input_path: str, suffix: str, fmt: str | None = None) -> str:
    """Generate default output path with a suffix."""
    root, ext = os.path.splitext(input_path)
    if fmt:
        ext = "." + fmt.lower().replace("jpeg", "jpg")
    return f"{root}_{suffix}{ext}"


def _get_info(path: str) -> dict:
    from PIL import Image

    with Image.open(path) as img:
        return {
            "width": img.width,
            "height": img.height,
            "format": img.format,
            "mode": img.mode,
            "file_size_bytes": os.path.getsize(path),
        }


def _resize(path: str, output: str, width: int | None, height: int | None):
    from PIL import Image

    with Image.open(path) as img:
        if width and height:
            new_size = (width, height)
        elif width:
            ratio = width / img.width
            new_size = (width, int(img.height * ratio))
        elif height:
            ratio = height / img.height
            new_size = (int(img.width * ratio), height)
        else:
            raise ValueError("Provide width and/or height for resize")
        resized = img.resize(new_size, Image.LANCZOS)
        resized.save(output)
    return new_size


def _crop(path: str, output: str, crop_box: str):
    from PIL import Image

    parts = [int(x.strip()) for x in crop_box.split(",")]
    if len(parts) != 4:
        raise ValueError(
            "crop_box must be 'left,top,right,bottom'"
        )
    box = tuple(parts)
    with Image.open(path) as img:
        cropped = img.crop(box)
        cropped.save(output)
    return box


def _thumbnail(path: str, output: str, width: int, height: int):
    from PIL import Image

    with Image.open(path) as img:
        img.thumbnail((width, height), Image.LANCZOS)
        img.save(output)
        return (img.width, img.height)


def _convert(path: str, output: str, fmt: str):
    from PIL import Image

    with Image.open(path) as img:
        if fmt.upper() in ("JPG", "JPEG") and img.mode == "RGBA":
            img = img.convert("RGB")
        save_fmt = fmt.upper().replace("JPG", "JPEG")
        img.save(output, format=save_fmt)


def _rotate(path: str, output: str, angle: int):
    from PIL import Image

    with Image.open(path) as img:
        rotated = img.rotate(angle, expand=True)
        rotated.save(output)
        return (rotated.width, rotated.height)


class ImageTool(BaseTool):
    name = "process_image"
    description = (
        "Process images: resize, crop, convert format, get info, "
        "create thumbnails. Works with images in the data/files "
        "directory."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "input_path": {
                "type": "string",
                "description": (
                    "Path to input image (relative to data/files "
                    "or absolute within allowed paths)"
                ),
            },
            "action": {
                "type": "string",
                "enum": [
                    "info", "resize", "crop",
                    "thumbnail", "convert", "rotate",
                ],
                "description": "Action to perform on the image",
            },
            "output_path": {
                "type": "string",
                "description": (
                    "Output path (defaults to input with suffix)"
                ),
            },
            "width": {
                "type": "integer",
                "description": "Width for resize/thumbnail",
            },
            "height": {
                "type": "integer",
                "description": "Height for resize/thumbnail",
            },
            "format": {
                "type": "string",
                "enum": ["png", "jpg", "webp"],
                "description": "Target format for convert action",
            },
            "angle": {
                "type": "integer",
                "description": "Rotation angle in degrees",
            },
            "crop_box": {
                "type": "string",
                "description": (
                    "Crop coordinates: 'left,top,right,bottom'"
                ),
            },
        },
        "required": ["input_path", "action"],
    }

    def __init__(self, base_dir: str | None = None):
        self._base_dir = base_dir

    async def execute(self, params: dict) -> ToolResult:
        input_path = params.get("input_path", "")
        action = params.get("action", "")

        if not input_path:
            return ToolResult(
                success=False, data="",
                error="input_path is required",
            )
        if not action:
            return ToolResult(
                success=False, data="",
                error="action is required",
            )

        try:
            resolved_in = _safe_path(input_path, self._base_dir)
        except ValueError as e:
            return ToolResult(
                success=False, data="", error=str(e),
            )

        if not os.path.isfile(resolved_in):
            return ToolResult(
                success=False, data="",
                error=f"File not found: {input_path}",
            )

        try:
            if action == "info":
                info = await asyncio.to_thread(
                    _get_info, resolved_in,
                )
                lines = [f"{k}: {v}" for k, v in info.items()]
                return ToolResult(
                    success=True, data="\n".join(lines),
                )

            # Resolve output path
            out_param = params.get("output_path", "")
            fmt = params.get("format")

            if action == "resize":
                suffix = "resized"
                w = params.get("width")
                h = params.get("height")
                if not out_param:
                    out_param = _default_output(
                        resolved_in, suffix,
                    )
                resolved_out = _safe_path(
                    out_param, self._base_dir,
                )
                new_size = await asyncio.to_thread(
                    _resize, resolved_in, resolved_out, w, h,
                )
                return ToolResult(
                    success=True,
                    data=f"Resized to {new_size[0]}x{new_size[1]}",
                    side_effect={"output_path": resolved_out},
                )

            elif action == "crop":
                crop_box = params.get("crop_box", "")
                if not crop_box:
                    return ToolResult(
                        success=False, data="",
                        error="crop_box is required for crop",
                    )
                if not out_param:
                    out_param = _default_output(
                        resolved_in, "cropped",
                    )
                resolved_out = _safe_path(
                    out_param, self._base_dir,
                )
                box = await asyncio.to_thread(
                    _crop, resolved_in, resolved_out, crop_box,
                )
                return ToolResult(
                    success=True,
                    data=f"Cropped to box {box}",
                    side_effect={"output_path": resolved_out},
                )

            elif action == "thumbnail":
                w = params.get("width", 128)
                h = params.get("height", 128)
                if not out_param:
                    out_param = _default_output(
                        resolved_in, "thumb",
                    )
                resolved_out = _safe_path(
                    out_param, self._base_dir,
                )
                size = await asyncio.to_thread(
                    _thumbnail, resolved_in, resolved_out, w, h,
                )
                return ToolResult(
                    success=True,
                    data=f"Thumbnail created: {size[0]}x{size[1]}",
                    side_effect={"output_path": resolved_out},
                )

            elif action == "convert":
                if not fmt:
                    return ToolResult(
                        success=False, data="",
                        error="format is required for convert",
                    )
                if not out_param:
                    out_param = _default_output(
                        resolved_in, "converted", fmt,
                    )
                resolved_out = _safe_path(
                    out_param, self._base_dir,
                )
                await asyncio.to_thread(
                    _convert, resolved_in, resolved_out, fmt,
                )
                return ToolResult(
                    success=True,
                    data=f"Converted to {fmt.upper()}",
                    side_effect={"output_path": resolved_out},
                )

            elif action == "rotate":
                angle = params.get("angle", 90)
                if not out_param:
                    out_param = _default_output(
                        resolved_in, f"rotated{angle}",
                    )
                resolved_out = _safe_path(
                    out_param, self._base_dir,
                )
                size = await asyncio.to_thread(
                    _rotate, resolved_in, resolved_out, angle,
                )
                return ToolResult(
                    success=True,
                    data=f"Rotated {angle} degrees ({size[0]}x{size[1]})",
                    side_effect={"output_path": resolved_out},
                )

            else:
                return ToolResult(
                    success=False, data="",
                    error=f"Unknown action: {action}",
                )

        except Exception as e:
            logger.warning("Image processing failed: %s", e)
            return ToolResult(
                success=False, data="", error=str(e),
            )
