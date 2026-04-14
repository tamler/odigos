"""Setup status endpoint — no auth required (used before config exists)."""

from fastapi import APIRouter, Depends

from odigos.api.deps import get_settings

router = APIRouter(prefix="/api")


@router.get("/setup-status")
async def setup_status(settings=Depends(get_settings)):
    """Return whether the system has been configured with at least one provider."""
    configured = bool(
        settings.providers
        and any(p.api_key for p in settings.providers.values())
        and settings.models
        and settings.llm.fast
    )
    return {"configured": configured}
