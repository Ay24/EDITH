from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path


@dataclass(slots=True)
class CoworkTask:
    created_at: str
    title: str
    status: str


class TaskQueue:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._tasks: list[CoworkTask] = []
        self._load()

    def add(self, title: str) -> CoworkTask:
        task = CoworkTask(
            created_at=datetime.now().isoformat(timespec="seconds"),
            title=title.strip(),
            status="pending",
        )
        self._tasks.append(task)
        self._save()
        return task

    def list(self) -> list[CoworkTask]:
        return list(self._tasks)

    def next_task(self) -> CoworkTask | None:
        for task in self._tasks:
            if task.status == "pending":
                return task
        return None

    def complete(self, title: str) -> CoworkTask | None:
        lowered = title.lower().strip()
        for task in self._tasks:
            if task.title.lower() == lowered or lowered in task.title.lower():
                task.status = "done"
                self._save()
                return task
        return None

    def clear_done(self) -> int:
        before = len(self._tasks)
        self._tasks = [task for task in self._tasks if task.status != "done"]
        self._save()
        return before - len(self._tasks)

    def summary(self) -> str:
        if not self._tasks:
            return "No cowork tasks queued yet."
        lines = [f"- [{task.status}] {task.title}" for task in self._tasks[:10]]
        return "Cowork queue:\n" + "\n".join(lines)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump([asdict(task) for task in self._tasks], handle, ensure_ascii=True, indent=2)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._tasks = [CoworkTask(**item) for item in data if isinstance(item, dict)]
        except Exception:
            self._tasks = []
