"""
edith_app.rag.pipeline
=======================
Master orchestrator for EDITH's RAG pipeline.

Pipeline stages
---------------
1. Query expansion  — generate sub-questions / rephrasings (optional)
2. Retrieval        — fetch candidates from ChromaDB via MMR
3. Re-ranking       — cross-encoder re-scores and reorders chunks
4. Context building — deduplicate + format into a grounded prompt
5. Generation       — call Ollama LLM with strict context-only instruction
6. Memory storage   — persist interaction summary for future retrieval

Usage
-----
    cfg = AppConfig()
    pipeline = RAGPipeline(config=cfg)
    result = pipeline.query("What is EDITH's architecture?")
    print(result.answer)
    print(result.sources)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from edith_app.rag.context_builder import BuiltContext, ContextBuilder
from edith_app.rag.generator import GeneratorResult, RAGGenerator
from edith_app.rag.ingestion import DocumentIngester
from edith_app.rag.memory import MemoryFact, RAGMemory
from edith_app.rag.reranker import CrossEncoderReranker
from edith_app.rag.retrieval import RAGRetriever, RetrievedChunk

logger = logging.getLogger("edith.rag.pipeline")


# ── Result type ──────────────────────────────────────────────────────────────

@dataclass
class RAGResult:
    """Full result from a RAG pipeline query."""
    answer: str
    sources: list[str] = field(default_factory=list)
    doc_chunks_used: int = 0
    memory_facts_used: int = 0
    latency_ms: float = 0.0
    was_grounded: bool = True
    context_chars: int = 0
    retrieval_count: int = 0
    reranked: bool = False
    error: str = ""

    def __str__(self) -> str:
        src = ", ".join(self.sources) if self.sources else "no sources"
        return (
            f"{self.answer}\n\n"
            f"[Sources: {src} | {self.doc_chunks_used} chunks | "
            f"{self.latency_ms:.0f}ms]"
        )


# ── Query expansion ───────────────────────────────────────────────────────────

def _expand_query(query: str) -> list[str]:
    """
    Lightweight query expansion: generate alternative rephrasings locally
    without an LLM call to keep latency low.

    Returns a list of queries including the original.
    """
    queries = [query.strip()]

    # Add 'what is' variant for short factual queries
    lower = query.lower().strip()
    if not lower.startswith(("what", "how", "why", "when", "where", "who", "is", "are", "does")):
        queries.append(f"What is {query}?")

    # Add 'explain' variant for definition-like queries
    if len(query.split()) <= 6:
        queries.append(f"Explain {query}")

    return queries[:3]  # Cap at 3 to avoid over-fetching


# ── RAGPipeline ──────────────────────────────────────────────────────────────

class RAGPipeline:
    """
    Orchestrates the full RAG pipeline: retrieve → rerank → build → generate.

    Parameters
    ----------
    chroma_path        : persistent ChromaDB directory
    embed_model        : HuggingFace embedding model
    rerank_model       : HuggingFace cross-encoder model
    ollama_url         : Ollama server base URL
    ollama_model       : Ollama model name for generation
    retrieval_k        : number of chunks to retrieve (before reranking)
    rerank_top_n       : number of chunks to keep after reranking
    max_context_chars  : character budget for context block
    similarity_threshold : minimum retrieval similarity score (0-1)
    use_query_expansion: whether to expand the query before retrieval
    use_reranker       : whether to run cross-encoder re-ranking
    store_interactions : whether to store each interaction in RAG memory
    """

    def __init__(
        self,
        chroma_path: str = "data/rag_chroma",
        embed_model: str = "BAAI/bge-small-en-v1.5",
        rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        ollama_url: str = "http://127.0.0.1:11434",
        ollama_model: str = "phi3",
        retrieval_k: int = 6,
        rerank_top_n: int = 4,
        max_context_chars: int = 6000,
        similarity_threshold: float = 0.25,
        use_query_expansion: bool = True,
        use_reranker: bool = True,
        store_interactions: bool = True,
    ) -> None:
        self._retriever = RAGRetriever(
            chroma_path=chroma_path,
            embed_model=embed_model,
            k=retrieval_k,
            similarity_threshold=similarity_threshold,
        )
        self._reranker = CrossEncoderReranker(
            model_name=rerank_model,
            top_n=rerank_top_n,
        )
        self._context_builder = ContextBuilder(
            max_chars=max_context_chars,
        )
        self._generator = RAGGenerator(
            ollama_url=ollama_url,
            model=ollama_model,
            max_tokens=350,
            temperature=0.15,
        )
        self._memory = RAGMemory(
            chroma_path=chroma_path,
            embed_model=embed_model,
        )
        self._ingester = DocumentIngester(
            chroma_path=chroma_path,
            embed_model=embed_model,
        )
        self._use_expansion = use_query_expansion
        self._use_reranker = use_reranker
        self._store_interactions = store_interactions

    # ── Public API ────────────────────────────────────────────────────────────

    def query(
        self,
        question: str,
        on_token: Callable[[str], None] | None = None,
        memory_limit: int = 3,
    ) -> RAGResult:
        """
        Run the full RAG pipeline for *question*.

        Parameters
        ----------
        question     : the user's question
        on_token     : optional streaming callback for token-by-token output
        memory_limit : max memory facts to inject
        """
        t0 = time.monotonic()

        if not question.strip():
            return RAGResult(answer="Please provide a question.", error="empty_query")

        # ── Stage 1: Query expansion ─────────────────────────────────────────
        queries = _expand_query(question) if self._use_expansion else [question]

        # ── Stage 2: Retrieval ───────────────────────────────────────────────
        all_chunks: dict[str, RetrievedChunk] = {}
        for q in queries:
            hits = self._retriever.retrieve(q)
            for chunk in hits:
                # Deduplicate by chunk_id, keep highest score
                if chunk.chunk_id not in all_chunks or chunk.score > all_chunks[chunk.chunk_id].score:
                    all_chunks[chunk.chunk_id] = chunk

        chunks = list(all_chunks.values())
        retrieval_count = len(chunks)

        if not chunks:
            logger.info("No chunks retrieved for: %s", question[:60])
            # Still try memory for conversational context
            memory_facts = self._memory.retrieve(question, limit=memory_limit)
            if memory_facts:
                context = self._context_builder.build(
                    query=question,
                    doc_chunks=[],
                    memory_facts=memory_facts,
                )
                if context.memory_facts_used > 0:
                    prompt = self._context_builder.format_for_prompt(context, question)
                    gen = self._generator.generate(prompt, context, on_token=on_token)
                    latency = (time.monotonic() - t0) * 1000
                    return RAGResult(
                        answer=gen.answer,
                        sources=[],
                        doc_chunks_used=0,
                        memory_facts_used=context.memory_facts_used,
                        latency_ms=latency,
                        was_grounded=gen.was_grounded,
                        context_chars=context.char_count,
                        retrieval_count=0,
                    )
            return RAGResult(
                answer="I don't have that information in my knowledge base.",
                error="no_chunks_retrieved",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        # ── Stage 3: Re-ranking ──────────────────────────────────────────────
        ranked_chunks = None
        reranked = False
        
        # Fast-Path: if initial retrieval confidence is extremely high, skip reranking
        fast_path_eligible = any(c.score > 0.85 for c in chunks)
        
        if self._use_reranker and not fast_path_eligible:
            ranked_chunks = self._reranker.rerank(question, chunks)
            reranked = True
        elif fast_path_eligible:
            # Sort by score descending if skipping reranker
            ranked_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)[:self._reranker._top_n if hasattr(self._reranker, '_top_n') else 4]
            logger.info("Fast-path triggered: skipping reranker due to high confidence match.")

        # ── Stage 4: Memory retrieval ────────────────────────────────────────
        memory_facts = self._memory.retrieve(question, limit=memory_limit)

        # ── Stage 5: Context building ────────────────────────────────────────
        context = self._context_builder.build(
            query=question,
            doc_chunks=chunks,
            memory_facts=memory_facts,
            ranked_chunks=ranked_chunks,
        )
        prompt = self._context_builder.format_for_prompt(context, question)

        # ── Stage 6: Generation ──────────────────────────────────────────────
        gen_result = self._generator.generate(prompt, context, on_token=on_token)

        # ── Stage 7: Store interaction in memory ─────────────────────────────
        if self._store_interactions and gen_result.was_grounded and gen_result.answer:
            summary = f"Q: {question[:120]} A: {gen_result.answer[:200]}"
            self._memory.store(summary, category="interaction")

        latency_ms = (time.monotonic() - t0) * 1000

        result = RAGResult(
            answer=gen_result.answer,
            sources=context.sources,
            doc_chunks_used=context.doc_chunks_used,
            memory_facts_used=context.memory_facts_used,
            latency_ms=latency_ms,
            was_grounded=gen_result.was_grounded,
            context_chars=context.char_count,
            retrieval_count=retrieval_count,
            reranked=reranked,
        )

        logger.info(
            "RAG query complete in %.0fms | chunks=%d reranked=%s grounded=%s",
            latency_ms,
            retrieval_count,
            reranked,
            result.was_grounded,
        )
        return result

    def ingest(self, docs_dir: str, reset: bool = False) -> str:
        """Ingest documents into the knowledge base. Returns a status string."""
        stats = self._ingester.ingest_directory(docs_dir, reset=reset)
        return str(stats)

    def ingest_text(self, text: str, source_name: str, metadata: dict | None = None) -> int:
        """Ingest raw text directly. Returns chunk count."""
        return self._ingester.ingest_text(text, source_name, metadata)

    def store_memory(self, text: str, category: str = "fact") -> bool:
        """Manually store a fact in long-term memory."""
        return self._memory.store(text, category=category)

    def get_memory(self, query: str, limit: int = 4) -> list[MemoryFact]:
        """Retrieve relevant memory facts for a query."""
        return self._memory.retrieve(query, limit=limit)

    def knowledge_base_stats(self) -> dict:
        """Return statistics about the knowledge base."""
        return {
            "doc_chunks": self._retriever.chunk_count(),
            "memory_facts": self._memory.fact_count(),
            "retriever_ready": self._retriever.is_ready(),
            "reranker_ready": self._reranker.is_ready(),
        }

    def set_model(self, model: str) -> None:
        """Change the generation model at runtime."""
        self._generator.set_model(model)
