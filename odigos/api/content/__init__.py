from fastapi import APIRouter

from odigos.api.skills import router as skills_router
from odigos.api.plugins import router as plugins_router
from odigos.api.evolution import router as evolution_router
from odigos.api.prompts import router as prompts_router
from odigos.api.analytics import router as analytics_router
from odigos.api.report import router as report_router

router = APIRouter()
router.include_router(skills_router)
router.include_router(plugins_router)
router.include_router(evolution_router)
router.include_router(prompts_router)
router.include_router(analytics_router)
router.include_router(report_router)
