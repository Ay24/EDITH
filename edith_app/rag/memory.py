"""
edith_app.rag.memory
====================
Long-term RAG memory for EDITH.

Stores user facts, preferences, and interaction summaries in a dedicated
ChromaDB collection, enabling semantic retrieval of past context.

This complements (not replaces) the existing MemoryService — it provides
vector-based recall while MemoryService handles structured JSONL storage.

Usage
-----
    mem = RAGMemory(chroma_path="data/rag_chroma")
    mem.store("User prefers dark mode", category="preference")
    results = mem.retrieve("what does the user like?")
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("edith.rag.memory")


@dataclass
class MemoryFact:
    fact_id: str
    text: str
    category: str     # e.g. "preference", "interaction", "fact", "goal"
    stored_at: str    # ISO timestamp string
    score: float = 0.0


class RAGMemory:
    """
    Semantic long-term memory backed by a ChromaDB vector collection.

    Categories
    ----------
    preference  : user preferences (e.g. "prefers concise answers")
    fact        : factual information about the user or context
    interaction : summarised past interactions worth remembering
    goal        : ongoing goals or projects the user is pursuing
    """

    COLLECTION_NAME = "edith_memory"

    def __init__(
        self,
        chroma_path: str = "data/rag_chroma",
        embed_model: str = "BAAI/bge-small-en-v1.5",
        max_facts: int = 500,
    ) -> None:
        self._chroma_path = Path(chroma_path)
        self._embed_model_name = embed_model
        self._max_facts = max_facts
        self._client = None
        self._col = None
        self._embedder = None
        self._ready = False

    # ── Public API ────────────────────────────────────────────────────────────

    def store(self, text: str, category: str = "fact") -> bool:
        """
        Store a fact/preference/interaction in long-term memory.
        Deduplicates by content hash so the same fact isn't stored twice.
        Returns True if stored, False if duplicate or backend unavailable.
        """
        text = text.strip()
        if not text:
            return False
        if not self._init():
            return False

        fact_id = self._make_id(text)

        # Skip exact duplicates
        try:
            existing = self._col.get(ids=[fact_id])
            if existing["ids"]:
                logger.debug("Duplicate memory fact skipped: %s", text[:60])
                return False
        except Exception:
            pass

        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            self._col.upsert(
                ids=[fact_id],
                documents=[text],
                metadatas=[{
                    "category": category,
                    "stored_at": ts,
                    "char_count": str(len(text)),
                }],
            )
            logger.debug("Stored memory [%s]: %s", category, text[:80])
            # Prune oldest if over limit
            self._maybe_prune()
            return True
        except Exception as exc:
            logger.warning("Memory store failed: %s", exc)
            return False

    def retrieve(
        self,
        query: str,
        limit: int = 4,
        category: str | None = None,
    ) -> list[MemoryFact]:
        """
        Retrieve the most semantically relevant memory facts for *query*.

        Parameters
        ----------
        query    : search query string
        limit    : maximum number of facts to return
        category : optional filter by category
        """
        if not query.strip() or not self._init():
            return []

        query_emb = self._embed(query)
        where: dict | None = {"category": category} if category else None

        try:
            count = self._col.count()
            if count == 0:
                return []
            result = self._col.query(
                query_embeddings=[query_emb],
                n_results=min(limit, count),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("Memory retrieve failed: %s", exc)
            return []

        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        facts: list[MemoryFact] = []
        for fid, doc, meta, dist in zip(ids, docs, metas, distances):
            similarity = max(0.0, 1.0 - float(dist))
            facts.append(MemoryFact(
                fact_id=fid,
                text=doc,
                category=meta.get("category", "fact"),
                stored_at=meta.get("stored_at", ""),
                score=similarity,
            ))
        return facts

    def get_recent(self, limit: int = 6) -> list[MemoryFact]:
        """Return the most recently stored memory facts (chronological)."""
        if not self._init():
            return []
        try:
            count = self._col.count()
            if count == 0:
                return []
            # ChromaDB doesn't support ORDER BY, so fetch a window and sort by timestamp
            result = self._col.get(
                limit=min(limit * 4, count),
                include=["documents", "metadatas"],
            )
            facts: list[MemoryFact] = []
            for fid, doc, meta in zip(result["ids"], result["documents"], result["metadatas"]):
                facts.append(MemoryFact(
                    fact_id=fid,
                    text=doc,
                    category=meta.get("category", "fact"),
                    stored_at=meta.get("stored_at", ""),
                ))
            facts.sort(key=lambda f: f.stored_at, reverse=True)
            return facts[:limit]
        except Exception as exc:
            logger.warning("get_recent failed: %s", exc)
            return []

    def delete(self, fact_id: str) -> bool:
        """Delete a specific memory fact by ID."""
        if not self._init():
            return False
        try:
            self._col.delete(ids=[fact_id])
            return True
        except Exception:
            return False

    def fact_count(self) -> int:
        if not self._init():
            return 0
        try:
            return self._col.count()
        except Exception:
            return 0

    def clear_category(self, category: str) -> int:
        """Delete all facts in a given category. Returns deleted count."""
        if not self._init():
            return 0
        try:
            result = self._col.get(where={"category": category}, limit=10000)
            ids = result.get("ids", [])
            if ids:
                self._col.delete(ids=ids)
            return len(ids)
        except Exception as exc:
            logger.warning("clear_category failed: %s", exc)
            return 0

    # ── Internal ──────────────────────────────────────────────────────────────

    def _init(self) -> bool:
        if self._ready:
            return True
        try:
            import chromadb  # type: ignore

            class OllamaEmbed:
                def __init__(self, model_name):
                    self.model = model_name
                    import requests
                    self.requests = requests

                def __call__(self, input):
                    if isinstance(input, str): input = [input]
                    res = []
                    for t in input:
                        r = self.requests.post(
                            "http://127.0.0.1:11434/api/embed", 
                            json={
                                "model": self.model, 
                                "input": t,
                                "options": {"num_ctx": 2048}
                            }, 
                            timeout=10
                        )
                        if r.status_code == 200:
                            emb = r.json().get("embeddings", [[]])[0]
                            res.append(emb)
                        else:
                            res.append([])
                    return res

            self._chroma_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._chroma_path))
            emb_fn = OllamaEmbed(self._embed_model_name)
            self._col = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                embedding_function=emb_fn,
                metadata={"hnsw:space": "cosine"},
            )
            self._embedder = emb_fn
            self._ready = True
            logger.info("RAGMemory ready — facts=%d", self._col.count())
            return True
        except ImportError:
            logger.warning("RAGMemory deps missing. pip install chromadb")
            return False
        except Exception as exc:
            logger.error("RAGMemory init failed: %s", exc)
            return False

    def _embed(self, text: str) -> list[float]:
        try:
            return self._embedder([text])[0]
        except Exception:
            return []

    def _make_id(self, text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def _maybe_prune(self) -> None:
        """Remove oldest facts if collection exceeds max_facts."""
        try:
            count = self._col.count()
            if count <= self._max_facts:
                return
            # Fetch all and delete oldest N
            result = self._col.get(limit=count, include=["metadatas"])
            pairs = list(zip(result["ids"], result["metadatas"]))
            pairs.sort(key=lambda p: p[1].get("stored_at", ""))
            to_delete = [fid for fid, _ in pairs[: count - self._max_facts]]
            if to_delete:
                self._col.delete(ids=to_delete)
                logger.debug("Pruned %d old memory facts", len(to_delete))
        except Exception:
            pass
