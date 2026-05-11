"""
edith_app.rag
=============
Production RAG (Retrieval-Augmented Generation) subsystem for EDITH.

Public API
----------
    from edith_app.rag import RAGPipeline, DocumentIngester, RAGMemory

The entire package is soft-optional: all heavy dependencies (chromadb,
sentence-transformers, pypdf) are imported lazily and guarded so that EDITH
continues to run normally even when they are not installed.
"""
from __future__ import annotations

from edith_app.rag.ingestion import DocumentIngester
from edith_app.rag.memory import RAGMemory
from edith_app.rag.pipeline import RAGPipeline, RAGResult

__all__ = [
    "DocumentIngester",
    "RAGMemory",
    "RAGPipeline",
    "RAGResult",
]
