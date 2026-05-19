"""
NeuroCI — LLM Factory.

Centralised LLM provider management. Supports:
- Google Gemini (FREE tier — recommended)
- Groq (FREE tier — fast inference)
- Ollama (FREE — runs locally, no API key)
- OpenAI (paid — GPT-4o)

Switch providers by setting LLM_PROVIDER in .env
"""

from __future__ import annotations

from typing import Literal

import structlog
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from src.config import get_settings

logger = structlog.get_logger()

LLMProvider = Literal["gemini", "groq", "ollama", "openai"]


def get_chat_llm(
    temperature: float = 0.1,
    max_tokens: int = 2000,
    provider: LLMProvider | None = None,
) -> BaseChatModel:
    """
    Get a chat LLM instance based on the configured provider.

    Priority: explicit provider arg > LLM_PROVIDER env var > fallback to gemini
    """
    settings = get_settings()
    provider = provider or settings.llm_provider

    logger.debug("llm_factory.get_chat", provider=provider, temperature=temperature)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

    elif provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    elif provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_url,
            temperature=temperature,
            num_predict=max_tokens,
        )

    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def get_embeddings(provider: LLMProvider | None = None) -> Embeddings:
    """
    Get an embeddings model based on the configured provider.

    - Gemini  → models/text-embedding-004 (FREE)
    - Groq    → falls back to Ollama embeddings
    - Ollama  → nomic-embed-text (FREE, local)
    - OpenAI  → text-embedding-3-small (paid)
    """
    settings = get_settings()
    provider = provider or settings.llm_provider

    if provider == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model=settings.gemini_embedding_model,
            google_api_key=settings.gemini_api_key,
        )

    elif provider in ("groq", "ollama"):
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=settings.ollama_embedding_model,
            base_url=settings.ollama_url,
        )

    elif provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key,
        )

    else:
        raise ValueError(f"Unknown embedding provider: {provider}")
