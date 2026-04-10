# Marp Tool + Research-Present Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Marp slide rendering tool and a `presenter` persona, then wire the first end-to-end sub-agent demonstration: user asks for a primer → researcher sub-agent gathers info → presenter sub-agent formats Marp slides → marp tool renders PDF → orchestrator delivers the artifact.

**Architecture:** `MarpTool` extends `CLITool`, calls `npx @marp-team/marp-cli` to render markdown slides into PDF/PPTX/HTML. The `presenter` persona already exists in `data/subagents/` but needs `marp` in its tools list. The research-present workflow is just a chained `run_subagent` call with `on_complete` — no new orchestration code needed.

**Tech Stack:** `@marp-team/marp-cli` (npm), Python `CLITool` base class, existing sub-agent dispatch + chaining.

**Spec:** Section 8 of `docs/superpowers/specs/2026-04-10-subagents-orchestration-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `odigos/tools/marp_tool.py` | MarpTool extending CLITool — renders markdown slides to PDF/PPTX/HTML |
| `tests/test_marp_tool.py` | Tool tests |

### Modified Files

| File | Change |
|------|--------|
| `data/subagents/presenter.md` | NEW persona for slide generation |
| `odigos/bootstrap.py` | Register MarpTool |
| `Dockerfile` | Install `@marp-team/marp-cli` globally |

---

### Task 1: Install Marp CLI

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Check current Dockerfile for Node.js**

```bash
grep -n "node\|npm\|npx" Dockerfile | head -10
```

If Node.js is already installed (it should be for the dashboard build), we just add the marp-cli package. If not, we need to install Node first.

- [ ] **Step 2: Add marp-cli installation**

Find the layer where npm packages are installed (or after the Node.js install). Add:

```dockerfile
# Marp CLI for slide rendering (used by MarpTool)
RUN npm install -g @marp-team/marp-cli
```

If the Dockerfile uses a multi-stage build, this needs to go in the runtime stage (not just the builder), since the tool runs at runtime.

- [ ] **Step 3: Verify marp-cli works locally**

```bash
npx @marp-team/marp-cli --version
```

If `npx` isn't available locally, install globally:

```bash
npm install -g @marp-team/marp-cli && marp --version
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "feat: install marp-cli in Docker image for slide rendering"
```

---

### Task 2: MarpTool

**Files:**
- Create: `odigos/tools/marp_tool.py`
- Create: `tests/test_marp_tool.py`
- Modify: `odigos/bootstrap.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_marp_tool.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_marp_tool.py -x -q`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create MarpTool**

Create `odigos/tools/marp_tool.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_marp_tool.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Register in bootstrap**

In `odigos/bootstrap.py`, find the tool registration section (near the other media/CLI tools). Add:

```python
from odigos.tools.marp_tool import MarpTool
registry.register(MarpTool())
```

- [ ] **Step 6: Commit**

```bash
git add odigos/tools/marp_tool.py tests/test_marp_tool.py odigos/bootstrap.py
git commit -m "feat: add MarpTool for rendering Markdown slides to PDF/PPTX/HTML"
```

---

### Task 3: Presenter Persona + Update Researcher

**Files:**
- Create: `data/subagents/presenter.md`
- Modify: `data/subagents/researcher.md` (minor — add note about structured output for downstream consumption)

- [ ] **Step 1: Create presenter persona**

Create `data/subagents/presenter.md`:

```markdown
---
name: presenter
description: Converts research or content into Marp slide presentations
model: default
tools: [marp, read_file, write_file]
max_runtime_seconds: 300
---

# Presentation Specialist

You create clear, visually structured Marp slide presentations from content provided to you.

## Rules

- Use `---` between slides (Marp separator)
- First slide: title + subtitle
- Maximum 15 slides unless instructed otherwise. For a "5-slide primer", use exactly 5 content slides + 1 title + 1 sources slide.
- Each slide should make ONE clear point
- Use bullet points (3-5 per slide max), not paragraphs
- Include a "Sources" slide at the end if the input has citations
- Use heading levels: `#` for slide titles, `##` for section headers within a slide
- Don't use images (not supported in our Marp setup)
- Keep text concise — slides are visual, not documents

## Marp Features You Can Use

- `<!-- _class: lead -->` for title/section divider slides
- `<!-- _class: invert -->` for dark background emphasis slides
- `**bold**` and `*italic*` for emphasis
- Tables for comparison data
- Code blocks with syntax highlighting

## Output Format

Return ONLY the raw Marp markdown. No wrapping, no explanation, no commentary.
Start with the YAML frontmatter:

```
---
marp: true
theme: default
paginate: true
---
```

Then the slides separated by `---`.

After producing the markdown, call the `marp` tool to render it as PDF.
```

- [ ] **Step 2: Commit**

```bash
git add data/subagents/presenter.md
git commit -m "feat: add presenter persona for Marp slide generation"
```

---

### Task 4: End-to-End Smoke Test + Demo Instructions

**Files:**
- Test: manual verification

- [ ] **Step 1: Verify marp-cli is available locally**

```bash
npx @marp-team/marp-cli --version 2>&1 || echo "marp not available locally — install with: npm install -g @marp-team/marp-cli"
```

If not available, install:
```bash
npm install -g @marp-team/marp-cli
```

- [ ] **Step 2: Run all new tests**

```bash
cd /Users/jacob/Projects/odigos && python3 -m pytest tests/test_marp_tool.py tests/test_subagent.py tests/test_subagent_worker.py tests/test_subagent_tools.py -v
```

Expected: all pass.

- [ ] **Step 3: Import smoke test**

```bash
python3 -c "
from odigos.tools.marp_tool import MarpTool
from odigos.core.subagent import SubagentManager, load_persona
p = load_persona('presenter')
assert p is not None
assert 'marp' in p.tools
print(f'presenter persona: model={p.model}, tools={p.tools}')
t = MarpTool()
print(f'MarpTool: name={t.name}, category={t.category}')
print('all ok')
"
```

Expected: prints persona info + tool info + "all ok".

- [ ] **Step 4: Update Dockerfile (if not done in Task 1)**

If the Docker build doesn't include marp-cli yet, update the Dockerfile now. For local dev, `npx @marp-team/marp-cli` works without global install.

- [ ] **Step 5: Document the demo workflow**

The research-present flow works like this — the orchestrator does:

```python
await manager.dispatch(
    task="Research the current state of LLM memory architectures — key papers, approaches, and open questions",
    persona="researcher",
    on_complete={
        "persona": "presenter",
        "task": "Turn this research into a 5-slide Marp primer suitable for a technical audience. Use the marp tool to render the slides as PDF.",
        "input_from": "result",
    },
)
```

The user triggers this by asking: "Make me a 5-slide primer on LLM memory architectures" and the orchestrator recognizes this as a research+present workflow.

No special code needed — the orchestrator learns this from the capabilities rubric we already added to `data/agent/capabilities.md`. The chaining infrastructure from Task 7 of the sub-agent plan handles the researcher → presenter handoff.

- [ ] **Step 6: Commit any remaining changes**

```bash
git add -A && git commit -m "feat: end-to-end research-present workflow with Marp rendering"
```
