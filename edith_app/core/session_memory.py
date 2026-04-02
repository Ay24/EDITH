from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path


@dataclass(slots=True)
class SessionTask:
    timestamp: str
    goal: str
    plan: str
    summary: str
    mode: str


class SessionMemory:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._items: list[SessionTask] = []
        self._load()

    def add(self, goal: str, plan: str, summary: str, mode: str) -> None:
        item = SessionTask(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            goal=goal,
            plan=plan,
            summary=summary,
            mode=mode,
        )
        self._items.append(item)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump([asdict(entry) for entry in self._items[-80:]], handle, ensure_ascii=True, indent=2)

    def recent(self, limit: int = 5) -> list[SessionTask]:
        return self._items[-limit:]

    def relevant(self, goal: str, limit: int = 3) -> list[SessionTask]:
        lowered = goal.lower().strip()
        scored: list[tuple[int, SessionTask]] = []
        for item in reversed(self._items):
            score = 0
            for token in lowered.split():
                if len(token) >= 4 and token in item.goal.lower():
                    score += 1
            if score:
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
