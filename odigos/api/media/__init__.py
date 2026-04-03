from fastapi import APIRouter

from odigos.api.upload import router as upload_router
from odigos.api.audio import router as audio_router
from odigos.api.feed import router as feed_router
from odigos.api.cards import router as cards_router
from odigos.api.mesh import router as mesh_router

router = APIRouter()
router.include_router(upload_router)
router.include_router(audio_router)
router.include_router(feed_router)
router.include_router(cards_router)
router.include_router(mesh_router)
