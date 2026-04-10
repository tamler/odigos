"""Tests for MarpTool slide renderer."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from odigos.tools.marp_tool import MarpTool


SAMPLE_SLIDES = """---
marp: true
theme: default
---

# Slide 1: Introduction

This is a test presentation.

---

# Slide 2: Key Points

- Point one
- Point two
- Point three

---

# Slide 3: Conclusion

Thank you!
"""


class TestMarpTool:
    def test_tool_metadata(self):
        tool = MarpTool()
        assert tool.name == "marp"
        assert tool.category == "media"
        assert "slide" in tool.description.lower() or "presentation" in tool.description.lower()

    async def test_execute_writes_input_and_calls_cli(self):
        tool = MarpTool()

        # Mock run_cli to simulate marp producing output
        async def fake_run_cli(args, **kwargs):
            from odigos.tools.cli_tool import CLIResult
            # Find the output path from args
            output_idx = args.index("-o") + 1 if "-o" in args else None
            if output_idx:
                Path(args[output_idx]).write_text("fake pdf content")
            return CLIResult(exit_code=0, stdout="", stderr="")

        tool.run_cli = fake_run_cli

        result = await tool.execute({
            "input_markdown": SAMPLE_SLIDES,
            "output_format": "pdf",
        })

        assert result.success is True
        assert result.data  # should contain artifact path
        assert "pdf" in result.data.lower() or "artifact" in result.data.lower()

    async def test_execute_handles_missing_markdown(self):
        tool = MarpTool()
        result = await tool.execute({"input_markdown": ""})
        assert result.success is False
        assert "markdown" in (result.error or "").lower() or "empty" in (result.error or "").lower()

    async def test_execute_handles_cli_failure(self):
        tool = MarpTool()

        async def fake_run_cli(args, **kwargs):
            from odigos.tools.cli_tool import CLIResult
            return CLIResult(exit_code=1, stdout="", stderr="Error: invalid markdown")

        tool.run_cli = fake_run_cli

        result = await tool.execute({
            "input_markdown": SAMPLE_SLIDES,
            "output_format": "pdf",
        })

        assert result.success is False
