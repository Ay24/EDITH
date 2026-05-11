from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import re


@dataclass(slots=True)
class SessionTask:
    timestamp: str
    goal: str
    plan: str
    summary: str
    mode: str


class SessionMemory:
    def __init__(self, path: str, max_items: int = 80) -> None:
        self._path = Path(path)
        self._max_items = max(20, max_items)
        self._items: list[SessionTask] = []
        self._semantic_docs: list[dict[str, float]] = []
        self._idf: dict[str, float] = {}
        self._load()
        self._rebuild_semantic_index()

    def add(self, goal: str, plan: str, summary: str, mode: str) -> None:
        item = SessionTask(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            goal=goal,
            plan=plan,
            summary=summary,
            mode=mode,
        )
        self._items.append(item)
        if len(self._items) > self._max_items:
            self._items = self._items[-self._max_items :]
        self._rebuild_semantic_index()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump([asdict(entry) for entry in self._items[-self._max_items :]], handle, ensure_ascii=True, indent=2)

    def recent(self, limit: int = 5) -> list[SessionTask]:
        return self._items[-limit:]

    def relevant(self, goal: str, limit: int = 3) -> list[SessionTask]:
        lowered = goal.lower().strip()
        scored: list[tuple[float, SessionTask]] = []
        query_tokens = {token for token in lowered.split() if len(token) >= 4}
        semantic_query = self._semantic_vector(lowered)
        for index, item in reversed(list(enumerate(self._items))):
            lexical = 0.0
            for token in query_tokens:
                if token in item.goal.lower():
                    lexical += 1.0
            semantic = self._semantic_similarity(semantic_query, self._semantic_docs[index]) if index < len(self._semantic_docs) else 0.0
            score = lexical * 0.6 + semantic * 2.4
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda entry: entry[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._items = [SessionTask(**item) for item in data if isinstance(item, dict)]
        except Exception:
            self._items = []

    def _rebuild_semantic_index(self) -> None:
        docs = [self._token_counts(f"{item.goal} {item.plan} {item.summary}") for item in self._items]
        doc_freq: dict[str, int] = {}
        for doc in docs:
            for token in doc:
                doc_freq[token] = doc_freq.get(token, 0) + 1
        total_docs = max(1, len(docs))
        self._idf = {token: math.log(1.0 + total_docs / freq) for token, freq in doc_freq.items() if freq > 0}
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
            weighted[token] = float(count) * self._idf.get(token, 1.0)
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
        stop = {"this", "that", "with", "have", "from", "your", "about", "please", "edith"}
        return [token for token in cleaned if token not in stop]
