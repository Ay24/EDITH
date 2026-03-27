from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from difflib import SequenceMatcher
import json
from pathlib import Path


@dataclass(slots=True)
class MemoryItem:
    timestamp: str
    command: str
    reply: str
    action: str


class MemoryService:
    def __init__(self, memory_path: str) -> None:
        self._path = Path(memory_path)
        self._items: list[MemoryItem] = []
        self._load()

    def remember(self, command: str, reply: str, action: str) -> None:
        item = MemoryItem(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            command=command,
            reply=reply,
            action=action,
        )
        self._items.append(item)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(item), ensure_ascii=True) + "\n")

    def similar(self, command: str, threshold: float = 0.8) -> MemoryItem | None:
        command = command.strip().lower()
        best_item = None
        best_score = threshold
        for item in reversed(self._items[-120:]):
            score = SequenceMatcher(None, command, item.command.lower()).ratio()
            if score > best_score and item.command.lower() != command:
                best_score = score
                best_item = item
        return best_item

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    self._items.append(MemoryItem(**data))
        except Exception:
            self._items = []
