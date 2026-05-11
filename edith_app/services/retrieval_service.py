from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Callable


@dataclass(slots=True)
class RetrievalChunk:
    chunk_id: str
    source_type: str
    source_id: str
    text: str
    metadata: dict[str, str]
    vector: list[float]


@dataclass(slots=True)
class RetrievalHit:
    score: float
    chunk: RetrievalChunk


class RetrievalService:
    def __init__(
        self,
        path: str,
        embedder: Callable[[str], list[float]] | None = None,
        max_chunks: int = 160,
    ) -> None:
        self._path = Path(path)
        self._embedder = embedder
        self._max_chunks = max(40, max_chunks)
        self._chunks: list[RetrievalChunk] = []
        self._load()

    def upsert_text(self, source_type: str, source_id: str, text: str, metadata: dict[str, str] | None = None) -> None:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return
        metadata = metadata or {}
        chunk_id = self._chunk_id(source_type, source_id)
        vector = self._embed(cleaned)
        chunk = RetrievalChunk(
            chunk_id=chunk_id,
            source_type=source_type,
            source_id=source_id,
            text=cleaned,
            metadata={key: str(value) for key, value in metadata.items()},
            vector=vector,
        )
        self._chunks = [item for item in self._chunks if item.chunk_id != chunk_id]
        self._chunks.append(chunk)
        self._trim()
        self._save()

    def upsert_document(self, source_type: str, source_id: str, text: str, metadata: dict[str, str] | None = None, chunk_size: int = 700) -> None:
        chunks = self._split_text(text, chunk_size=chunk_size)
        if not chunks:
            return
        prefix = self._chunk_id(source_type, source_id)
        self._chunks = [item for item in self._chunks if not item.chunk_id.startswith(prefix)]
        for index, chunk_text in enumerate(chunks, start=1):
            chunk_id = f"{prefix}:{index}"
            vector = self._embed(chunk_text)
            self._chunks.append(
                RetrievalChunk(
                    chunk_id=chunk_id,
                    source_type=source_type,
                    source_id=source_id,
                    text=chunk_text,
                    metadata={key: str(value) for key, value in (metadata or {}).items()},
                    vector=vector,
                )
            )
        self._trim()
        self._save()

    def search(self, query: str, limit: int = 4, source_types: set[str] | None = None) -> list[RetrievalHit]:
        cleaned = " ".join(query.strip().split())
        if not cleaned:
            return []
        query_vector = self._embed(cleaned)
        query_tokens = set(self._tokenize(cleaned))
        scored: list[RetrievalHit] = []
        for chunk in self._chunks:
            if source_types is not None and chunk.source_type not in source_types:
                continue
            lexical = self._lexical_score(query_tokens, chunk.text)
            semantic = self._cosine(query_vector, chunk.vector) if query_vector and chunk.vector else 0.0
            score = semantic * 0.72 + lexical * 0.28
            if score > 0.08:
                scored.append(RetrievalHit(score=score, chunk=chunk))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: max(1, min(limit, 12))]

    def summary(self, query: str, limit: int = 4, source_types: set[str] | None = None) -> list[str]:
        hits = self.search(query, limit=limit, source_types=source_types)
        lines = []
        for hit in hits:
            label = hit.chunk.metadata.get("label") or hit.chunk.source_id
            lines.append(f"{label} ({hit.chunk.source_type}, score={hit.score:.2f}): {hit.chunk.text}")
        return lines

    def _embed(self, text: str) -> list[float]:
        if self._embedder is not None:
            vector = self._embedder(text)
            if vector:
                return self._normalize(vector)
        return self._fallback_embed(text)

    def _fallback_embed(self, text: str) -> list[float]:
        dims = 64
        buckets = [0.0] * dims
        for token in self._tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = digest[0] % dims
            sign = -1.0 if digest[1] % 2 else 1.0
            buckets[index] += sign * (1.0 + (digest[2] / 255.0))
        return self._normalize(buckets)

    def _lexical_score(self, query_tokens: set[str], text: str) -> float:
        if not query_tokens:
            return 0.0
        doc_tokens = set(self._tokenize(text))
        if not doc_tokens:
            return 0.0
        overlap = len(query_tokens.intersection(doc_tokens))
        return overlap / max(1, len(query_tokens))

    def _cosine(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        return sum(a * b for a, b in zip(left, right))

    def _normalize(self, vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 0:
            return []
        return [float(value) / norm for value in vector]

    def _split_text(self, text: str, chunk_size: int) -> list[str]:
        cleaned = re.sub(r"\s+", " ", text.strip())
        if not cleaned:
            return []
        if len(cleaned) <= chunk_size:
            return [cleaned]
        chunks: list[str] = []
        start = 0
        step = max(200, chunk_size - 120)
        while start < len(cleaned):
            end = min(len(cleaned), start + chunk_size)
            if end < len(cleaned):
                split = cleaned.rfind(". ", start, end)
                if split > start + 120:
                    end = split + 1
            chunks.append(cleaned[start:end].strip())
            start += step
        return [chunk for chunk in chunks if chunk]

    def _tokenize(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]{3,}", text.lower())
        stop = {"this", "that", "with", "from", "have", "your", "about", "please", "edith", "assistant"}
        return [token for token in tokens if token not in stop]

    def _chunk_id(self, source_type: str, source_id: str) -> str:
        digest = hashlib.sha1(f"{source_type}:{source_id}".encode("utf-8")).hexdigest()[:12]
        return f"{source_type}:{digest}"

    def _trim(self) -> None:
        if len(self._chunks) > self._max_chunks:
            self._chunks = self._chunks[-self._max_chunks :]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(chunk) for chunk in self._chunks]
        self._path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            self._chunks = []
            return
        chunks: list[RetrievalChunk] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                chunk = RetrievalChunk(
                    chunk_id=str(item.get("chunk_id", "")),
                    source_type=str(item.get("source_type", "")),
                    source_id=str(item.get("source_id", "")),
                    text=str(item.get("text", "")),
                    metadata={str(key): str(value) for key, value in dict(item.get("metadata", {})).items()},
                    vector=[float(value) for value in item.get("vector", []) if isinstance(value, (int, float))],
                )
            except Exception:
                continue
            if chunk.chunk_id and chunk.text:
                chunks.append(chunk)
        self._chunks = chunks[-self._max_chunks :]
