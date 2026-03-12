"""Tests for memory API endpoints (entity graph + semantic search)."""

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from odigos.api.memory import router
from odigos.db import Database


def _make_app(db: Database, vector_memory=None) -> FastAPI:
    """Create a minimal FastAPI app with the memory router and fake state."""
    app = FastAPI()
    app.include_router(router)
    app.state.db = db
    app.state.vector_memory = vector_memory
    app.state.settings = SimpleNamespace(api_key="test-key")
    return app


@pytest_asyncio.fixture
async def db(tmp_db_path: str) -> Database:
    d = Database(tmp_db_path, migrations_dir="migrations")
    await d.initialize()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def client(db: Database) -> AsyncClient:
    app = _make_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_entities_empty(client: AsyncClient):
    resp = await client.get("/api/memory/entities")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"entities": [], "edges": []}


@pytest.mark.asyncio
async def test_entities_with_data(client: AsyncClient, db: Database):
    await db.execute(
        "INSERT INTO entities (id, type, name, status) VALUES (?, ?, ?, ?)",
        ("e1", "person", "Alice", "active"),
    )
    await db.execute(
        "INSERT INTO entities (id, type, name, status) VALUES (?, ?, ?, ?)",
        ("e2", "location", "Paris", "active"),
    )
    await db.execute(
        "INSERT INTO edges (source_id, relationship, target_id, strength) "
        "VALUES (?, ?, ?, ?)",
        ("e1", "lives_in", "e2", 0.9),
    )

    resp = await client.get("/api/memory/entities")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entities"]) == 2
    assert len(data["edges"]) == 1
    assert data["edges"][0]["source_id"] == "e1"
    assert data["edges"][0]["relationship"] == "lives_in"
    assert data["edges"][0]["target_id"] == "e2"


@pytest.mark.asyncio
async def test_search_requires_query_param(client: AsyncClient):
    resp = await client.get("/api/memory/search")
    assert resp.status_code == 422


@dataclass
class FakeMemoryResult:
    content_preview: str
    source_type: str
    source_id: str
    distance: float


@pytest.mark.asyncio
async def test_search_returns_results(db: Database):
    mock_vm = AsyncMock()
    mock_vm.search.return_value = [
        FakeMemoryResult(
            content_preview="Alice lives in Paris",
            source_type="conversation",
            source_id="conv-1",
            distance=0.15,
        ),
    ]

    app = _make_app(db, vector_memory=mock_vm)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        resp = await c.get("/api/memory/search", params={"q": "Alice", "limit": 5})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["content_preview"] == "Alice lives in Paris"
    assert data["results"][0]["source_type"] == "conversation"
    assert data["results"][0]["source_id"] == "conv-1"
    assert data["results"][0]["distance"] == pytest.approx(0.15)
    mock_vm.search.assert_awaited_once_with("Alice", limit=15)


@pytest.mark.asyncio
async def test_search_empty_results(db: Database):
    mock_vm = AsyncMock()
    mock_vm.search.return_value = []

    app = _make_app(db, vector_memory=mock_vm)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-key"},
    ) as c:
        resp = await c.get("/api/memory/search", params={"q": "nonexistent"})

    assert resp.status_code == 200
    data = resp.json()
    assert data == {"results": []}
