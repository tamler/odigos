"""Setup status endpoint — no auth required (used before config exists)."""

from fastapi import APIRouter, Depends

from odigos.api.deps import get_settings

router = APIRouter(prefix="/api")


@router.get("/setup-status")
async def setup_status(settings=Depends(get_settings)):
    """Return whether the system has been configured with an LLM key."""
    configured = bool(settings.llm_api_key and settings.llm_api_key != "your-api-key")
    return {"configured": configured}
