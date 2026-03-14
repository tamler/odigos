"""Test that memory recall includes source document metadata."""
import asyncio
import pytest
from unittest.mock import AsyncMock
from odigos.memory.manager import MemoryManager
from odigos.memory.vectors import MemoryResult


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_recall_includes_document_source(event_loop):
    """When a recalled memory is a document_chunk, include filename in output."""
    mock_vector = AsyncMock()
    mock_vector.search = AsyncMock(return_value=[
        MemoryResult(
            content_preview="Revenue grew 15% year-over-year",
            source_type="document_chunk",
            source_id="doc-123",
            distance=0.1,
            when_to_use="when referencing content from 'quarterly-report.pdf': Revenue grew 15%",
        )
    ])
    mock_vector.search_fts = AsyncMock(return_value=[])
    mock_graph = AsyncMock()
    mock_graph.find_entity = AsyncMock(return_value=[])

    manager = MemoryManager(
        vector_memory=mock_vector,
        graph=mock_graph,
        resolver=AsyncMock(),
        summarizer=AsyncMock(),
    )

    result = event_loop.run_until_complete(manager.recall("revenue growth"))
    assert "[Source: quarterly-report.pdf]" in result
    assert "Revenue grew 15%" in result


def test_recall_non_document_has_no_source_tag(event_loop):
    """Regular memories should not have source tags."""
    mock_vector = AsyncMock()
    mock_vector.search = AsyncMock(return_value=[
        MemoryResult(
            content_preview="User prefers dark mode",
            source_type="user_message",
            source_id="conv-1",
            distance=0.2,
        )
    ])
    mock_vector.search_fts = AsyncMock(return_value=[])
    mock_graph = AsyncMock()
    mock_graph.find_entity = AsyncMock(return_value=[])

    manager = MemoryManager(
        vector_memory=mock_vector,
        graph=mock_graph,
        resolver=AsyncMock(),
        summarizer=AsyncMock(),
    )

    result = event_loop.run_until_complete(manager.recall("dark mode"))
    assert "[Source:" not in result
    assert "User prefers dark mode" in result
