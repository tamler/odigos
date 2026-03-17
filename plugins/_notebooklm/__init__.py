"""NotebookLM plugin -- generate podcasts, quizzes, mind maps from documents."""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings:
        return {"status": "available", "error_message": "No settings available"}

    # Check for NotebookLM credentials
    notebooklm_cookie = getattr(settings, "notebooklm_cookie", "")
    if not notebooklm_cookie:
        return {"status": "available", "error_message": "No notebooklm_cookie configured"}

    try:
        from plugins.notebooklm.tools import (
            NotebookLMMindMapTool,
            NotebookLMPodcastTool,
            NotebookLMQuizTool,
        )

        ctx.register_tool(NotebookLMPodcastTool(cookie=notebooklm_cookie))
        ctx.register_tool(NotebookLMQuizTool(cookie=notebooklm_cookie))
        ctx.register_tool(NotebookLMMindMapTool(cookie=notebooklm_cookie))

        logger.info("NotebookLM plugin loaded with 3 tools")
        return {"status": "active"}
    except ImportError:
        return {
            "status": "error",
            "error_message": "notebooklm-py not installed. Run: pip install notebooklm-py",
        }
    except Exception as e:
        return {"status": "error", "error_message": str(e)}
