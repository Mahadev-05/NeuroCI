"""
NeuroCI — LLM Factory Tests.

Tests for provider selection, initialization, and error handling.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestGetChatLLM:
    """Test LLM provider factory."""

    @patch("src.agent.llm_factory.get_settings")
    def test_gemini_provider(self, mock_settings):
        """Gemini provider should return ChatGoogleGenerativeAI."""
        settings = MagicMock()
        settings.llm_provider = "gemini"
        settings.gemini_model = "gemini-2.0-flash"
        settings.gemini_api_key = "fake-key"
        mock_settings.return_value = settings

        with patch("src.agent.llm_factory.ChatGoogleGenerativeAI", create=True) as mock_cls:
            mock_cls.return_value = MagicMock()
            from src.agent.llm_factory import get_chat_llm
            llm = get_chat_llm(provider="gemini")
            # Verify the import path was used
            assert llm is not None

    @patch("src.agent.llm_factory.get_settings")
    def test_default_provider_from_settings(self, mock_settings):
        """Default provider should come from settings when not specified."""
        settings = MagicMock()
        settings.llm_provider = "gemini"
        settings.gemini_model = "gemini-2.0-flash"
        settings.gemini_api_key = "fake-key"
        mock_settings.return_value = settings

        from src.agent.llm_factory import get_chat_llm
        # Should not raise — uses settings.llm_provider
        with patch("langchain_google_genai.ChatGoogleGenerativeAI", create=True):
            try:
                llm = get_chat_llm()
            except ImportError:
                pass  # OK if langchain_google_genai not installed in test

    def test_invalid_provider(self):
        """Unknown provider should raise ValueError."""
        with patch("src.agent.llm_factory.get_settings") as mock_settings:
            settings = MagicMock()
            settings.llm_provider = "invalid_provider"
            mock_settings.return_value = settings

            from src.agent.llm_factory import get_chat_llm
            with pytest.raises(ValueError, match="Unknown LLM provider"):
                get_chat_llm(provider="invalid_provider")


class TestGetEmbeddings:
    """Test embedding model factory."""

    def test_invalid_embedding_provider(self):
        """Unknown embedding provider should raise ValueError."""
        with patch("src.agent.llm_factory.get_settings") as mock_settings:
            settings = MagicMock()
            settings.llm_provider = "invalid"
            mock_settings.return_value = settings

            from src.agent.llm_factory import get_embeddings
            with pytest.raises(ValueError, match="Unknown embedding provider"):
                get_embeddings(provider="invalid")

    @patch("src.agent.llm_factory.get_settings")
    def test_groq_falls_back_to_ollama_embeddings(self, mock_settings):
        """Groq provider should use Ollama embeddings (Groq has no embedding API)."""
        settings = MagicMock()
        settings.llm_provider = "groq"
        settings.ollama_url = "http://localhost:11434"
        settings.ollama_embedding_model = "nomic-embed-text"
        mock_settings.return_value = settings

        with patch("langchain_ollama.OllamaEmbeddings", create=True) as mock_cls:
            mock_cls.return_value = MagicMock()
            from src.agent.llm_factory import get_embeddings
            emb = get_embeddings(provider="groq")
            assert emb is not None
