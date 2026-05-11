from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path


@dataclass(slots=True)
class PersonalTask:
    created_at: str
    title: str
    status: str


@dataclass(slots=True)
class Routine:
    name: str
    steps: list[str]
    created_at: str


class PersonalAssistantService:
    def __init__(self, tasks_path: str, routines_path: str) -> None:
        self._tasks_path = Path(tasks_path)
        self._routines_path = Path(routines_path)
        self._tasks: list[PersonalTask] = []
        self._routines: list[Routine] = []
        self._load()
        self._seed_defaults()

    def add_task(self, title: str) -> str:
        cleaned = title.strip()
        if not cleaned:
            return "I need a task title."
        task = PersonalTask(
            created_at=datetime.now().isoformat(timespec="seconds"),
            title=cleaned,
            status="pending",
        )
        self._tasks.append(task)
        self._save_tasks()
        return f"Added personal task: {task.title}."

    def list_tasks(self) -> str:
        if not self._tasks:
            return "No personal tasks saved yet."
        lines = [f"- [{task.status}] {task.title}" for task in self._tasks[:12]]
        return "Personal tasks:\n" + "\n".join(lines)

    def complete_task(self, title: str) -> str:
        lowered = title.lower().strip()
        for task in self._tasks:
            if task.title.lower() == lowered or lowered in task.title.lower():
                task.status = "done"
                self._save_tasks()
                return f"Completed personal task: {task.title}."
        return f"I couldn't find a personal task matching {title}."

    def next_task(self) -> str:
        for task in self._tasks:
            if task.status == "pending":
                return f"Next personal task: {task.title}."
        return "No pending personal tasks right now."

    def add_routine(self, name: str, steps: list[str]) -> str:
        cleaned_name = name.strip().lower()
        normalized_steps = [step.strip() for step in steps if step.strip()]
        if not cleaned_name or not normalized_steps:
            return "I need a routine name and at least one step."
        routine = Routine(
            name=cleaned_name,
            steps=normalized_steps,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._routines = [item for item in self._routines if item.name != cleaned_name]
        self._routines.append(routine)
        self._save_routines()
        return f"Saved routine '{cleaned_name}' with {len(normalized_steps)} step{'s' if len(normalized_steps) != 1 else ''}."

    def list_routines(self) -> str:
        if not self._routines:
            return "No routines saved yet."
        lines = [f"- {routine.name}: {', '.join(routine.steps[:3])}" for routine in self._routines[:12]]
        return "Routines:\n" + "\n".join(lines)

    def get_routine_steps(self, name: str) -> list[str]:
        cleaned = name.strip().lower()
        for routine in self._routines:
            if routine.name == cleaned or cleaned in routine.name:
                return list(routine.steps)
        return []

    def describe_routine(self, name: str) -> str:
        steps = self.get_routine_steps(name)
        if not steps:
            return f"I couldn't find a routine named {name}."
        lines = [f"{index}. {step}" for index, step in enumerate(steps, start=1)]
        return f"Routine {name.strip().lower()}:\n" + "\n".join(lines)

    def _seed_defaults(self) -> None:
        if self._routines:
            return
        now = datetime.now().isoformat(timespec="seconds")
        self._routines = [
            Routine(name="focus", steps=["open spotify", "spotify playlist deep focus"], created_at=now),
            Routine(name="research", steps=["search_web latest breakthroughs in artificial intelligence", "open_target notepad"], created_at=now),
            Routine(name="coding", steps=["open_target github", "open_target stackoverflow", "spotify playlist coding"], created_at=now),
        ]
        self._save_routines()

    def _save_tasks(self) -> None:
        self._tasks_path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks_path.write_text(json.dumps([asdict(task) for task in self._tasks], ensure_ascii=True, indent=2), encoding="utf-8")

    def _save_routines(self) -> None:
        self._routines_path.parent.mkdir(parents=True, exist_ok=True)
        self._routines_path.write_text(json.dumps([asdict(routine) for routine in self._routines], ensure_ascii=True, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if self._tasks_path.exists():
            try:
                data = json.loads(self._tasks_path.read_text(encoding="utf-8"))
                self._tasks = [PersonalTask(**item) for item in data if isinstance(item, dict)]
            except Exception:
                self._tasks = []
        if self._routines_path.exists():
            try:
                data = json.loads(self._routines_path.read_text(encoding="utf-8"))
                self._routines = [Routine(**item) for item in data if isinstance(item, dict)]
            except Exception:
                self._routines = []
