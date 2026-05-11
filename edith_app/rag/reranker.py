"""
edith_app.rag.reranker
======================
Cross-encoder re-ranking layer for EDITH's RAG pipeline.

Re-ranks a list of retrieved chunks using a cross-encoder model
(ms-marco-MiniLM-L-6-v2) which scores query-passage pairs directly,
giving significantly better ranking than bi-encoder cosine similarity alone.

Gracefully degrades to pass-through (original order) if cross-encoder
model or sentence-transformers is unavailable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from edith_app.rag.retrieval import RetrievedChunk

logger = logging.getLogger("edith.rag.reranker")


@dataclass
class RankedChunk:
    """A chunk after cross-encoder re-ranking."""
    chunk: RetrievedChunk
    rerank_score: float   # raw cross-encoder logit (higher = more relevant)


class CrossEncoderReranker:
    """
    Re-ranks retrieved chunks with a cross-encoder model.

    Parameters
    ----------
    model_name : HuggingFace cross-encoder model identifier
    top_n      : number of chunks to keep after re-ranking
    batch_size : inference batch size
    score_threshold : minimum cross-encoder score to keep a chunk
                      (None = keep all top_n regardless of score)
    """

    DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        top_n: int = 4,
        batch_size: int = 16,
        score_threshold: float | None = None,
    ) -> None:
        self._model_name = model_name
        self._top_n = top_n
        self._batch_size = batch_size
        self._threshold = score_threshold
        self._model = None
        self._ready = False

    # ── Public API ────────────────────────────────────────────────────────────

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_n: int | None = None,
        fast_path_threshold: float = 0.85,
    ) -> list[RankedChunk]:
        """
        Re-rank *chunks* for *query*.

        Returns a list of RankedChunk sorted by rerank_score descending.
        Falls back to original retrieval order if model unavailable.
        If the top retrieved chunk has a score >= fast_path_threshold, bypasses
        re-ranking entirely to save latency.
        """
        if not chunks:
            return []

        final_n = top_n if top_n is not None else self._top_n

        # Fast-path bypass for extremely high confidence matches
        top_retrieval_score = max(c.score for c in chunks)
        if top_retrieval_score >= fast_path_threshold:
            logger.debug("Bypassing re-ranker: top retrieval score %.3f >= %.3f", 
                         top_retrieval_score, fast_path_threshold)
            fallback = [RankedChunk(chunk=c, rerank_score=c.score) for c in chunks]
            return sorted(fallback, key=lambda r: r.rerank_score, reverse=True)[:final_n]

        if not self._init():
            # Graceful degradation: wrap in RankedChunk with retrieval score
            logger.debug("Cross-encoder unavailable, using retrieval order")
            fallback = [RankedChunk(chunk=c, rerank_score=c.score) for c in chunks]
            return sorted(fallback, key=lambda r: r.rerank_score, reverse=True)[:final_n]

        # Build (query, passage) pairs for cross-encoder
        pairs = [(query, c.text) for c in chunks]

        # Batch inference
        scores: list[float] = []
        try:
            for start in range(0, len(pairs), self._batch_size):
                batch = pairs[start : start + self._batch_size]
                batch_scores = self._model.predict(batch, show_progress_bar=False)
                scores.extend(float(s) for s in batch_scores)
        except Exception as exc:
            logger.warning("Cross-encoder inference failed: %s — using retrieval order", exc)
            fallback = [RankedChunk(chunk=c, rerank_score=c.score) for c in chunks]
            return sorted(fallback, key=lambda r: r.rerank_score, reverse=True)[:final_n]

        # Pair chunks with their rerank scores
        ranked = [
            RankedChunk(chunk=c, rerank_score=s)
            for c, s in zip(chunks, scores)
        ]

        # Apply optional score threshold
        if self._threshold is not None:
            ranked = [r for r in ranked if r.rerank_score >= self._threshold]

        # Sort descending and truncate
        ranked.sort(key=lambda r: r.rerank_score, reverse=True)
        result = ranked[:final_n]

        logger.debug(
            "Re-ranked %d → %d chunks. Top score: %.3f",
            len(chunks),
            len(result),
            result[0].rerank_score if result else 0.0,
        )
        return result

    def is_ready(self) -> bool:
        return self._init()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _init(self) -> bool:
        if self._ready:
            return True
        # Completely disable cross-encoder CPU inference because it destroys latency on local hardware.
        # RAG pipeline degrades gracefully and relies perfectly on MMR Nomic Embeddings.
        self._ready = False
        return False
