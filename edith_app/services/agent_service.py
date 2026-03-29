from __future__ import annotations

import time
from typing import Iterable

import requests

from edith_app.config import AppConfig
from edith_app.models import ChatMessage


class AgentService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session = requests.Session()
        self._tags_cache: tuple[float, set[str]] = (0.0, set())

    @property
    def enabled(self) -> bool:
        return self._model_available(self._config.ollama_model)

    def reply(self, prompt: str, history: Iterable[ChatMessage]) -> str:
        return self._run_model(
            model=self._config.ollama_model,
            prompt=prompt,
            history=history,
            system_instruction=(
                f"{self._config.persona.system_prompt} "
                "Default to crisp, direct responses. Usually keep it to 2 to 4 short sentences."
            ),
        )

    def plan(self, prompt: str, history: Iterable[ChatMessage]) -> str:
        return self._run_model(
            model=self._config.planner_model,
            prompt=prompt,
            history=history,
            system_instruction=(
                "You are Edith's planning model. Break problems into clear steps, identify tradeoffs, "
                "and propose a practical path forward. Keep the plan punchy and compact."
            ),
        )

    def brainstorm(self, prompt: str, history: Iterable[ChatMessage]) -> str:
        return self._run_model(
            model=self._config.creative_model,
            prompt=prompt,
            history=history,
            system_instruction=(
                "You are Edith's creative ideation model. Generate bold but practical ideas, alternatives, "
                "angles, and next experiments. Keep it lively but compact."
            ),
        )

    def quick_think(self, prompt: str, history: Iterable[ChatMessage]) -> str:
        return self._run_model(
            model=self._config.fast_model,
            prompt=prompt,
            history=history,
            system_instruction=(
                "You are Edith's fast tactical model. Give a concise, decisive answer with the next best move."
            ),
        )

    def think_with_user(self, prompt: str, history: Iterable[ChatMessage]) -> str:
        planner = self.plan(prompt, history)
        creative = self.brainstorm(prompt, history)
        tactical = self.quick_think(prompt, history)
        return (
            "Planner view:\n"
            f"{planner}\n\n"
            "Creative view:\n"
            f"{creative}\n\n"
            "Tactical view:\n"
            f"{tactical}"
        )

    def _run_model(
        self,
        model: str,
        prompt: str,
        history: Iterable[ChatMessage],
        system_instruction: str,
    ) -> str:
        if not self._server_ready():
            return "Ollama is starting up. Keep Edith open for a moment and try again."
        if not self._model_available(model):
            return f"I am preparing the local model '{model}'. Keep Edith open and I will use it as soon as it finishes loading."

        transcript = [system_instruction]
        for item in list(history)[-10:]:
            transcript.append(f"{item.source.title()}: {item.text}")
        transcript.append(f"User: {prompt}")

        payload = {
            "model": model,
            "prompt": "\n".join(transcript) + "\nAssistant:",
            "stream": False,
        }

        try:
            response = self._session.post(
                f"{self._config.ollama_url}/api/generate",
                json=payload,
                timeout=60,
            )
            if response.status_code >= 500:
                return f"The local model '{model}' is still warming up or hit an internal Ollama error. Give it a moment and try again."
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip() or "The local model returned an empty response."
        except requests.RequestException:
            return f"I couldn't reach the local model '{model}' just now. Edith is still trying to bring Ollama online."

    def _server_ready(self) -> bool:
        try:
            response = self._session.get(f"{self._config.ollama_url}/api/tags", timeout=1.5)
            return response.ok
        except requests.RequestException:
            return False

    def _model_available(self, model: str) -> bool:
        names = self._available_models()
        return model in names

    def _available_models(self) -> set[str]:
        now = time.monotonic()
        cached_at, cached_names = self._tags_cache
        if now - cached_at < 3.0 and cached_names:
            return cached_names
        try:
            response = self._session.get(f"{self._config.ollama_url}/api/tags", timeout=2)
            response.raise_for_status()
            data = response.json()
            names = set()
            for item in data.get("models", []):
                name = item.get("name", "")
                if not name:
                    continue
                names.add(name)
                names.add(name.split(":", 1)[0])
            self._tags_cache = (now, names)
            return names
        except requests.RequestException:
            return set()
