"""
task_storage.py  —  Persistent JSON storage for the full task system.
Keeps tasks in a separate file from the existing cowork_tasks.json.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("edith.task_storage")


class TaskStorage:
    """Thread-safe JSON persistence for Task objects."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> list:
        from edith_app.core.task_engine import Task  # avoid circular import
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            tasks = []
            for item in raw:
                if isinstance(item, dict):
                    try:
                        tasks.append(Task.from_dict(item))
                    except Exception as e:
                        logger.warning("Skipping corrupt task record: %s", e)
            return tasks
        except Exception as e:
            logger.error("Failed to load tasks from %s: %s", self._path, e)
            return []

    def save_all(self, tasks: list) -> None:
        try:
            data = [t.to_dict() for t in tasks]
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to save tasks: %s", e)

    def backup(self) -> None:
        if self._path.exists():
            backup_path = self._path.with_suffix(".bak.json")
            backup_path.write_bytes(self._path.read_bytes())
