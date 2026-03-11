"""Plugins list API endpoint."""

from fastapi import APIRouter, Depends

from odigos.api.deps import get_plugin_manager, require_api_key

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


@router.get("/plugins")
async def list_plugins(
    plugin_manager=Depends(get_plugin_manager),
):
    """Return list of loaded plugins with their capabilities."""
    plugins = [
        {
            "name": p["name"],
            "status": "loaded",
            "capabilities": p.get("capabilities", []),
        }
        for p in plugin_manager.loaded_plugins
    ]
    return {"plugins": plugins}
