from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odigos.memory.ingester import DocumentIngester


class TestDocumentIngester:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.fetch_one = AsyncMock(return_value=None)
        return db

    @pytest.fixture
    def mock_vector_memory(self):
        vm = AsyncMock()
        vm.store = AsyncMock(return_value=str(uuid.uuid4()))
        return vm

    @pytest.fixture
    def ingester(self, mock_db, mock_vector_memory):
        return DocumentIngester(db=mock_db, vector_memory=mock_vector_memory)

    async def test_ingest_stores_chunks(self, ingester, mock_vector_memory):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        doc_id = await ingester.ingest(text=text, filename="test.txt")

        assert doc_id is not None
        assert mock_vector_memory.store.call_count > 0
        for call in mock_vector_memory.store.call_args_list:
            assert (call.kwargs.get("source_type") or call.args[1]) == "document_chunk"

    async def test_ingest_creates_document_record(self, ingester, mock_db):
        await ingester.ingest(text="Some content.", filename="doc.pdf")

        insert_calls = [
            c for c in mock_db.execute.call_args_list
            if "INSERT INTO documents" in str(c)
        ]
        assert len(insert_calls) == 1
        # Should also update chunk_count
        update_calls = [
            c for c in mock_db.execute.call_args_list
            if "UPDATE documents" in str(c)
        ]
        assert len(update_calls) == 1

    async def test_ingest_with_source_url(self, ingester, mock_db):
        await ingester.ingest(
            text="Content.", filename="remote.pdf",
            source_url="https://example.com/remote.pdf",
        )

        insert_call = [
            c for c in mock_db.execute.call_args_list
            if "INSERT INTO documents" in str(c)
        ][0]
        assert "https://example.com/remote.pdf" in str(insert_call)

    async def test_ingest_returns_document_id(self, ingester):
        doc_id = await ingester.ingest(text="Content.", filename="test.txt")
        assert isinstance(doc_id, str)
        uuid.UUID(doc_id)

    async def test_ingest_chunk_count(self, ingester, mock_db):
        text = "Para one.\n\nPara two.\n\nPara three."
        await ingester.ingest(text=text, filename="test.txt")

        # chunk_count is set via UPDATE after vectors are stored
        update_call = [
            c for c in mock_db.execute.call_args_list
            if "UPDATE documents" in str(c)
        ][0]
        params = update_call.args[1] if len(update_call.args) > 1 else update_call[0][1]
        assert params[0] == 3  # 3 paragraphs

    async def test_ingest_empty_text(self, ingester, mock_db):
        doc_id = await ingester.ingest(text="", filename="empty.txt")
        assert doc_id is not None

    async def test_delete_document(self, ingester, mock_db):
        mock_db.fetch_one = AsyncMock(return_value={"chunk_count": 2})

        await ingester.delete("doc-123")

        delete_calls = [
            c for c in mock_db.execute.call_args_list
            if "DELETE" in str(c)
        ]
        # Should have 2 DELETEs: one for vectors, one for document record
        assert len(delete_calls) == 2

    async def test_ingest_with_docling_document(self, ingester, mock_vector_memory):
        mock_doc = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.text = "Chunk from docling"

        with patch("odigos.memory.ingester.HybridChunker") as MockChunker:
            MockChunker.return_value.chunk.return_value = [mock_chunk]
            doc_id = await ingester.ingest(
                text="fallback",
                filename="test.pdf",
                dl_doc=mock_doc,
            )

        assert doc_id is not None
        MockChunker.return_value.chunk.assert_called_once_with(mock_doc)
        mock_vector_memory.store.assert_called_once()
        assert "Chunk from docling" in str(mock_vector_memory.store.call_args)
