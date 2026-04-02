from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

import requests

from edith_app.config import AppConfig


class BootstrapService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def start_async(self) -> None:
        thread = threading.Thread(target=self._prepare_ollama, daemon=True)
        thread.start()

    def _prepare_ollama(self) -> None:
        self._ensure_runtime_dirs()
        executable = shutil.which(self._config.ollama_executable) or self._config.ollama_executable
        if not executable:
            return

        if not self._is_server_ready():
            self._start_server(executable)
            self._wait_for_server()

        if not self._is_server_ready():
            return

        available = self._available_models()
        if not self._config.auto_pull_models:
            return

        for model in self._required_models():
            if model not in available:
                self._pull_model(executable, model)
        self._warm_models()

    def _required_models(self) -> list[str]:
        models = [
            self._config.ollama_model,
            self._config.planner_model,
            self._config.creative_model,
            self._config.fast_model,
        ]
        unique: list[str] = []
        for model in models:
            if model and model not in unique:
                unique.append(model)
        return unique

    def _is_server_ready(self) -> bool:
        try:
            response = requests.get(f"{self._config.ollama_url}/api/tags", timeout=1.5)
            return response.ok
        except requests.RequestException:
            return False

    def _available_models(self) -> set[str]:
        try:
            response = requests.get(f"{self._config.ollama_url}/api/tags", timeout=2)
            response.raise_for_status()
            data = response.json()
            models = set()
            for item in data.get("models", []):
                name = item.get("name", "")
                if not name:
                    continue
                models.add(name)
                models.add(name.split(":", 1)[0])
            return models
        except requests.RequestException:
            return set()

    def _start_server(self, executable: str) -> None:
        try:
            subprocess.Popen([executable, "serve"], env=self._ollama_env())
        except Exception:
            pass

    def _wait_for_server(self, attempts: int = 20, delay: float = 1.5) -> None:
        for _ in range(attempts):
            if self._is_server_ready():
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

    def _ollama_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self._config.ollama_models_path:
            env["OLLAMA_MODELS"] = self._config.ollama_models_path
        return env

    def _ensure_runtime_dirs(self) -> None:
        for path in (
            self._config.data_dir,
            os.path.dirname(self._config.memory_path),
            os.path.dirname(self._config.notes_path),
            os.path.dirname(self._config.session_memory_path),
            os.path.dirname(self._config.cowork_tasks_path),
            os.path.dirname(self._config.organization_manifest_path),
            os.path.dirname(self._config.vosk_model_path),
        ):
            if not path:
                continue
            try:
                os.makedirs(path, exist_ok=True)
            except OSError:
                continue

    def _warm_models(self) -> None:
        for model in self._required_models():
            try:
                requests.post(
                    f"{self._config.ollama_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": "Reply with one word: ready.",
                        "stream": False,
                        "keep_alive": "10m",
                    },
                    timeout=45,
                )
            except requests.RequestException:
                continue
