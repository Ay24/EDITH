"""
edith_app.rag.retrieval
=======================
ChromaDB-backed retriever with MMR (Maximal Marginal Relevance) and
similarity-threshold filtering for EDITH's RAG pipeline.

Features
--------
* BGE-small embeddings via sentence-transformers (runs fully offline / CPU)
* MMR diversity re-ranking to avoid redundant chunks
* Configurable k, similarity threshold, fetch multiplier
* Source-type filtering
* Graceful degradation if deps missing
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("edith.rag.retrieval")


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    source_name: str
    source_path: str
    chunk_index: int
    score: float          # cosine similarity score (0-1)
    metadata: dict


# ── MMR helper ────────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two unit-normalised vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _mmr(
    query_emb: list[float],
    candidates: list[tuple[RetrievedChunk, list[float]]],
    k: int,
    lambda_mult: float = 0.6,
) -> list[RetrievedChunk]:
    """
    Maximal Marginal Relevance selection.

    Parameters
    ----------
    query_emb    : query embedding vector
    candidates   : list of (chunk, embedding) pairs, pre-filtered by threshold
    k            : number of chunks to select
    lambda_mult  : trade-off between relevance (1.0) and diversity (0.0)
    """
    if not candidates:
        return []
    selected: list[tuple[RetrievedChunk, list[float]]] = []
    remaining = list(candidates)

    for _ in range(min(k, len(remaining))):
        best_score = -float("inf")
        best_idx = 0
        for i, (chunk, emb) in enumerate(remaining):
            relevance = _cosine(query_emb, emb)
            if selected:
                max_sim = max(_cosine(emb, sel_emb) for _, sel_emb in selected)
            else:
                max_sim = 0.0
            mmr_score = lambda_mult * relevance - (1 - lambda_mult) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i
        selected.append(remaining.pop(best_idx))

    return [chunk for chunk, _ in selected]


# ── RAGRetriever ──────────────────────────────────────────────────────────────

class RAGRetriever:
    """
    Retrieves relevant document chunks from ChromaDB using BGE embeddings.

    Parameters
    ----------
    chroma_path       : persistent ChromaDB directory
    embed_model       : HuggingFace sentence-transformers model name
    collection_name   : ChromaDB collection for document chunks
    k                 : number of final chunks to return
    fetch_multiplier  : how many extra candidates to fetch before MMR
    similarity_threshold : minimum cosine score to keep a candidate (0-1)
    lambda_mult       : MMR diversity weight (0=diverse, 1=pure relevance)
    """

    def __init__(
        self,
        chroma_path: str = "data/rag_chroma",
        embed_model: str = "BAAI/bge-small-en-v1.5",
        collection_name: str = "edith_docs",
        k: int = 6,
        fetch_multiplier: int = 4,
        similarity_threshold: float = 0.25,
        lambda_mult: float = 0.6,
    ) -> None:
        self._chroma_path = Path(chroma_path)
        self._embed_model_name = embed_model
        self._collection_name = collection_name
        self._k = k
        self._fetch_mult = fetch_multiplier
        self._threshold = similarity_threshold
        self._lambda = lambda_mult
        self._client = None
        self._col = None
        self._embedder = None   # SentenceTransformer instance
        self._ready = False

    # ── Public API ────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        k: int | None = None,
        source_filter: str | None = None,
    ) -> list[RetrievedChunk]:
        """
        Retrieve up to *k* relevant chunks for *query*.

        Parameters
        ----------
        query         : user question string
        k             : override default k if provided
        source_filter : restrict to chunks whose source_name matches this value
        """
        if not query.strip():
            return []
        if not self._init():
            return []

        final_k = k if k is not None else self._k
        fetch_n = final_k * self._fetch_mult

        # Build query embedding
        query_emb = self._embed(query)
        if not query_emb:
            return []

        # Build ChromaDB where-filter
        where: dict | None = None
        if source_filter:
            where = {"source_name": source_filter}

        # Fetch candidates from ChromaDB
        try:
            result = self._col.query(
                query_embeddings=[query_emb],
                n_results=min(fetch_n, max(1, self._col.count())),
                where=where,
                include=["documents", "metadatas", "distances", "embeddings"],
            )
        except Exception as exc:
            logger.warning("ChromaDB query failed: %s", exc)
            return []

        # Unpack results
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        embeddings = result.get("embeddings", [[]])[0]

        # ChromaDB returns L2 distances for cosine space; convert to similarity
        candidates: list[tuple[RetrievedChunk, list[float]]] = []
        for cid, doc, meta, dist, emb in zip(ids, docs, metas, distances, embeddings):
            # For cosine space in ChromaDB: similarity = 1 - distance
            similarity = max(0.0, 1.0 - float(dist))
            if similarity < self._threshold:
                continue
            chunk = RetrievedChunk(
                chunk_id=cid,
                text=doc,
                source_name=meta.get("source_name", ""),
                source_path=meta.get("source_path", ""),
                chunk_index=int(meta.get("chunk_index", "0")),
                score=similarity,
                metadata=meta,
            )
            candidates.append((chunk, list(emb) if emb else []))

        if not candidates:
            logger.debug("No chunks above threshold %.2f for query: %s", self._threshold, query[:60])
            return []

        # Apply MMR to promote diversity
        selected = _mmr(query_emb, candidates, k=final_k, lambda_mult=self._lambda)
        logger.debug("Retrieved %d chunks (from %d candidates) for query: %s", len(selected), len(candidates), query[:60])
        return selected

    def retrieve_similarity(self, query: str, k: int | None = None) -> list[RetrievedChunk]:
        """Pure similarity retrieval (no MMR), sorted by score descending."""
        if not query.strip():
            return []
        if not self._init():
            return []

        final_k = k if k is not None else self._k
        query_emb = self._embed(query)

        try:
            result = self._col.query(
                query_embeddings=[query_emb],
                n_results=min(final_k, max(1, self._col.count())),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("similarity query failed: %s", exc)
            return []

        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        chunks: list[RetrievedChunk] = []
        for cid, doc, meta, dist in zip(ids, docs, metas, distances):
            similarity = max(0.0, 1.0 - float(dist))
            if similarity < self._threshold:
                continue
            chunks.append(RetrievedChunk(
                chunk_id=cid,
                text=doc,
                source_name=meta.get("source_name", ""),
                source_path=meta.get("source_path", ""),
                chunk_index=int(meta.get("chunk_index", "0")),
                score=similarity,
                metadata=meta,
            ))
        return sorted(chunks, key=lambda c: c.score, reverse=True)

    def chunk_count(self) -> int:
        if not self._init():
            return 0
        try:
            return self._col.count()
        except Exception:
            return 0

    def is_ready(self) -> bool:
        return self._init()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _init(self) -> bool:
        if self._ready:
            return True
        try:
            import chromadb  # type: ignore
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._chroma_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._chroma_path))

            # CPU-only embedder — never competes with the main LLM for VRAM.
            # Uses the same model that was used to ingest the collection (768-dim).
            # GTX 1650 cannot run F16 cuBLAS ops (nomic-embed-text crashes).
            cpu_model = SentenceTransformer(
                self._embed_model_name,
                device="cpu",
                trust_remote_code=True,
            )

            class _SentenceTransformerEmbed:
                """ChromaDB-compatible embedding function wrapper."""
                def __init__(self, model: SentenceTransformer) -> None:
                    self._model = model

                def __call__(self, input: list[str]) -> list[list[float]]:
                    if isinstance(input, str):
                        input = [input]
                    try:
                        vecs = self._model.encode(
                            input,
                            normalize_embeddings=True,
                            batch_size=16,
                            show_progress_bar=False,
                        )
                        return [v.tolist() for v in vecs]
                    except Exception as exc:
                        logger.warning("Embedding failed: %s", exc)
                        # Return empty lists — ChromaDB will reject rather than
                        # silently store dimension-mismatched zero vectors.
                        return [[] for _ in input]

            emb_fn = _SentenceTransformerEmbed(cpu_model)
            self._embedder = emb_fn
            self._col = self._client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=emb_fn,
                metadata={"hnsw:space": "cosine"},
            )
            self._ready = True
            logger.info(
                "Retriever ready — model=%s device=cpu chunks=%d",
                self._embed_model_name,
                self._col.count(),
            )
            return True
        except ImportError as exc:
            logger.warning("RAG retrieval deps missing (%s). pip install chromadb sentence-transformers", exc)
            return False
        except Exception as exc:
            logger.error("Retriever init error: %s", exc)
            return False

    def _embed(self, text: str) -> list[float]:
        """Embed a single text string, returning a normalised float list."""
        try:
            result = self._embedder([text])
            return result[0] if result and result[0] else []
        except Exception as exc:
            logger.warning("Embedding failed: %s", exc)
            return []
