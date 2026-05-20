from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from edith_app.core.task_queue import TaskQueue
    from edith_app.core.session_memory import SessionMemory
    from edith_app.config import AppConfig

class ContextEngine:
    """Assembles situational awareness context for EDITH's brain."""

    def __init__(self, config: AppConfig, task_queue: TaskQueue, session_memory: SessionMemory):
        self._config = config
        self._task_queue = task_queue
        self._session_memory = session_memory

    def get_situation(self) -> str:
        now = datetime.now()
        timestamp = now.strftime("%I:%M %p, %A, %d %B %Y")
        
        # 1. System state
        parts = [
            f"Current Time: {timestamp}",
            f"Assistant Mode: EDITH ORBIT (local, full capability)",
            f"Workspace Root: {self._config.project_root.name}",
        ]
        
        # 2. Active Tasks (Proactive)
        active_task = self._task_queue.next_task()
        if active_task:
            parts.append(f"Active Cowork Task: {active_task.title} (Status: {active_task.status})")
        else:
            parts.append("No active cowork tasks. Standing by for instructions.")
            
        # 3. Contextual Memory Snippets
        recent = self._session_memory.recent(limit=3)
        if recent:
            memory_block = "Recent Highlights:\n"
            for item in recent:
                 memory_block += f"- [{item.mode}] {item.goal}: {item.summary[:100]}...\n"
            parts.append(memory_block)
            
        return "\n".join(parts)

    def contextualize_prompt(self, system_instruction: str, prompt: str) -> str:
        situation = self.get_situation()
        return (
            f"{system_instruction}\n\n"
            "## SITUATIONAL AWARENESS\n"
            f"{situation}\n\n"
            "## USER INPUT\n"
            f"{prompt}\n\n"
            "Respond naturally as Jarvis, keeping situational context in mind."
        )
