from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Iterable, TypeVar


T = TypeVar("T")


@dataclass(slots=True)
class ExecutionTask:
    name: str
    fn: Callable[[], T]


class ExecutionEngine:
    """Small bounded executor for low-overhead parallel task fan-out."""

    def __init__(self, max_workers: int = 3) -> None:
        self._max_workers = max(1, min(max_workers, 4))

    def run_batch(self, tasks: Iterable[ExecutionTask]) -> list[T]:
        task_list = [task for task in tasks if task.fn is not None]
        if not task_list:
            return []
        if len(task_list) == 1:
            return [task_list[0].fn()]

        results: list[T] = []
        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(task_list))) as pool:
            futures = {pool.submit(task.fn): task.name for task in task_list}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception:
                    continue
        return results
