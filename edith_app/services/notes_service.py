from __future__ import annotations

from datetime import datetime


class NotesService:
    def __init__(self, path: str) -> None:
        self._path = path

    def save(self, text: str) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {text}\n")
        return f"Saved note to {self._path}."
