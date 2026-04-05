from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from odigos.api.rate_limit import RateLimitMiddleware
from odigos.bootstrap import Bootstrapper
from odigos.config import load_settings
from odigos.config_validator import validate_settings

from odigos.api.callbacks import router as callbacks_router
from odigos.api.workspace import router as workspace_router
from odigos.api.agent import router as agent_router
from odigos.api.system import router as system_router
from odigos.api.content import router as content_router
from odigos.api.media import router as media_router

from odigos.dashboard import mount_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for FastAPI."""
    config_path = os.environ.get("ODIGOS_CONFIG", "config.yaml")
    settings = load_settings(config_path)

    # Validate configuration and log warnings
    config_warnings = validate_settings(settings)
    for w in config_warnings:
        logger.warning("Config: %s", w)
    if config_warnings:
        logger.warning(
            "%d config warning(s) found. The agent will "
            "still start, but some features may not work.",
            len(config_warnings),
        )

    bootstrapper = Bootstrapper(settings, config_path)
    container = await bootstrapper.bootstrap()
    app.state.container = container

    yield

    logger.info("Shutting down Odigos...")
    await container.shutdown()
    logger.info("Odigos stopped.")


app = FastAPI(title="Odigos", lifespan=lifespan)

# Rate limiting: 10 req/s per IP with burst of 30
app.add_middleware(RateLimitMiddleware, rate=10.0, burst=30)

# CORS: only allow same-origin requests (dashboard is served from same host)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # No cross-origin allowed; dashboard is same-origin
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)

app.include_router(callbacks_router)  # No auth — external APIs POST here
app.include_router(system_router)
app.include_router(agent_router)
app.include_router(workspace_router)
app.include_router(content_router)
app.include_router(media_router)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "odigos"}

mount_dashboard(app)


def main():
    import uvicorn

    config_path = os.environ.get("ODIGOS_CONFIG", "config.yaml")
    settings = load_settings(config_path)

    uvicorn.run(
        "odigos.main:app",
        host=settings.server.host,
        port=settings.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
