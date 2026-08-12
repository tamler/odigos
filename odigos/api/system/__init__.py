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

# webauthn.py defines `router` at module scope before its own guarded imports,
# and swallows their ImportError internally, so this import can never fail --
# the old try/except set _HAS_WEBAUTHN = True unconditionally, including when
# passkey auth was entirely broken. A guard that asserts nothing is worse than
# no guard: it reads as a capability check. The real signal is
# webauthn._WEBAUTHN_AVAILABLE, reported via /api/state.
from odigos.api.webauthn import router as webauthn_router

router = APIRouter()
router.include_router(settings_router)
router.include_router(auth_router)
router.include_router(setup_router)
router.include_router(diagnostic_router)
router.include_router(metrics_router)
router.include_router(cron_router)
router.include_router(budget_router)
router.include_router(push_router)
router.include_router(webauthn_router)
if os.environ.get("ODIGOS_PLATFORM_URL"):
    from odigos.api.platform_auth import router as platform_auth_router
    router.include_router(platform_auth_router)
