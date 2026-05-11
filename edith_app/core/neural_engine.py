from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from edith_app.config import AppConfig
from edith_app.models import ChatMessage


@dataclass(slots=True)
class RequestProfile:
    normalized: str
    complexity: str
    route: str
    use_fast_model: bool
    should_try_model_intent: bool
    should_try_model_intent_first: bool
    memory_limit: int
    history_limit: int
    observation_budget: int
    run_compile_check: bool


class NeuralEngine:
    """Lightweight perception/cognition coordinator for routing and context budgets."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def analyze(self, command: str, mode_hint: str = "") -> RequestProfile:
        normalized = " ".join(command.lower().strip().split())
        words = normalized.split()
        complexity = "simple"
        if len(words) >= 8 or any(token in normalized for token in ("because", "improve", "analyze", "optimize", "refactor", "architecture")):
            complexity = "medium"
        if len(words) >= 16 or mode_hint in {"workspace", "coding", "edit"}:
            complexity = "deep"

        action_tokens = {
            "open", "play", "search", "find", "organize", "analyse", "analyze", "set",
            "turn", "show", "check", "run", "move", "call", "message",
        }
        conversational = len(words) <= 10 and not any(token in action_tokens for token in words)
        route = "conversation" if conversational else "action"
        use_fast_model = complexity == "simple"

        direct_prefixes = (
            "show tasks", "task list", "next task", "complete task", "clear done tasks",
            "run preflight", "export debug bundle", "self improve", "set volume",
            "set brightness", "focus mode", "cowork mode", "analyze desktop",
            "analyze downloads", "organize desktop", "organize downloads", "open youtube",
            "open spotify", "open google", "open stack", "open whatsapp", "open settings",
            "wifi ", "bluetooth ", "message ", "send message to", "call ",
        )
        should_try_model_intent = (
            route == "action" and
            3 <= len(words) <= 30 and
            any(token in action_tokens or token in {"could", "can", "please", "help"} for token in words)
        )
        should_try_model_intent_first = should_try_model_intent and not normalized.startswith(direct_prefixes)

        run_compile_check = mode_hint in {"workspace", "coding", "edit"} or any(
            token in normalized for token in ("error", "bug", "crash", "traceback", "import", "compile", "syntax", "test", "failing")
        )

        memory_limit = 2 if complexity == "simple" else 4
        history_limit = 8 if complexity == "simple" else min(self._config.history_max_messages, 14 if complexity == "medium" else 18)
        observation_budget = max(4, min(self._config.cowork_observation_budget, 12))
        if complexity == "deep":
            observation_budget = min(12, observation_budget + 2)

        return RequestProfile(
            normalized=normalized,
            complexity=complexity,
            route=route,
            use_fast_model=use_fast_model,
            should_try_model_intent=should_try_model_intent,
            should_try_model_intent_first=should_try_model_intent_first,
            memory_limit=memory_limit,
            history_limit=history_limit,
            observation_budget=observation_budget,
            run_compile_check=run_compile_check,
        )

    def build_context_history(
        self,
        command: str,
        live_history: Iterable[ChatMessage],
        remembered_context: Iterable[ChatMessage],
    ) -> list[ChatMessage]:
        profile = self.analyze(command)
        remembered = list(remembered_context)[-profile.memory_limit * 2 :]
        recent_history = list(live_history)[-profile.history_limit :]
        merged = remembered + recent_history
        return merged[-self._config.history_max_messages :]

    def extract_keywords(self, text: str, limit: int = 4) -> list[str]:
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", text)
        if quoted:
            return [item.strip() for item in quoted[:limit] if item.strip()]
        words = [word.strip(".,:;!?()[]{}") for word in text.lower().split()]
        ranked: list[str] = []
        for word in words:
            if len(word) < 5 or word in ranked:
                continue
            ranked.append(word)
            if len(ranked) >= limit:
                break
        return ranked
