"""MarpTool — render Markdown slides into PDF, PPTX, or HTML using marp-cli."""
from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path

from odigos.tools.base import ToolResult
from odigos.tools.cli_tool import CLITool

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path("data/artifacts")
VALID_FORMATS = {"pdf", "pptx", "html", "png"}
VALID_THEMES = {"default", "gaia", "uncover"}


class MarpTool(CLITool):
    """Render Markdown slides into PDF, PPTX, or HTML using marp-cli.

    Input must be marp-compatible markdown (--- separators for slides,
    optional YAML frontmatter for theme/marp settings).
    """

    name = "marp"
    COMMAND = "marp"
    category = "media"
    description = (
        "Render Markdown slides into a presentation file (PDF, PPTX, or HTML) "
        "using marp-cli. Input must be marp-compatible markdown with --- "
        "separators between slides. Returns the path to the generated file."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "input_markdown": {
                "type": "string",
                "description": "Marp-compatible markdown content for the slides.",
            },
            "output_format": {
                "type": "string",
                "enum": ["pdf", "pptx", "html", "png"],
                "description": "Output format (default: pdf).",
            },
            "theme": {
                "type": "string",
                "enum": ["default", "gaia", "uncover"],
                "description": "Marp theme (default: default).",
            },
            "title": {
                "type": "string",
                "description": "Title for the output file (used in filename).",
            },
        },
        "required": ["input_markdown"],
    }

    def __init__(self, **kwargs):
        super().__init__(timeout=120.0, **kwargs)

    async def execute(self, params: dict) -> ToolResult:
        markdown = params.get("input_markdown", "").strip()
        if not markdown:
            return ToolResult(
                success=False, data="",
                error="input_markdown is required and cannot be empty.",
            )

        output_format = params.get("output_format", "pdf")
        if output_format not in VALID_FORMATS:
            output_format = "pdf"

        theme = params.get("theme", "default")
        if theme not in VALID_THEMES:
            theme = "default"

        title = params.get("title", "slides")
        safe_title = "".join(
            c if c.isalnum() or c in "-_ " else "" for c in title
        ).strip().replace(" ", "-")[:60] or "slides"

        # Ensure marp: true is in the frontmatter
        if "marp: true" not in markdown:
            if markdown.startswith("---"):
                # Insert marp: true into existing frontmatter
                markdown = markdown.replace("---\n", "---\nmarp: true\n", 1)
            else:
                # Prepend minimal frontmatter
                markdown = f"---\nmarp: true\ntheme: {theme}\n---\n\n{markdown}"

        # Write input to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, prefix="marp-",
        ) as f:
            f.write(markdown)
            input_path = f.name

        # Build output path
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        artifact_id = str(uuid.uuid4())[:8]
        output_filename = f"{safe_title}-{artifact_id}.{output_format}"
        output_path = str(ARTIFACTS_DIR / output_filename)

        # Build marp args
        args = [input_path, "-o", output_path]
        if theme != "default":
            args.extend(["--theme", theme])
        if output_format == "pdf":
            args.append("--pdf")
        elif output_format == "pptx":
            args.append("--pptx")
        elif output_format == "png":
            args.append("--images")
            args.append("png")
        # html is the default, no flag needed

        try:
            result = await self.run_cli(args, timeout=120.0)
        except Exception as exc:
            logger.warning("marp-cli failed: %s", exc)
            # Clean up temp file
            Path(input_path).unlink(missing_ok=True)
            return ToolResult(
                success=False, data="",
                error=f"marp-cli failed: {exc}",
                failure_category="transient",
            )

        # Clean up temp file
        Path(input_path).unlink(missing_ok=True)

        if result.exit_code != 0:
            return ToolResult(
                success=False, data="",
                error=f"marp-cli exited with code {result.exit_code}: {result.stderr[:500]}",
                failure_category="input",
            )

        # Verify output exists
        if not Path(output_path).exists():
            return ToolResult(
                success=False, data="",
                error="marp-cli completed but output file not found.",
                failure_category="transient",
            )

        return ToolResult(
            success=True,
            data=f"Presentation rendered: {output_path}",
            side_effect={
                "artifact": {
                    "path": output_path,
                    "type": output_format,
                    "title": title,
                },
            },
        )
