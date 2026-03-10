import asyncio
import os
import tempfile
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

try:
    from odigos.config import Settings
except ImportError:
    Settings = None


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def tmp_db_path() -> AsyncGenerator[str, None]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    os.unlink(path)


if Settings is not None:

    @pytest.fixture
    def test_settings(tmp_db_path: str) -> Settings:
        return Settings(
            telegram_bot_token="test-token",
            llm_api_key="test-key",
            searxng_url="https://search.example.com",
            searxng_username="testuser",
            searxng_password="testpass",
            agent={"name": "TestAgent"},
            database={"path": tmp_db_path},
            llm={
                "default_model": "test/model",
                "fallback_model": "test/fallback",
                "max_tokens": 100,
                "temperature": 0.5,
            },
            telegram={"mode": "polling", "webhook_url": ""},
            server={"host": "127.0.0.1", "port": 8000},
        )
