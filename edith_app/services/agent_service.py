from __future__ import annotations

import os
import shutil
import subprocess
import threading
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
        self._recovery_lock = threading.Lock()
        self._recovery_state: dict[str, float] = {}

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
            self._recover_async(model)
            return "Ollama is starting up. Keep Edith open for a moment and try again."
        target_model = model
        if not self._model_available(target_model):
            self._recover_async(model)
            return f"I am preparing the local model '{model}'. Keep Edith open and I will use it as soon as it finishes loading."

        transcript = [system_instruction]
        for item in list(history)[-10:]:
            transcript.append(f"{item.source.title()}: {item.text}")
        transcript.append(f"User: {prompt}")

        payload = {
            "model": target_model,
            "prompt": "\n".join(transcript) + "\nAssistant:",
            "stream": False,
            "keep_alive": "10m",
        }

        for attempt in range(2):
            try:
                response = self._session.post(
                    f"{self._config.ollama_url}/api/generate",
                    json=payload,
                    timeout=60,
                )
                if response.status_code >= 500:
                    if attempt == 0:
                        time.sleep(1.0)
                        continue
                    self._recover_async(model)
                    return f"The local model '{model}' is still warming up or hit an internal Ollama error. Give it a moment and try again."
                response.raise_for_status()
                data = response.json()
                return data.get("response", "").strip() or "The local model returned an empty response."
            except requests.RequestException:
                if attempt == 0:
                    time.sleep(0.8)
                    continue
                self._recover_async(model)
                return f"I couldn't reach the local model '{model}' just now. Edith is still trying to bring Ollama online."
        self._recover_async(model)
        return f"The local model '{model}' is still warming up. Try again in a moment."

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
        if now - cached_at < 10.0:
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

    def _recover_async(self, model: str) -> None:
        now = time.monotonic()
        with self._recovery_lock:
            last = self._recovery_state.get(model, 0.0)
            if now - last < 20.0:
                return
            self._recovery_state[model] = now
        thread = threading.Thread(target=self._recover_model_runtime, args=(model,), daemon=True)
        thread.start()

    def _recover_model_runtime(self, model: str) -> None:
        executable = shutil.which(self._config.ollama_executable) or self._config.ollama_executable
        if not executable:
            return
        if not self._server_ready():
            self._start_server(executable)
            self._wait_for_server()
        if not self._server_ready():
            return
        if not self._model_available(model):
            self._pull_model(executable, model)
            self._tags_cache = (0.0, set())
        self._warm_model(model)

    def _start_server(self, executable: str) -> None:
        try:
            subprocess.Popen([executable, "serve"], env=self._ollama_env())
        except Exception:
            pass

    def _wait_for_server(self, attempts: int = 12, delay: float = 1.0) -> None:
        for _ in range(attempts):
            if self._server_ready():
                return
            time.sleep(delay)

    def _pull_model(self, executable: str, model: str) -> None:
        try:
            subprocess.run(
                [executable, "pull", model],
                capture_output=True,
                text=True,
                timeout=900,
                env=self._ollama_env(),
            )
        except Exception:
            pass

    def _warm_model(self, model: str) -> None:
        try:
            self._session.post(
                f"{self._config.ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": "Respond with one word: ready.",
                    "stream": False,
                    "keep_alive": "10m",
                },
                timeout=45,
            )
        except requests.RequestException:
            pass

    def _ollama_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self._config.ollama_models_path:
            env["OLLAMA_MODELS"] = self._config.ollama_models_path
        return env
