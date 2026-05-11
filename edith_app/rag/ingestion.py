"""
edith_app.rag.ingestion
=======================
Document ingestion pipeline for EDITH's RAG system.

Loads .txt, .md, .pdf files → cleans → chunks (400-600 tokens) → stores in ChromaDB.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("edith.rag.ingestion")


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class DocumentChunk:
    chunk_id: str
    source_path: str
    source_name: str
    chunk_index: int
    text: str
    char_count: int
    metadata: dict


@dataclass
class IngestionStats:
    files_processed: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    chunks_added: int = 0
    duration_seconds: float = 0.0
    errors: list = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"{self.files_processed} files processed, {self.files_skipped} skipped, "
            f"{self.files_failed} failed | {self.chunks_added} chunks added "
            f"in {self.duration_seconds:.1f}s"
        )


# ── Text cleaning ────────────────────────────────────────────────────────────

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
_MULTI_NL = re.compile(r"\n{3,}")
_MULTI_SP = re.compile(r" {2,}")


def _clean_text(text: str) -> str:
    text = _URL_RE.sub(" ", text)
    text = _EMAIL_RE.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    text = _MULTI_SP.sub(" ", text)
    return text.strip()


# ── Token counting (approximate) ────────────────────────────────────────────

def _approx_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


# ── Chunking ─────────────────────────────────────────────────────────────────

def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    out: list[str] = []
    for p in parts:
        for sub in p.split("\n\n"):
            s = sub.strip()
            if s:
                out.append(s)
    return out


def chunk_text(text: str, target: int = 500, overlap: int = 80, min_t: int = 40) -> list[str]:
    """Split text into overlapping token-budget chunks, sentence-aware."""
    sents = _sentences(text)
    if not sents:
        return []
    chunks: list[str] = []
    cur: list[str] = []
    cur_t = 0
    for sent in sents:
        st = _approx_tokens(sent)
        if st > target:
            # Force-split on word level
            words = sent.split()
            part: list[str] = []
            pt = 0
            for w in words:
                part.append(w)
                pt += 1
                if pt >= target:
                    chunks.append(" ".join(part))
                    part = part[-max(1, overlap // 2):]
                    pt = len(part)
            if part:
                cur = part
                cur_t = len(part)
            continue
        if cur_t + st > target and cur:
            chunks.append(" ".join(cur))
            ob = overlap
            back: list[str] = []
            for s in reversed(cur):
                t2 = _approx_tokens(s)
                if ob - t2 < 0:
                    break
                back.insert(0, s)
                ob -= t2
            cur = back
            cur_t = sum(_approx_tokens(s) for s in cur)
        cur.append(sent)
        cur_t += st
    if cur:
        chunks.append(" ".join(cur))
    return [c for c in chunks if _approx_tokens(c) >= min_t]


# ── File loaders ──────────────────────────────────────────────────────────────

def _load_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _load_pdf(path: Path) -> str:
    try:
        import pypdf  # type: ignore
    except ImportError:
        raise RuntimeError("pypdf not installed. Run: pip install pypdf")
    reader = pypdf.PdfReader(str(path))
    return "\n\n".join(p.extract_text() or "" for p in reader.pages)


def _load_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".rst", ".text"}:
        return _load_txt(path)
    if suffix == ".pdf":
        return _load_pdf(path)
    raise ValueError(f"Unsupported extension: {suffix}")


# ── ID helpers ────────────────────────────────────────────────────────────────

def _chunk_id(source: str, idx: int) -> str:
    return hashlib.sha1(f"{source}::{idx}".encode()).hexdigest()


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        h.update(f.read(512 * 1024))
    return h.hexdigest()


# ── DocumentIngester ──────────────────────────────────────────────────────────

class DocumentIngester:
    """
    Loads, cleans, chunks, and stores documents in a ChromaDB collection.

    Parameters
    ----------
    chroma_path  : persistent ChromaDB directory
    embed_model  : HuggingFace sentence-transformers model name
    collection   : ChromaDB collection name for document chunks
    target_tokens: target chunk size in tokens
    overlap_tokens: overlap window in tokens
    """

    SUPPORTED = {".txt", ".md", ".rst", ".text", ".pdf"}

    def __init__(
        self,
        chroma_path: str = "data/rag_chroma",
        embed_model: str = "BAAI/bge-small-en-v1.5",
        collection: str = "edith_docs",
        target_tokens: int = 500,
        overlap_tokens: int = 80,
    ) -> None:
        self._chroma_path = Path(chroma_path)
        self._embed_model = embed_model
        self._collection_name = collection
        self._target = target_tokens
        self._overlap = overlap_tokens
        self._client = None
        self._col = None
        self._ready = False

    # ── Public API ────────────────────────────────────────────────────────────

    def ingest_directory(self, docs_dir: str | Path, reset: bool = False) -> IngestionStats:
        """Ingest all supported files from *docs_dir*."""
        t0 = time.monotonic()
        stats = IngestionStats()
        docs_path = Path(docs_dir)
        if not docs_path.exists():
            logger.warning("docs_dir not found: %s", docs_path)
            return stats
        if not self._init():
            stats.errors.append("RAG backend unavailable (install chromadb sentence-transformers)")
            return stats
        if reset:
            self._reset()
        files = [f for f in docs_path.rglob("*") if f.is_file() and f.suffix.lower() in self.SUPPORTED]
        
        # Process files in parallel to maximize CPU usage for chunking/cleaning
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_fp = {executor.submit(self._ingest_file, fp): fp for fp in files}
            for future in concurrent.futures.as_completed(future_to_fp):
                fp = future_to_fp[future]
                try:
                    n = future.result()
                    if n is None:
                        stats.files_skipped += 1
                    else:
                        stats.files_processed += 1
                        stats.chunks_added += n
                except Exception as exc:
                    stats.files_failed += 1
                    stats.errors.append(f"{fp.name}: {exc}")
                    logger.warning("ingest failed %s: %s", fp.name, exc)
                    
        stats.duration_seconds = time.monotonic() - t0
        logger.info("Ingestion: %s", stats)
        return stats

    def ingest_text(self, text: str, source_name: str, metadata: dict | None = None) -> int:
        """Ingest raw text directly. Returns chunk count."""
        if not self._init():
            return 0
        chunks = self._build_chunks(text, source_name, source_name, metadata or {})
        self._upsert(chunks)
        return len(chunks)

    def chunk_count(self) -> int:
        if not self._init():
            return 0
        try:
            return self._col.count()
        except Exception:
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
            emb = OllamaEmbed(self._embed_model)
            self._col = self._client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=emb,
                metadata={"hnsw:space": "cosine"},
            )
            self._ready = True
            logger.info("Ingester ready — collection=%s chunks=%d", self._collection_name, self._col.count())
            return True
        except ImportError:
            logger.warning("RAG deps missing. pip install chromadb sentence-transformers")
            return False
        except Exception as exc:
            logger.error("Ingester init failed: %s", exc)
            return False

    def _reset(self) -> None:
        try:
            self._client.delete_collection(self._collection_name)
            
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

            emb = OllamaEmbed(self._embed_model)
            self._col = self._client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=emb,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("Collection reset: %s", self._collection_name)
        except Exception as exc:
            logger.warning("Reset failed: %s", exc)

    def _ingest_file(self, fp: Path) -> int | None:
        fhash = _file_hash(fp)
        # Skip if hash matches existing
        try:
            existing = self._col.get(where={"file_hash": fhash}, limit=1)
            if existing["ids"]:
                logger.debug("Unchanged, skipping: %s", fp.name)
                return None
        except Exception:
            pass
        raw = _load_file(fp)
        cleaned = _clean_text(raw)
        if not cleaned:
            return 0
        # Remove stale chunks for this file
        try:
            old = self._col.get(where={"source_path": str(fp)}, limit=2000)
            if old["ids"]:
                self._col.delete(ids=old["ids"])
        except Exception:
            pass
        chunks = self._build_chunks(cleaned, str(fp), fp.stem, {"file_hash": fhash, "ext": fp.suffix.lower()})
        self._upsert(chunks)
        logger.info("Ingested %s → %d chunks", fp.name, len(chunks))
        return len(chunks)

    def _build_chunks(self, text: str, source_path: str, source_name: str, extra: dict) -> list[DocumentChunk]:
        raw = chunk_text(text, target=self._target, overlap=self._overlap)
        ts = str(int(time.time()))
        out: list[DocumentChunk] = []
        for i, t in enumerate(raw):
            out.append(DocumentChunk(
                chunk_id=_chunk_id(source_path, i),
                source_path=source_path,
                source_name=source_name,
                chunk_index=i,
                text=t,
                char_count=len(t),
                metadata={
                    "source_path": source_path,
                    "source_name": source_name,
                    "chunk_index": str(i),
                    "total_chunks": str(len(raw)),
                    "ingested_at": ts,
                    **{k: str(v) for k, v in extra.items()},
                },
            ))
        return out

    def _upsert(self, chunks: list[DocumentChunk]) -> None:
        if not chunks:
            return
        BATCH = 100
        for s in range(0, len(chunks), BATCH):
            b = chunks[s:s + BATCH]
            self._col.upsert(
                ids=[c.chunk_id for c in b],
                documents=[c.text for c in b],
                metadatas=[c.metadata for c in b],
            )
