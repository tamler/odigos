"""NotebookLM tools -- podcast, quiz, and mind map generation."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

FILES_DIR = Path("data/files")


def _parse_cookie_string(cookie_str: str) -> dict[str, str]:
    """Parse a cookie header string into a dict of name=value pairs."""
    cookies: dict[str, str] = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            cookies[name.strip()] = value.strip()
    return cookies


async def _create_client(cookie_str: str):
    """Create a NotebookLMClient from a cookie string.

    Tries from_storage() first (uses ~/.notebooklm/storage_state.json),
    then falls back to manual AuthTokens construction from the cookie string.
    """
    from notebooklm import NotebookLMClient

    try:
        client = await NotebookLMClient.from_storage()
        return client
    except Exception:
        pass

    # Fall back to manual construction
    from notebooklm.auth import AuthTokens

    cookies = _parse_cookie_string(cookie_str)
    csrf_token = cookies.get("CSRF_TOKEN", "")
    session_id = cookies.get("SESSION_ID", "")
    auth = AuthTokens(cookies=cookies, csrf_token=csrf_token, session_id=session_id)
    return NotebookLMClient(auth)


class NotebookLMPodcastTool(BaseTool):
    """Generate podcast-style audio from document content via NotebookLM."""

    name = "generate_podcast"
    description = (
        "Generate a podcast-style audio discussion about a topic or document. "
        "Uses Google NotebookLM to create a conversational audio overview with two hosts. "
        "Provide text content or a URL to discuss."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Text content or URL to generate a podcast about",
            },
            "title": {
                "type": "string",
                "description": "Title for the podcast episode",
            },
        },
        "required": ["content"],
    }

    def __init__(self, cookie: str) -> None:
        self._cookie = cookie

    async def execute(self, params: dict) -> ToolResult:
        content = params.get("content", "").strip()
        if not content:
            return ToolResult(success=False, data="", error="Missing required parameter: content")

        title = params.get("title", "").strip() or f"podcast_{int(time.time())}"

        try:
            from notebooklm import NotebookLMClient  # noqa: F401
        except ImportError:
            return ToolResult(
                success=False,
                data="",
                error="notebooklm-py not installed. Run: pip install notebooklm-py",
            )

        try:
            async with await _create_client(self._cookie) as client:
                nb = await client.notebooks.create(title)

                if content.startswith(("http://", "https://")):
                    await client.sources.add_url(nb.id, content, wait=True)
                else:
                    await client.sources.add_text(nb.id, content)

                status = await client.artifacts.generate_audio(
                    nb.id, instructions="Make it engaging and informative"
                )
                await client.artifacts.wait_for_completion(nb.id, status.task_id)

                FILES_DIR.mkdir(parents=True, exist_ok=True)
                safe_title = "".join(
                    c if c.isalnum() or c in "-_" else "_" for c in title
                )[:80]
                filename = f"{safe_title}_{int(time.time())}.mp3"
                output_path = FILES_DIR / filename

                await client.artifacts.download_audio(nb.id, str(output_path))

                return ToolResult(
                    success=True,
                    data=f"Podcast generated: {output_path}",
                )
        except Exception as e:
            logger.exception("NotebookLM podcast generation failed")
            return ToolResult(success=False, data="", error=f"Podcast generation failed: {e}")


class NotebookLMQuizTool(BaseTool):
    """Generate quiz questions from document content via NotebookLM."""

    name = "generate_quiz"
    description = (
        "Generate quiz questions from document content using Google NotebookLM. "
        "Provide text content or a URL to create questions about."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Text content or URL to generate quiz questions from",
            },
            "title": {
                "type": "string",
                "description": "Title for the quiz",
            },
        },
        "required": ["content"],
    }

    def __init__(self, cookie: str) -> None:
        self._cookie = cookie

    async def execute(self, params: dict) -> ToolResult:
        content = params.get("content", "").strip()
        if not content:
            return ToolResult(success=False, data="", error="Missing required parameter: content")

        title = params.get("title", "").strip() or f"quiz_{int(time.time())}"

        try:
            from notebooklm import NotebookLMClient  # noqa: F401
        except ImportError:
            return ToolResult(
                success=False,
                data="",
                error="notebooklm-py not installed. Run: pip install notebooklm-py",
            )

        try:
            async with await _create_client(self._cookie) as client:
                nb = await client.notebooks.create(title)

                if content.startswith(("http://", "https://")):
                    await client.sources.add_url(nb.id, content, wait=True)
                else:
                    await client.sources.add_text(nb.id, content)

                status = await client.artifacts.generate_quiz(nb.id)
                await client.artifacts.wait_for_completion(nb.id, status.task_id)

                FILES_DIR.mkdir(parents=True, exist_ok=True)
                safe_title = "".join(
                    c if c.isalnum() or c in "-_" else "_" for c in title
                )[:80]
                filename = f"{safe_title}_{int(time.time())}.json"
                output_path = FILES_DIR / filename

                await client.artifacts.download_quiz(
                    nb.id, str(output_path), output_format="json"
                )

                quiz_data = output_path.read_text()
                try:
                    parsed = json.loads(quiz_data)
                    lines = [f"## Quiz: {title}\n"]
                    for i, q in enumerate(parsed if isinstance(parsed, list) else [], 1):
                        question = q.get("question", q.get("text", ""))
                        lines.append(f"**Q{i}.** {question}")
                        options = q.get("options", q.get("choices", []))
                        for opt in options:
                            if isinstance(opt, dict):
                                opt = opt.get("text", str(opt))
                            lines.append(f"  - {opt}")
                        lines.append("")
                    formatted = "\n".join(lines)
                except (json.JSONDecodeError, KeyError):
                    formatted = quiz_data

                return ToolResult(
                    success=True,
                    data=f"{formatted}\n\nQuiz saved to: {output_path}",
                )
        except Exception as e:
            logger.exception("NotebookLM quiz generation failed")
            return ToolResult(success=False, data="", error=f"Quiz generation failed: {e}")


class NotebookLMMindMapTool(BaseTool):
    """Generate a mind map from document content via NotebookLM."""

    name = "generate_mindmap"
    description = (
        "Generate a mind map from document content using Google NotebookLM. "
        "Provide text content or a URL to create a structured mind map."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Text content or URL to generate a mind map from",
            },
            "title": {
                "type": "string",
                "description": "Title for the mind map",
            },
        },
        "required": ["content"],
    }

    def __init__(self, cookie: str) -> None:
        self._cookie = cookie

    async def execute(self, params: dict) -> ToolResult:
        content = params.get("content", "").strip()
        if not content:
            return ToolResult(success=False, data="", error="Missing required parameter: content")

        title = params.get("title", "").strip() or f"mindmap_{int(time.time())}"

        try:
            from notebooklm import NotebookLMClient  # noqa: F401
        except ImportError:
            return ToolResult(
                success=False,
                data="",
                error="notebooklm-py not installed. Run: pip install notebooklm-py",
            )

        try:
            async with await _create_client(self._cookie) as client:
                nb = await client.notebooks.create(title)

                if content.startswith(("http://", "https://")):
                    await client.sources.add_url(nb.id, content, wait=True)
                else:
                    await client.sources.add_text(nb.id, content)

                await client.artifacts.generate_mind_map(nb.id)

                FILES_DIR.mkdir(parents=True, exist_ok=True)
                safe_title = "".join(
                    c if c.isalnum() or c in "-_" else "_" for c in title
                )[:80]
                filename = f"{safe_title}_{int(time.time())}.json"
                output_path = FILES_DIR / filename

                await client.artifacts.download_mind_map(nb.id, str(output_path))

                mindmap_data = output_path.read_text()
                try:
                    parsed = json.loads(mindmap_data)
                    formatted = json.dumps(parsed, indent=2)
                except json.JSONDecodeError:
                    formatted = mindmap_data

                return ToolResult(
                    success=True,
                    data=f"## Mind Map: {title}\n\n```json\n{formatted}\n```\n\nMind map saved to: {output_path}",
                )
        except Exception as e:
            logger.exception("NotebookLM mind map generation failed")
            return ToolResult(success=False, data="", error=f"Mind map generation failed: {e}")
