from fastapi import APIRouter

from odigos.api.notebooks import router as notebooks_router
from odigos.api.kanban import router as kanban_router
from odigos.api.artifacts import router as artifacts_router
from odigos.api.documents import router as documents_router
from odigos.api.sharing import router as sharing_router
from odigos.api.sharing import public_router as sharing_public_router

router = APIRouter()
router.include_router(notebooks_router)
router.include_router(kanban_router)
router.include_router(artifacts_router)
router.include_router(documents_router)
router.include_router(sharing_router)
router.include_router(sharing_public_router)
