"""
task_engine.py  —  EDITH Full Task Management Engine
Extends (not replaces) the existing TaskQueue. All new capabilities are additive.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, date
from typing import Literal

Status   = Literal["pending", "in_progress", "completed", "cancelled"]
Priority = Literal["low", "medium", "high"]

PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
STATUS_EMOJI   = {"pending": "⏳", "in_progress": "⚙️", "completed": "✅", "cancelled": "❌"}


@dataclass
class Task:
    id: str
    title: str
    description: str
    status: Status
    priority: Priority
    created_at: str
    due_date: str | None = None
    completed_at: str | None = None
    context: str = ""
    notes: str = ""
    related_files: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        data.setdefault("notes", "")
        data.setdefault("context", "")
        data.setdefault("related_files", [])
        data.setdefault("tags", [])
        data.setdefault("completed_at", None)
        return cls(**data)

    def summary_line(self) -> str:
        pe = PRIORITY_EMOJI.get(self.priority, "")
        se = STATUS_EMOJI.get(self.status, "")
        due = f" | Due: {self.due_date}" if self.due_date else ""
        return f"{se} {pe} [{self.status.upper()}] {self.title}{due}"

    def is_overdue(self) -> bool:
        if not self.due_date or self.status in ("completed", "cancelled"):
            return False
        try:
            return date.fromisoformat(self.due_date) < date.today()
        except ValueError:
            return False


class TaskEngine:
    """Full-featured task management engine — additive on top of TaskQueue."""

    def __init__(self, storage: "TaskStorage") -> None:
        self._storage = storage
        self._tasks: list[Task] = storage.load_all()

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create(
        self,
        title: str,
        description: str = "",
        priority: Priority = "medium",
        due_date: str | None = None,
        context: str = "",
        tags: list[str] | None = None,
    ) -> Task:
        task = Task(
            id=str(uuid.uuid4())[:8],
            title=title.strip(),
            description=description.strip(),
            status="pending",
            priority=priority,
            created_at=datetime.now().isoformat(timespec="seconds"),
            due_date=due_date,
            context=context,
            tags=tags or [],
        )
        self._tasks.append(task)
        self._save()
        return task

    def get(self, task_id_or_title: str) -> Task | None:
        lowered = task_id_or_title.lower().strip()
        for t in self._tasks:
            if t.id == lowered or lowered in t.title.lower():
                return t
        return None

    def update_status(self, task_id_or_title: str, status: Status) -> Task | None:
        task = self.get(task_id_or_title)
        if task:
            task.status = status
            if status == "completed":
                task.completed_at = datetime.now().isoformat(timespec="seconds")
            self._save()
        return task

    def add_note(self, task_id_or_title: str, note: str) -> Task | None:
        task = self.get(task_id_or_title)
        if task:
            stamp = datetime.now().strftime("%H:%M")
            task.notes = f"{task.notes}\n[{stamp}] {note}".strip()
            self._save()
        return task

    def delete(self, task_id_or_title: str) -> bool:
        task = self.get(task_id_or_title)
        if task:
            self._tasks = [t for t in self._tasks if t.id != task.id]
            self._save()
            return True
        return False

    # ── QUERIES ───────────────────────────────────────────────────────────────

    def all(self) -> list[Task]:
        return list(self._tasks)

    def by_status(self, status: Status) -> list[Task]:
        return [t for t in self._tasks if t.status == status]

    def by_priority(self, priority: Priority) -> list[Task]:
        return [t for t in self._tasks if t.priority == priority]

    def overdue(self) -> list[Task]:
        return [t for t in self._tasks if t.is_overdue()]

    def next_task(self) -> Task | None:
        """Return the highest-priority pending task."""
        order = {"high": 0, "medium": 1, "low": 2}
        pending = [t for t in self._tasks if t.status == "pending"]
        if not pending:
            return None
        pending.sort(key=lambda t: (order.get(t.priority, 3), t.created_at))
        return pending[0]

    def pending_count(self) -> int:
        return sum(1 for t in self._tasks if t.status == "pending")

    def completed_count(self) -> int:
        return sum(1 for t in self._tasks if t.status == "completed")

    # ── SUMMARIES ─────────────────────────────────────────────────────────────

    def dashboard_text(self) -> str:
        if not self._tasks:
            return "No tasks yet. Speak or type a goal to auto-create one."
        high   = [t for t in self._tasks if t.priority == "high" and t.status != "completed"]
        mid    = [t for t in self._tasks if t.priority == "medium" and t.status != "completed"]
        low    = [t for t in self._tasks if t.priority == "low"    and t.status != "completed"]
        done   = [t for t in self._tasks if t.status == "completed"]
        over   = self.overdue()
        lines  = []
        if over: lines.append(f"⚠️  OVERDUE ({len(over)}): " + ", ".join(t.title[:30] for t in over[:3]))
        if high: lines += [t.summary_line() for t in high[:3]]
        if mid:  lines += [t.summary_line() for t in mid[:3]]
        if low:  lines += [t.summary_line() for t in low[:2]]
        lines.append(f"\n✅ Completed: {len(done)} | ⏳ Pending: {self.pending_count()}")
        return "\n".join(lines)

    def cowork_summary(self) -> str:
        """Brief text suitable for the Cowork Pipeline card."""
        pending = self.by_status("pending")
        if not pending:
            return "All tasks complete. Ready for next mission."
        lines = [t.summary_line() for t in pending[:6]]
        return "\n".join(lines)

    # ── PERSISTENCE ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        self._storage.save_all(self._tasks)
