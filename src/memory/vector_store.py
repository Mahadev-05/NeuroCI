"""
NeuroCI — ChromaDB Vector Store.

Manages the failure→fix embedding memory:
- Stores past fixes with failure logs and diffs
- Retrieves similar past fixes via cosine similarity
- Grows with every merged fix (the learning loop)
"""

from __future__ import annotations

import hashlib
from typing import Any

import chromadb
import structlog
from chromadb.config import Settings as ChromaSettings

from src.agent.llm_factory import get_embeddings

from src.config import get_settings
from src.models import SimilarFix

logger = structlog.get_logger()


class VectorStore:
    """ChromaDB-backed vector store for failure→fix pairs."""

    def __init__(self) -> None:
        settings = get_settings()
        self._embeddings = get_embeddings()

        try:
            self._client = chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=settings.chroma_collection,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("vector_store.connected", collection=settings.chroma_collection)
        except Exception as e:
            logger.warning("vector_store.connection_failed", error=str(e))
            self._client = None
            self._collection = None

    def _embed(self, text: str) -> list[float]:
        """Generate embedding using the configured provider."""
        return self._embeddings.embed_query(text[:8000])

    def _make_id(self, text: str) -> str:
        """Generate a deterministic ID for deduplication."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    async def find_similar(self, failure_log: str, top_k: int = 3) -> list[SimilarFix]:
        """
        Find the top-K most similar past failure→fix pairs.
        Returns SimilarFix objects with similarity scores.
        """
        if not self._collection:
            logger.warning("vector_store.not_available")
            return []

        try:
            embedding = self._embed(failure_log)

            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )

            fixes: list[SimilarFix] = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i] if results["metadatas"] else {}
                    distance = results["distances"][0][i] if results["distances"] else 1.0
                    similarity = 1.0 - distance  # Cosine distance → similarity

                    fixes.append(SimilarFix(
                        failure_log=doc,
                        fix_diff=meta.get("fix_diff", ""),
                        category=meta.get("category", "Unknown"),
                        outcome=meta.get("outcome", "unknown"),
                        similarity_score=max(0.0, similarity),
                    ))

            logger.info("vector_store.query", results=len(fixes), top_k=top_k)
            return fixes

        except Exception as e:
            logger.error("vector_store.query_error", error=str(e))
            return []

    async def store_fix(
        self,
        failure_log: str,
        fix_diff: str,
        category: str,
        outcome: str,
        repo: str = "",
        run_id: int = 0,
    ) -> None:
        """
        Store a failure→fix pair in the vector store.
        Called after a fix PR is merged (success) or rejected.
        """
        if not self._collection:
            logger.warning("vector_store.not_available_for_store")
            return

        try:
            doc_id = self._make_id(failure_log + fix_diff)
            embedding = self._embed(failure_log)

            self._collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[failure_log[:4000]],
                metadatas=[{
                    "fix_diff": fix_diff[:4000],
                    "category": category,
                    "outcome": outcome,
                    "repo": repo,
                    "run_id": str(run_id),
                }],
            )

            logger.info(
                "vector_store.stored",
                outcome=outcome, category=category, run_id=run_id,
            )

        except Exception as e:
            logger.error("vector_store.store_error", error=str(e))

    async def export_dataset(self) -> list[dict[str, Any]]:
        """
        Export the full fix dataset as a list of dicts.
        Useful for fine-tuning a smaller LLM (Llama 3 via LoRA).
        """
        if not self._collection:
            return []

        try:
            data = self._collection.get(include=["documents", "metadatas"])
            dataset = []
            for i, doc in enumerate(data["documents"] or []):
                meta = data["metadatas"][i] if data["metadatas"] else {}
                dataset.append({
                    "failure_log": doc,
                    "fix_diff": meta.get("fix_diff", ""),
                    "category": meta.get("category", ""),
                    "outcome": meta.get("outcome", ""),
                })
            return dataset
        except Exception as e:
            logger.error("vector_store.export_error", error=str(e))
            return []
