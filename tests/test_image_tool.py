"""Tests for the image processing tool."""
from __future__ import annotations

import asyncio

import pytest
from PIL import Image

from odigos.tools.image import ImageTool


def _make_image(path, width=200, height=100, color="red", fmt="PNG"):
    """Create a test image at the given path."""
    img = Image.new("RGB", (width, height), color=color)
    img.save(str(path), format=fmt)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def tool(tmp_path):
    return ImageTool(base_dir=str(tmp_path))


@pytest.fixture
def sample_image(tmp_path):
    path = tmp_path / "test.png"
    _make_image(path)
    return path


def test_tool_metadata(tool):
    assert tool.name == "process_image"
    props = tool.parameters_schema["properties"]
    assert "input_path" in props
    assert "action" in props
    assert "width" in props
    assert "height" in props
    assert "format" in props
    assert "angle" in props
    assert "crop_box" in props
    required = tool.parameters_schema["required"]
    assert "input_path" in required
    assert "action" in required


def test_info_action(tool, sample_image):
    result = _run(tool.execute({
        "input_path": sample_image.name,
        "action": "info",
    }))
    assert result.success
    assert "200" in result.data
    assert "100" in result.data
    assert "PNG" in result.data


def test_resize(tool, sample_image):
    result = _run(tool.execute({
        "input_path": sample_image.name,
        "action": "resize",
        "width": 100,
        "height": 50,
    }))
    assert result.success
    assert "100x50" in result.data
    out = result.side_effect["output_path"]
    with Image.open(out) as img:
        assert img.width == 100
        assert img.height == 50


def test_resize_width_only(tool, sample_image):
    result = _run(tool.execute({
        "input_path": sample_image.name,
        "action": "resize",
        "width": 100,
    }))
    assert result.success
    out = result.side_effect["output_path"]
    with Image.open(out) as img:
        assert img.width == 100
        assert img.height == 50  # aspect ratio preserved


def test_thumbnail(tool, sample_image):
    result = _run(tool.execute({
        "input_path": sample_image.name,
        "action": "thumbnail",
        "width": 50,
        "height": 50,
    }))
    assert result.success
    out = result.side_effect["output_path"]
    with Image.open(out) as img:
        assert img.width <= 50
        assert img.height <= 50


def test_convert_format(tool, tmp_path):
    png_path = tmp_path / "convert_test.png"
    _make_image(png_path)
    result = _run(tool.execute({
        "input_path": png_path.name,
        "action": "convert",
        "format": "jpg",
    }))
    assert result.success
    assert "JPG" in result.data
    out = result.side_effect["output_path"]
    with Image.open(out) as img:
        assert img.format == "JPEG"


def test_rotate(tool, sample_image):
    result = _run(tool.execute({
        "input_path": sample_image.name,
        "action": "rotate",
        "angle": 90,
    }))
    assert result.success
    out = result.side_effect["output_path"]
    with Image.open(out) as img:
        assert img.width == 100
        assert img.height == 200


def test_crop(tool, sample_image):
    result = _run(tool.execute({
        "input_path": sample_image.name,
        "action": "crop",
        "crop_box": "10,10,100,50",
    }))
    assert result.success
    out = result.side_effect["output_path"]
    with Image.open(out) as img:
        assert img.width == 90
        assert img.height == 40


def test_path_traversal_blocked(tool):
    result = _run(tool.execute({
        "input_path": "../../etc/passwd",
        "action": "info",
    }))
    assert not result.success
    assert "outside allowed directory" in result.error.lower()


def test_missing_file(tool):
    result = _run(tool.execute({
        "input_path": "nonexistent.png",
        "action": "info",
    }))
    assert not result.success
    assert "not found" in result.error.lower()
