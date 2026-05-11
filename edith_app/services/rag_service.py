"""
edith_app.services.rag_service
================================
EDITH integration wrapper for the RAG pipeline.

Provides a thread-safe, lazily-initialised bridge between EDITH's assistant
and the RAGPipeline. This is the ONLY file in services/ that knows about the
rag package — keeping the integration surface minimal.

Usage (internal — called from assistant.py)
--------------------------------------------
    self.rag = RagService(config)
    answer = self.rag.ask_docs("What is EDITH?")
    self.rag.store_user_fact("User prefers short answers", "preference")
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable
import functools

from edith_app.config import AppConfig
from edith_app.services.logging_service import get_logger


class RagService:
    """
    Thread-safe lazy wrapper around RAGPipeline for use inside EdithAssistant.

    Initialization is deferred to the first call so EDITH starts instantly
    even when the RAG dependencies (chromadb, sentence-transformers) need
    time to load or are not installed.

    Parameters
    ----------
    config : AppConfig instance (provides all RAG path/model settings)
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._pipeline = None
        self._lock = threading.Lock()
        self._init_attempted = False
        self._available = False
        self._logger = get_logger("edith.rag_service", config.runtime_log_path)
        # Auto-ingest docs in a background thread on startup
        self._auto_ingest_done = False

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """True if the RAG backend is ready (deps installed, ChromaDB reachable)."""
        return self._available

    def ask_docs(
        self,
        question: str,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """
        Query the knowledge base with *question* and return a grounded answer.

        Returns a plain string answer. If RAG is unavailable, returns a
        graceful fallback message that doesn't expose internal errors.
        """
        if not self._ensure_ready():
            return (
                "The knowledge base is not available yet. "
                "Please ensure chromadb and sentence-transformers are installed."
            )
        try:
            result = self._pipeline.query(question, on_token=on_token)
            if result.error == "no_chunks_retrieved":
                return "I couldn't find relevant information in my knowledge base for that question."
            return result.answer
        except Exception as exc:
            self._logger.warning("RagService.ask_docs failed: %s", exc)
            return "I encountered an issue searching the knowledge base. Please try again."

    def ask_docs_full(self, question: str, on_token: Callable[[str], None] | None = None):
        """
        Like ask_docs but returns the full RAGResult object.
        Returns None if RAG is unavailable.
        """
        if not self._ensure_ready():
            return None
        try:
            return self._pipeline.query(question, on_token=on_token)
        except Exception as exc:
            self._logger.warning("RagService.ask_docs_full failed: %s", exc)
            return None

    def ingest_directory(self, docs_dir: str | None = None, reset: bool = False) -> str:
        """
        Ingest documents from *docs_dir* (defaults to config.rag_docs_dir).
        Returns a human-readable status string.
        """
        if not self._ensure_ready():
            return "RAG backend unavailable — skipping ingestion."
        target = docs_dir or self._config.rag_docs_dir
        try:
            return self._pipeline.ingest(target, reset=reset)
        except Exception as exc:
            self._logger.warning("RagService.ingest_directory failed: %s", exc)
            return f"Ingestion failed: {exc}"

    def ingest_text(self, text: str, source_name: str, metadata: dict | None = None) -> int:
        """Ingest raw text directly. Returns chunk count (0 if unavailable)."""
        if not self._ensure_ready():
            return 0
        try:
            return self._pipeline.ingest_text(text, source_name, metadata)
        except Exception as exc:
            self._logger.warning("RagService.ingest_text failed: %s", exc)
            return 0

    def store_user_fact(self, text: str, category: str = "fact") -> bool:
        """Store a user fact/preference in RAG long-term memory."""
        if not self._ensure_ready():
            return False
        try:
            self.get_user_memory.cache_clear()
            return self._pipeline.store_memory(text, category=category)
        except Exception:
            return False

    @functools.lru_cache(maxsize=32)
    def get_user_memory(self, query: str, limit: int = 4) -> list:
        """Retrieve relevant memory facts for *query*."""
        if not self._ensure_ready():
            return []
        try:
            return self._pipeline.get_memory(query, limit=limit)
        except Exception:
            return []

    def get_memory(self, query: str, limit: int = 4) -> list:
        """Backward-compatible alias used by assistant integrations."""
        return self.get_user_memory(query, limit=limit)

    def stats(self) -> dict:
        """Return knowledge base statistics."""
        if not self._available:
            return {"available": False}
        try:
            s = self._pipeline.knowledge_base_stats()
            s["available"] = True
            return s
        except Exception:
            return {"available": False}

    def auto_ingest_background(self) -> None:
        """
        Trigger background ingestion from the configured docs directory.
        Safe to call multiple times — only runs once per session.
        """
        if self._auto_ingest_done:
            return
        self._auto_ingest_done = True
        thread = threading.Thread(
            target=self._background_ingest,
            daemon=True,
            name="edith-rag-ingest",
        )
        thread.start()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _ensure_ready(self) -> bool:
        """Lazy-initialise the pipeline. Thread-safe."""
        if self._available:
            return True
        with self._lock:
            if self._available:
                return True
            if self._init_attempted:
                return False
            self._init_attempted = True
            return self._init_pipeline()

    def _init_pipeline(self) -> bool:
        """Instantiate RAGPipeline with config settings."""
        try:
            from edith_app.rag.pipeline import RAGPipeline  # type: ignore

            self._pipeline = RAGPipeline(
                chroma_path=self._config.rag_db_path,
                embed_model=self._config.rag_embed_model,
                rerank_model=self._config.rag_rerank_model,
                ollama_url=self._config.ollama_url,
                ollama_model=self._config.ollama_model,
                retrieval_k=self._config.rag_retrieval_k,
                use_reranker=self._config.rag_enabled,
            )
            self._available = True
            self._logger.info("RagService ready.")
            return True
        except ImportError as exc:
            self._logger.warning(
                "RAG dependencies missing (%s). "
                "Install: pip install chromadb sentence-transformers pypdf",
                exc,
            )
            return False
        except Exception as exc:
            self._logger.error("RagService init failed: %s", exc)
            return False

    def _background_ingest(self) -> None:
        """Run directory ingestion in a background thread."""
        docs_dir = Path(self._config.rag_docs_dir)
        if not docs_dir.exists():
            self._logger.debug("RAG docs directory not found, skipping auto-ingest: %s", docs_dir)
            return
        # Only ingest if there are files
        files = list(docs_dir.rglob("*"))
        doc_files = [f for f in files if f.is_file() and f.suffix.lower() in {".txt", ".md", ".pdf", ".rst"}]
        if not doc_files:
            self._logger.debug("No docs to ingest in %s", docs_dir)
            return
        if not self._ensure_ready():
            return
        self._logger.info("Background ingest: %d files from %s", len(doc_files), docs_dir)
        try:
            result = self._pipeline.ingest(str(docs_dir))
            self._logger.info("Background ingest complete: %s", result)
        except Exception as exc:
            self._logger.warning("Background ingest failed: %s", exc)
