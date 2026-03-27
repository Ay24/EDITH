from __future__ import annotations

from typing import Iterable

import requests

from edith_app.config import AppConfig
from edith_app.models import ChatMessage


class AgentService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def enabled(self) -> bool:
        try:
            response = requests.get(f"{self._config.ollama_url}/api/tags", timeout=1.5)
            return response.ok
        except requests.RequestException:
            return False

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
        instruction = (
            "You are Edith's planning model. Break problems into clear steps, identify tradeoffs, "
            "and propose a practical path forward. Keep the plan punchy and compact."
        )
        return self._run_model(
            model=self._config.planner_model,
            prompt=prompt,
            history=history,
            system_instruction=instruction,
        )

    def brainstorm(self, prompt: str, history: Iterable[ChatMessage]) -> str:
        instruction = (
            "You are Edith's creative ideation model. Generate bold but practical ideas, alternatives, "
            "angles, and next experiments. Keep it lively but compact."
        )
        return self._run_model(
            model=self._config.creative_model,
            prompt=prompt,
            history=history,
            system_instruction=instruction,
        )

    def quick_think(self, prompt: str, history: Iterable[ChatMessage]) -> str:
        instruction = (
            "You are Edith's fast tactical model. Give a concise, decisive answer with the next best move."
        )
        return self._run_model(
            model=self._config.fast_model,
            prompt=prompt,
            history=history,
            system_instruction=instruction,
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
            response = requests.post(
                f"{self._config.ollama_url}/api/generate",
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip() or "The local model returned an empty response."
        except requests.RequestException as exc:
            return (
                "Local agent is unavailable. Install and run Ollama, then pull a model such as "
                f"'{model}'. Details: {exc}"
            )
