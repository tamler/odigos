import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from odigos.channels.telegram import TelegramChannel
from odigos.config import load_settings
from odigos.core.agent import Agent
from odigos.db import Database
from odigos.providers.openrouter import OpenRouterProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Module-level references for cleanup
_db: Database | None = None
_provider: OpenRouterProvider | None = None
_telegram: TelegramChannel | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for FastAPI."""
    global _db, _provider, _telegram

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    settings = load_settings(config_path)

    logger.info("Starting Odigos agent: %s", settings.agent.name)

    # Initialize database
    _db = Database(settings.database.path)
    await _db.initialize()
    logger.info("Database initialized at %s", settings.database.path)

    # Initialize LLM provider
    _provider = OpenRouterProvider(
        api_key=settings.openrouter_api_key,
        default_model=settings.openrouter.default_model,
        fallback_model=settings.openrouter.fallback_model,
        max_tokens=settings.openrouter.max_tokens,
        temperature=settings.openrouter.temperature,
    )

    # Initialize agent
    agent = Agent(
        db=_db,
        provider=_provider,
        agent_name=settings.agent.name,
    )

    # Initialize Telegram channel
    _telegram = TelegramChannel(
        token=settings.telegram_bot_token,
        agent=agent,
        mode=settings.telegram.mode,
        webhook_url=settings.telegram.webhook_url,
    )
    await _telegram.start()
    logger.info("Telegram channel started in %s mode", settings.telegram.mode)

    logger.info("Odigos is ready.")

    yield

    # Shutdown
    logger.info("Shutting down Odigos...")
    if _telegram:
        await _telegram.stop()
    if _provider:
        await _provider.close()
    if _db:
        await _db.close()
    logger.info("Odigos stopped.")


app = FastAPI(title="Odigos", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "odigos"}


def main():
    import uvicorn

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    settings = load_settings(config_path)

    uvicorn.run(
        "odigos.main:app",
        host=settings.server.host,
        port=settings.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
