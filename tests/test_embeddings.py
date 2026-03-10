from unittest.mock import MagicMock, patch
from functools import partial

import numpy as np
import pytest

from odigos.providers.embeddings import EmbeddingProvider


class TestEmbeddingProvider:
    @pytest.fixture
    def provider(self):
        with patch("odigos.providers.embeddings.SentenceTransformer") as MockST:
            mock_model = MagicMock()
            MockST.return_value = mock_model
            p = EmbeddingProvider(model_name="test-model", dimensions=768)
            p._model = mock_model
            return p

    async def test_embed_single_text(self, provider):
        """Embeds a single text string and returns a vector."""
        provider._model.encode.return_value = np.array([[0.1] * 768])

        result = await provider.embed("Hello world")

        assert len(result) == 768
        assert result[0] == pytest.approx(0.1)
        provider._model.encode.assert_called_once()
        call_args = provider._model.encode.call_args[0][0]
        assert "search_document: Hello world" in call_args

    async def test_embed_batch(self, provider):
        """Embeds a list of texts and returns a list of vectors."""
        provider._model.encode.return_value = np.array([
            [0.1] * 768,
            [0.2] * 768,
        ])

        results = await provider.embed_batch(["Hello", "World"])

        assert len(results) == 2
        assert len(results[0]) == 768
        assert len(results[1]) == 768

    async def test_embed_query_uses_search_prefix(self, provider):
        """embed_query uses search_query prefix instead of search_document."""
        provider._model.encode.return_value = np.array([[0.3] * 768])

        result = await provider.embed_query("find something")

        assert len(result) == 768
        call_args = provider._model.encode.call_args[0][0]
        assert "search_query: find something" in call_args
