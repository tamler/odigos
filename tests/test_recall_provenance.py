"""Test that memory recall separates document and conversation results."""
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


def _make_mock_vector(doc_results=None, conv_results=None):
    """Create a mock vector memory that returns different results by source_type."""
    doc_results = doc_results or []
    conv_results = conv_results or []

    async def fake_search(query, limit=5, source_type=None, memory_type=None):
        if source_type == "document_chunk":
            return doc_results
        if source_type == "user_message":
            return conv_results
        return doc_results + conv_results

    async def fake_fts(query, limit=20, source_type=None):
        return []

    mock = AsyncMock()
    mock.search = AsyncMock(side_effect=fake_search)
    mock.search_fts = AsyncMock(side_effect=fake_fts)
    return mock


def test_recall_separates_documents_and_conversations(event_loop):
    """Document chunks and user messages appear in separate sections."""
    mock_vector = _make_mock_vector(
        doc_results=[
            MemoryResult(
                content_preview="Revenue grew 15% year-over-year",
                source_type="document_chunk",
                source_id="doc-123",
                distance=0.1,
                when_to_use="when referencing content from 'quarterly-report.pdf': Revenue grew 15%",
            )
        ],
        conv_results=[
            MemoryResult(
                content_preview="User asked about revenue trends",
                source_type="user_message",
                source_id="conv-1",
                distance=0.2,
            )
        ],
    )
    mock_graph = AsyncMock()
    mock_graph.find_entity = AsyncMock(return_value=[])

    manager = MemoryManager(
        vector_memory=mock_vector,
        graph=mock_graph,
        resolver=AsyncMock(),
        summarizer=AsyncMock(),
    )

    result = event_loop.run_until_complete(manager.recall("revenue growth"))
    assert "## Document knowledge" in result
    assert "[quarterly-report.pdf]" in result
    assert "## Conversation history" in result
    assert "User asked about revenue trends" in result


def test_recall_document_source_tag(event_loop):
    """Document chunks include source filename."""
    mock_vector = _make_mock_vector(
        doc_results=[
            MemoryResult(
                content_preview="p99 down from 800ms to 120ms",
                source_type="document_chunk",
                source_id="doc-456",
                distance=0.1,
                when_to_use="when referencing content from 'meeting-notes.txt': p99 down",
            )
        ],
    )
    mock_graph = AsyncMock()
    mock_graph.find_entity = AsyncMock(return_value=[])

    manager = MemoryManager(
        vector_memory=mock_vector,
        graph=mock_graph,
        resolver=AsyncMock(),
        summarizer=AsyncMock(),
    )

    result = event_loop.run_until_complete(manager.recall("API latency"))
    assert "[meeting-notes.txt]" in result
    assert "p99 down from 800ms" in result


def test_recall_no_documents_shows_only_conversations(event_loop):
    """When no documents match, only conversation section appears."""
    mock_vector = _make_mock_vector(
        conv_results=[
            MemoryResult(
                content_preview="User prefers dark mode",
                source_type="user_message",
                source_id="conv-1",
                distance=0.2,
            )
        ],
    )
    mock_graph = AsyncMock()
    mock_graph.find_entity = AsyncMock(return_value=[])

    manager = MemoryManager(
        vector_memory=mock_vector,
        graph=mock_graph,
        resolver=AsyncMock(),
        summarizer=AsyncMock(),
    )

    result = event_loop.run_until_complete(manager.recall("dark mode"))
    assert "## Document knowledge" not in result
    assert "## Conversation history" in result
    assert "[doc:" not in result  # no document citations in conversation-only recall
    assert "User prefers dark mode" in result
