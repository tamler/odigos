import os

from fastapi import APIRouter

from odigos.api.settings import router as settings_router
from odigos.api.auth import router as auth_router
from odigos.api.setup import router as setup_router
from odigos.api.diagnostic import router as diagnostic_router
from odigos.api.metrics import router as metrics_router
from odigos.api.cron import router as cron_router
from odigos.api.budget import router as budget_router
from odigos.api.push import router as push_router

try:
    from odigos.api.webauthn import router as webauthn_router
    _HAS_WEBAUTHN = True
except ImportError:
    _HAS_WEBAUTHN = False

router = APIRouter()
router.include_router(settings_router)
router.include_router(auth_router)
router.include_router(setup_router)
router.include_router(diagnostic_router)
router.include_router(metrics_router)
router.include_router(cron_router)
router.include_router(budget_router)
router.include_router(push_router)
if _HAS_WEBAUTHN:
    router.include_router(webauthn_router)
if os.environ.get("ODIGOS_PLATFORM_URL"):
    from odigos.api.platform_auth import router as platform_auth_router
    router.include_router(platform_auth_router)
