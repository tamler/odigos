"""Setup status endpoint — no auth required (used before config exists)."""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api")


@router.get("/setup-status")
async def setup_status(request: Request):
    """Return whether the system has been configured with an LLM key."""
    settings = request.app.state.settings
    configured = bool(settings.llm_api_key and settings.llm_api_key != "your-api-key")
    return {"configured": configured}
