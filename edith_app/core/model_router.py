from __future__ import annotations

from dataclasses import dataclass

from edith_app.config import AppConfig


@dataclass(slots=True)
class ModelDecision:
    model: str
    max_predict: int
    timeout_seconds: int
    temperature: float


class ModelRouter:
    """Lightweight model selector for EDITH Performance."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def select(self, task: str, prompt: str = "", lane: str = "chat") -> ModelDecision:
        lowered_task = task.lower().strip()
        prompt_words = len(prompt.split())

        # Intent parsing must be near-instant
        if lowered_task == "intent":
            return ModelDecision(
                model=self._config.fast_model,
                max_predict=72,
                timeout_seconds=90,
                temperature=0.1,
            )

        # Quick replies
        if lowered_task == "quick":
            return ModelDecision(
                model=self._config.fast_model,
                max_predict=96,
                timeout_seconds=90,
                temperature=0.3,
            )

        # Creative tasks
        if lowered_task == "creative" or lowered_task == "brainstorm":
            return ModelDecision(
                model=self._config.creative_model,
                max_predict=220,
                timeout_seconds=120,
                temperature=0.7,
            )

        # Planning and Cowork
        if lowered_task == "plan" or lane == "cowork":
            return ModelDecision(
                model=self._config.complex_model,
                max_predict=280,
                timeout_seconds=120,
                temperature=0.35,
            )

        # Default Chat
        if prompt_words < 15:
             return ModelDecision(
                model=self._config.fast_model,
                max_predict=80,
                timeout_seconds=90,
                temperature=0.4,
            )
            
        return ModelDecision(
            model=self._config.creative_model,
            max_predict=180,
            timeout_seconds=120,
            temperature=0.45,
        )
