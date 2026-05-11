from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from edith_app.core.classifier import CommandClassifier
from edith_app.core.context_engine import ContextEngine
from edith_app.core.async_wrapper import AsyncWrapper
from edith_app.core.proactive_loop import ProactiveLoop

if TYPE_CHECKING:
    from edith_app.config import AppConfig
    from edith_app.core.task_queue import TaskQueue
    from edith_app.core.session_memory import SessionMemory

class JarvisBrain:
    """Orchestrator for the elite JARVIS evolution layers."""

    def __init__(self, config: AppConfig, task_queue: TaskQueue, session_memory: SessionMemory):
        self._config = config
        self.logger = logging.getLogger("edith.brain")
        self.classifier = CommandClassifier()
        self.context = ContextEngine(config, task_queue, session_memory)
        self.proactive = ProactiveLoop(task_queue, self._handle_suggestion)
        self.async_exec = AsyncWrapper()
        self._suggestion_callback: Callable[[str], None] | None = None

    def start(self, suggestion_callback: Callable[[str], None], task_manager=None) -> None:
        self._suggestion_callback = suggestion_callback
        if task_manager is not None:
            self.proactive._task_manager = task_manager
        self.proactive.start()

    def _handle_suggestion(self, text: str) -> None:
        if self._suggestion_callback:
            self._suggestion_callback(text)

    def classify_intent(self, command: str) -> str:
        try:
            intent = self.classifier.classify(command)
            self.logger.info("Jarvis classified intent: %s (conf: %.2f)", intent.lane, intent.confidence)
            return intent.lane
        except Exception:
            self.logger.error("Jarvis classifier failed, falling back to legacy")
            return "chat"

    def assemble_context(self, system_instruction: str, prompt: str) -> str:
        try:
            return self.context.contextualize_prompt(system_instruction, prompt)
        except Exception as e:
            self.logger.error("Jarvis context engine failed, falling back to basic prompt", exc_info=True)
            return f"{system_instruction}\n\nUSER: {prompt}"
