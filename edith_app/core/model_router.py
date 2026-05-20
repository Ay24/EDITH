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
    """Lightweight model selector tuned for native 3B inference."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def select(self, task: str, prompt: str = "", lane: str = "chat") -> ModelDecision:
        lowered_task = task.lower().strip()
        prompt_words = len(prompt.split())

        # Intent parsing — must be near-instant, minimal tokens
        if lowered_task == "intent":
            return ModelDecision(
                model=self._config.fast_model,
                max_predict=64,
                timeout_seconds=12,
                temperature=0.1,
            )

        # ReAct tool-calling loop steps — fast, decisive
        if lowered_task == "quick":
            return ModelDecision(
                model=self._config.fast_model,
                max_predict=96,
                timeout_seconds=18,
                temperature=0.25,
            )

        # Creative tasks
        if lowered_task in ("creative", "brainstorm"):
            return ModelDecision(
                model=self._config.creative_model,
                max_predict=200,
                timeout_seconds=35,
                temperature=0.7,
            )

        # Planning and Cowork
        if lowered_task == "plan" or lane == "cowork":
            return ModelDecision(
                model=self._config.complex_model,
                max_predict=260,
                timeout_seconds=40,
                temperature=0.35,
            )

        # NLP voice correction — must never lag
        if lowered_task == "nlp_correct":
            return ModelDecision(
                model=self._config.fast_model,
                max_predict=80,
                timeout_seconds=10,
                temperature=0.0,
            )

        # Default Chat — short prompt, fast path
        if prompt_words < 15:
            return ModelDecision(
                model=self._config.fast_model,
                max_predict=160,
                timeout_seconds=20,
                temperature=0.4,
            )

        # Default Chat — longer prompt
        return ModelDecision(
            model=self._config.creative_model,
            max_predict=200,
            timeout_seconds=28,
            temperature=0.45,
        )
