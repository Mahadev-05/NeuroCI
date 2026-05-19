"""
NeuroCI — Vector Store Tests.

Tests for ChromaDB vector store with mocked client.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestVectorStore:

    @patch("src.memory.vector_store.get_settings")
    @patch("src.memory.vector_store.get_embeddings")
    @patch("src.memory.vector_store.chromadb")
    def test_init_success(self, mock_chroma, mock_emb, mock_settings):
        """VectorStore should initialize with ChromaDB connection."""
        mock_settings.return_value = MagicMock(
            chroma_host="localhost", chroma_port=8000,
            chroma_collection="test",
        )
        mock_emb.return_value = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = MagicMock()
        mock_chroma.HttpClient.return_value = mock_client

        from src.memory.vector_store import VectorStore
        vs = VectorStore()
        assert vs._collection is not None

    @patch("src.memory.vector_store.get_settings")
    @patch("src.memory.vector_store.get_embeddings")
    @patch("src.memory.vector_store.chromadb")
    def test_init_connection_failure(self, mock_chroma, mock_emb, mock_settings):
        """Connection failure should set collection to None."""
        mock_settings.return_value = MagicMock(
            chroma_host="localhost", chroma_port=8000,
            chroma_collection="test",
        )
        mock_emb.return_value = MagicMock()
        mock_chroma.HttpClient.side_effect = Exception("Connection refused")

        from src.memory.vector_store import VectorStore
        vs = VectorStore()
        assert vs._collection is None

    @patch("src.memory.vector_store.get_settings")
    @patch("src.memory.vector_store.get_embeddings")
    @patch("src.memory.vector_store.chromadb")
    @pytest.mark.asyncio
    async def test_find_similar_no_collection(self, mock_chroma, mock_emb, mock_settings):
        """No collection should return empty list."""
        mock_settings.return_value = MagicMock(
            chroma_host="localhost", chroma_port=8000,
            chroma_collection="test",
        )
        mock_emb.return_value = MagicMock()
        mock_chroma.HttpClient.side_effect = Exception("fail")

        from src.memory.vector_store import VectorStore
        vs = VectorStore()
        result = await vs.find_similar("test log")
        assert result == []

    @patch("src.memory.vector_store.get_settings")
    @patch("src.memory.vector_store.get_embeddings")
    @patch("src.memory.vector_store.chromadb")
    @pytest.mark.asyncio
    async def test_find_similar_returns_results(self, mock_chroma, mock_emb, mock_settings):
        """Should return SimilarFix objects from ChromaDB results."""
        mock_settings.return_value = MagicMock(
            chroma_host="localhost", chroma_port=8000,
            chroma_collection="test",
        )
        emb_instance = MagicMock()
        emb_instance.embed_query.return_value = [0.1] * 768
        mock_emb.return_value = emb_instance

        collection = MagicMock()
        collection.query.return_value = {
            "documents": [["log1"]],
            "metadatas": [[{"fix_diff": "diff1", "category": "ImportError", "outcome": "success"}]],
            "distances": [[0.2]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = collection
        mock_chroma.HttpClient.return_value = mock_client

        from src.memory.vector_store import VectorStore
        vs = VectorStore()
        results = await vs.find_similar("test error")
        assert len(results) == 1
        assert results[0].category == "ImportError"
        assert results[0].similarity_score == pytest.approx(0.8, abs=0.01)

    @patch("src.memory.vector_store.get_settings")
    @patch("src.memory.vector_store.get_embeddings")
    @patch("src.memory.vector_store.chromadb")
    @pytest.mark.asyncio
    async def test_store_fix(self, mock_chroma, mock_emb, mock_settings):
        """store_fix should call collection.upsert."""
        mock_settings.return_value = MagicMock(
            chroma_host="localhost", chroma_port=8000,
            chroma_collection="test",
        )
        emb_instance = MagicMock()
        emb_instance.embed_query.return_value = [0.1] * 768
        mock_emb.return_value = emb_instance

        collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = collection
        mock_chroma.HttpClient.return_value = mock_client

        from src.memory.vector_store import VectorStore
        vs = VectorStore()
        await vs.store_fix("log", "diff", "ImportError", "success")
        collection.upsert.assert_called_once()
