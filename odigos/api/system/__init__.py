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

# Deliberately unguarded. The old try/except set _HAS_WEBAUTHN = True whenever
# webauthn.py imported at all -- and it always does, because it defines `router`
# at module scope before its own guarded imports and swallows their ImportError
# internally. So the flag read as a capability check while asserting nothing,
# and stayed True with passkey auth entirely broken.
#
# The contract is now fail-fast: webauthn.py has unguarded imports of its own
# (fastapi, odigos.api.deps, odigos.core.capabilities), and if one of those
# breaks, an auth router silently missing from the app is worse than not
# booting. Whether the five py_webauthn names loaded is a separate question,
# answered by webauthn._WEBAUTHN_AVAILABLE and reported via /api/state.
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
