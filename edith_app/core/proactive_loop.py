from __future__ import annotations

import threading
import time
from typing import Callable, TYPE_CHECKING

from edith_app.core.task_queue import TaskQueue

if TYPE_CHECKING:
    from edith_app.core.task_engine import TaskEngine


class ProactiveLoop:
    """Low-frequency background awareness thread for task analysis."""

    def __init__(
        self,
        task_queue: TaskQueue,
        on_suggestion: Callable[[str], None],
        task_manager: "TaskEngine | None" = None,
        interval_seconds: int = 600,
        initial_delay_seconds: int = 30,
    ):
        self._task_queue = task_queue
        self._task_manager = task_manager
        self._on_suggestion = on_suggestion
        self._is_running = False
        self._thread: threading.Thread | None = None
        self._interval_seconds = max(120, int(interval_seconds))
        self._initial_delay_seconds = max(5, int(initial_delay_seconds))
        self._last_suggestion: str = ""

    def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._is_running = False

    def _loop(self) -> None:
        time.sleep(self._initial_delay_seconds)
        while self._is_running:
            try:
                self._analyze_current_state()
            except Exception:
                pass
            time.sleep(self._interval_seconds)

    def _surface(self, msg: str) -> None:
        if msg != self._last_suggestion:
            self._last_suggestion = msg
            self._on_suggestion(msg)

    def _analyze_current_state(self) -> None:
        # 1. Check TaskEngine for overdue tasks first (highest urgency)
        if self._task_manager:
            overdue = self._task_manager.overdue()
            if overdue:
                self._surface(f"⚠️ {len(overdue)} overdue task(s)! Oldest: '{overdue[0].title}'")
                return
            next_t = self._task_manager.next_task()
            if next_t:
                self._surface(f"Next high-priority task: '{next_t.title}' [{next_t.priority}]. Say 'show tasks' for full list.")
                return

        # 2. Fall back to cowork queue
        pending = self._task_queue.next_task()
        if pending:
            self._surface(f"Cowork task pending: '{pending.title}'. Shall I prioritize it?")
