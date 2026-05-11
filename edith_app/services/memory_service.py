from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from difflib import SequenceMatcher
import json
from pathlib import Path
from collections import deque
import math
import re


@dataclass(slots=True)
class MemoryItem:
    timestamp: str
    command: str
    reply: str
    action: str


class MemoryService:
    def __init__(self, memory_path: str, max_items: int = 100000) -> None:
        self._path = Path(memory_path)
        self._max_items = max_items # Infinite rolling archive for true long-term memory
        self._items: list[MemoryItem] = []
        self._semantic_docs: list[dict[str, float]] = []
        self._idf: dict[str, float] = {}
        self._load()
        self._rebuild_semantic_index()

    def remember(self, command: str, reply: str, action: str) -> None:
        item = MemoryItem(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            command=command,
            reply=reply,
            action=action,
        )
        self._items.append(item)
        if len(self._items) > self._max_items:
            self._items = self._items[-self._max_items :]
        self._rebuild_semantic_index()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(item), ensure_ascii=True) + "\n")

    def similar(self, command: str, threshold: float = 0.8) -> MemoryItem | None:
        command = command.strip().lower()
        best_item = None
        best_score = threshold
        command_tokens = set(command.split())
        semantic_query = self._semantic_vector(command)
        for index, item in reversed(list(enumerate(self._items[-120:], start=max(0, len(self._items) - min(len(self._items), 120))))):
            candidate = item.command.lower()
            token_hits = len(command_tokens.intersection(candidate.split()))
            lexical = SequenceMatcher(None, command, candidate).ratio() + min(0.15, token_hits * 0.05)
            semantic = self._semantic_similarity(semantic_query, self._semantic_docs[index]) if index < len(self._semantic_docs) else 0.0
            score = lexical * 0.7 + semantic * 0.3
            if score > best_score and item.command.lower() != command:
                best_score = score
                best_item = item
        return best_item

    def relevant(self, command: str, limit: int = 4, threshold: float = 0.45) -> list[MemoryItem]:
        command = command.strip().lower()
        scored: list[tuple[float, MemoryItem]] = []
        command_tokens = set(command.split())
        semantic_query = self._semantic_vector(command)
        window_start = max(0, len(self._items) - 160)
        for index, item in reversed(list(enumerate(self._items[window_start:], start=window_start))):
            candidate = item.command.lower()
            token_hits = len(command_tokens.intersection(candidate.split()))
            lexical = SequenceMatcher(None, command, candidate).ratio() + min(0.2, token_hits * 0.06)
            semantic = self._semantic_similarity(semantic_query, self._semantic_docs[index]) if index < len(self._semantic_docs) else 0.0
            score = lexical * 0.55 + semantic * 0.45
            if score >= threshold:
                scored.append((score, item))
        scored.sort(key=lambda entry: entry[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def recent(self, limit: int = 8, include_actions: set[str] | None = None) -> list[MemoryItem]:
        if include_actions is None:
            return self._items[-limit:]
        return [item for item in self._items if item.action in include_actions][-limit:]

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                for line in deque(handle, maxlen=self._max_items):
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    self._items.append(MemoryItem(**data))
        except Exception:
            self._items = []

    def _rewrite_compacted(self) -> None:
        try:
            with self._path.open("w", encoding="utf-8") as handle:
                for item in self._items[-self._max_items :]:
                    handle.write(json.dumps(asdict(item), ensure_ascii=True) + "\n")
        except Exception:
            pass

    def _rebuild_semantic_index(self) -> None:
        docs = [self._token_counts(f"{item.command} {item.reply}") for item in self._items]
        doc_freq: dict[str, int] = {}
        for doc in docs:
            for token in doc:
                doc_freq[token] = doc_freq.get(token, 0) + 1
        total_docs = max(1, len(docs))
        self._idf = {
            token: math.log(1.0 + total_docs / freq)
            for token, freq in doc_freq.items()
            if freq > 0
        }
        self._semantic_docs = [self._normalize_tfidf(doc) for doc in docs]

    def _semantic_vector(self, text: str) -> dict[str, float]:
        return self._normalize_tfidf(self._token_counts(text))

    def _semantic_similarity(self, left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        if len(left) > len(right):
            left, right = right, left
        return sum(weight * right.get(token, 0.0) for token, weight in left.items())

    def _normalize_tfidf(self, counts: dict[str, int]) -> dict[str, float]:
        weighted: dict[str, float] = {}
        for token, count in counts.items():
            idf = self._idf.get(token, 1.0)
            weighted[token] = float(count) * idf
        norm = math.sqrt(sum(value * value for value in weighted.values()))
        if norm <= 0:
            return {}
        return {token: value / norm for token, value in weighted.items()}

    def _token_counts(self, text: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for token in self._tokenize(text):
            counts[token] = counts.get(token, 0) + 1
        return counts

    def _tokenize(self, text: str) -> list[str]:
        cleaned = re.findall(r"[a-z0-9]{3,}", text.lower())
        stop = {
            "this", "that", "with", "have", "from", "your", "what", "when", "where",
            "would", "could", "should", "about", "please", "edith", "assistant",
        }
        return [token for token in cleaned if token not in stop]
