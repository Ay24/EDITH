from __future__ import annotations

import os
import json
import shutil
import subprocess
import threading
import time
from typing import Callable, Iterable

import requests

from edith_app.config import AppConfig
from edith_app.core.model_router import ModelRouter
from edith_app.models import ChatMessage
from edith_app.services.logging_service import get_logger


class AgentService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._logger = get_logger("edith.agent", config.runtime_log_path)
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=1)
        self._session.mount('http://', adapter)
        self._session.mount('https://', adapter)
        self._router = ModelRouter(config)
        self._tags_cache: tuple[float, set[str]] = (0.0, set())
        self._recovery_lock = threading.Lock()
        self._recovery_state: dict[str, float] = {}
        self._native_engine = None
        if os.getenv("EDITH_USE_NATIVE_LLM") == "1":
            try:
                from edith_app.core.inference_manager import AdaptiveLlamaEngine
                model_path = os.getenv("EDITH_NATIVE_MODEL_PATH", "models/llama-3.2-3b.gguf")
                self._native_engine = AdaptiveLlamaEngine(model_path=model_path, profile_name="balanced")
            except Exception as e:
                self._logger.error(f"Failed to load native engine: {e}")

    @property
    def enabled(self) -> bool:
        return self._model_available(self._config.ollama_model)

    def runtime_status(self) -> tuple[bool, str]:
        if not self._server_ready():
            return False, "Ollama server offline"
        if not self._model_available(self._config.ollama_model):
            return False, f"Model {self._config.ollama_model} not loaded"
        return True, f"Model {self._config.ollama_model} ready"

    def reply(self, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:
        decision = self._router.select("reply", prompt=prompt, lane="chat")
        return self._run_model(
            model=decision.model,
            prompt=prompt,
            history=history,
            system_instruction=(
                f"{self._config.persona.system_prompt} "
                "Default to crisp, direct responses. Usually keep it to 2 to 4 short sentences."
            ),
            max_predict=decision.max_predict,
            timeout_seconds=decision.timeout_seconds,
            temperature=decision.temperature,
        context_kwargs=context_kwargs,
        )

    def plan(self, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:
        decision = self._router.select("plan", prompt=prompt, lane="cowork")
        return self._run_model(
            model=decision.model,
            prompt=prompt,
            history=history,
            system_instruction=(
                "You are Edith's planning model. Break problems into clear steps, identify tradeoffs, "
                "and propose a practical path forward. Keep the plan punchy and compact."
            ),
            max_predict=decision.max_predict,
            timeout_seconds=decision.timeout_seconds,
            temperature=decision.temperature,
        context_kwargs=context_kwargs,
        )

    def brainstorm(self, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:
        decision = self._router.select("creative", prompt=prompt, lane="chat")
        return self._run_model(
            model=decision.model,
            prompt=prompt,
            history=history,
            system_instruction=(
                "You are Edith's creative ideation model. Generate bold but practical ideas, alternatives, "
                "angles, and next experiments. Keep it lively but compact."
            ),
            max_predict=decision.max_predict,
            timeout_seconds=decision.timeout_seconds,
            temperature=decision.temperature,
        context_kwargs=context_kwargs,
        )

    def quick_think(self, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:
        decision = self._router.select("quick", prompt=prompt, lane="chat")
        return self._run_model(
            model=decision.model,
            prompt=prompt,
            history=history,
            system_instruction=(
                "You are Edith's fast tactical model. Give a concise, decisive answer with the next best move."
            ),
            max_predict=decision.max_predict,
            timeout_seconds=decision.timeout_seconds,
            temperature=decision.temperature,
        context_kwargs=context_kwargs,
        )

    def specialist_reply(
        self,
        prompt: str,
        history: Iterable[ChatMessage],
        specialist_instruction: str,
        lane: str = "chat",
        prefer_fast: bool = False,
        context_kwargs: dict[str, str] | None = None,
    ) -> str:
        task = "quick" if prefer_fast else "reply"
        decision = self._router.select(task, prompt=prompt, lane=lane)
        return self._run_model(
            model=decision.model,
            prompt=prompt,
            history=history,
            system_instruction=(
                f"{self._config.persona.system_prompt} "
                f"{specialist_instruction} "
                "Be direct, natural, and context-aware."
            ),
            max_predict=decision.max_predict,
            timeout_seconds=decision.timeout_seconds,
            temperature=decision.temperature,
        context_kwargs=context_kwargs,
        )

    def stream_specialist_reply(
        self,
        prompt: str,
        history: Iterable[ChatMessage],
        specialist_instruction: str,
        lane: str = "chat",
        prefer_fast: bool = False,
        on_token: Callable[[str], None] | None = None,
        context_kwargs: dict[str, str] | None = None,
    ) -> str:
        task = "quick" if prefer_fast else "reply"
        decision = self._router.select(task, prompt=prompt, lane=lane)
        return self._run_model_stream(
            model=decision.model,
            prompt=prompt,
            history=history,
            system_instruction=(
                f"{self._config.persona.system_prompt} "
                f"{specialist_instruction} "
                "Be direct, natural, and context-aware."
            ),
            max_predict=decision.max_predict,
            timeout_seconds=decision.timeout_seconds,
            temperature=decision.temperature,
            on_token=on_token,
        )

    def parse_intent(self, prompt: str, history: Iterable[ChatMessage], prefer_fast: bool = False, context_kwargs: dict[str, str] | None = None) -> str:
        task = "intent" if prefer_fast else "reply"
        decision = self._router.select(task, prompt=prompt, lane="router")
        return self._run_model(
            model=decision.model,
            prompt=prompt,
            history=history,
            system_instruction=(
                "You are Edith's intent parser. Return strict JSON only, no markdown, no prose."
            ),
            max_predict=decision.max_predict,
            timeout_seconds=decision.timeout_seconds,
            temperature=decision.temperature,
        context_kwargs=context_kwargs,
        )

    def think_with_user(self, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:
        planner = self.plan(prompt, history, context_kwargs=context_kwargs)
        creative = self.brainstorm(prompt, history, context_kwargs=context_kwargs)
        tactical = self.quick_think(prompt, history, context_kwargs=context_kwargs)
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
        max_predict: int = 160,
        timeout_seconds: int = 24,
        temperature: float = 0.45,
        context_kwargs: dict[str, str] | None = None,
    ) -> str:
        if self._native_engine:
            full_prompt = self._compose_prompt(system_instruction, prompt, history, context_kwargs)
            try:
                resp = self._native_engine.generate(full_prompt, max_tokens=max_predict, stream=False)
                return resp['choices'][0]['text'].strip()
            except Exception as e:
                self._logger.error(f"Native engine failed: {e}")
                return "The native LLM engine encountered an error."

        if not self._server_ready():
            self._logger.warning("ollama server not ready for model=%s", model)
            self._recover_async(model)
            return "Ollama is starting up. Keep Edith open for a moment and try again."
        target_model = self._select_available_model(model)
        if not self._model_available(target_model):
            self._logger.warning("ollama model missing model=%s", model)
            self._recover_async(model)
            return f"I am preparing the local model '{model}'. Keep Edith open and I will use it as soon as it finishes loading."

        payload = {
            "model": target_model,
            "prompt": self._compose_prompt(system_instruction, prompt, history, context_kwargs),
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "num_predict": max_predict,
                "temperature": temperature,
                "num_ctx": 2048,
            },
        }

        for attempt in range(2):
            try:
                response = self._session.post(
                    f"{self._config.ollama_url}/api/generate",
                    json=payload,
                    timeout=timeout_seconds,
                )
                if response.status_code >= 500:
                    self._logger.warning("ollama 5xx status=%s model=%s attempt=%s", response.status_code, model, attempt)
                    if attempt == 0:
                        time.sleep(1.0)
                        continue
                    self._recover_async(model)
                    return f"The local model '{model}' is still warming up or hit an internal Ollama error. Give it a moment and try again."
                response.raise_for_status()
                try:
                    data = response.json()
                except json.JSONDecodeError:
                    self._logger.warning("ollama invalid json model=%s attempt=%s", model, attempt)
                    if attempt == 0:
                        time.sleep(0.8)
                        continue
                    self._recover_async(model)
                    return f"The local model '{model}' returned an invalid response while warming up. Try again in a moment."
                return data.get("response", "").strip() or "The local model returned an empty response."
            except requests.RequestException:
                self._logger.warning("ollama request exception model=%s attempt=%s", model, attempt, exc_info=True)
                if attempt == 0:
                    time.sleep(0.8)
                    continue
                self._recover_async(model)
                return f"I couldn't reach the local model '{model}' just now. Edith is still trying to bring Ollama online."
            except Exception:
                self._logger.exception("unexpected model runtime error model=%s attempt=%s", model, attempt)
                if attempt == 0:
                    time.sleep(0.6)
                    continue
                self._recover_async(model)
                return f"I hit a local model runtime issue for '{model}', but I am recovering it in the background."
        self._recover_async(model)
        return f"The local model '{model}' is still warming up. Try again in a moment."

    def _run_model_stream(
        self,
        model: str,
        prompt: str,
        history: Iterable[ChatMessage],
        system_instruction: str,
        max_predict: int = 160,
        timeout_seconds: int = 24,
        temperature: float = 0.45,
        on_token: Callable[[str], None] | None = None,
        context_kwargs: dict[str, str] | None = None,
    ) -> str:
        if self._native_engine:
            full_prompt = self._compose_prompt(system_instruction, prompt, history, context_kwargs)
            try:
                resp_stream = self._native_engine.generate(full_prompt, max_tokens=max_predict, stream=True)
                full_text = []
                for chunk in resp_stream:
                    token = chunk['choices'][0]['text']
                    if token:
                        full_text.append(token)
                        if on_token:
                            on_token(token)
                return "".join(full_text).strip()
            except Exception as e:
                self._logger.error(f"Native engine stream failed: {e}")
                return "The native LLM engine encountered an error."

        if not self._server_ready():
            self._logger.warning("ollama server not ready for streaming model=%s", model)
            self._recover_async(model)
            return "Ollama is starting up. Keep Edith open for a moment and try again."
        target_model = self._select_available_model(model)
        if not self._model_available(target_model):
            self._logger.warning("ollama stream model missing model=%s", model)
            self._recover_async(model)
            return f"I am preparing the local model '{model}'. Keep Edith open and I will use it as soon as it finishes loading."

        payload = {
            "model": target_model,
            "prompt": self._compose_prompt(system_instruction, prompt, history, context_kwargs),
            "stream": True,
            "keep_alive": "10m",
            "options": {
                "num_predict": max_predict,
                "temperature": temperature,
                "num_ctx": 2048,
            },
        }

        chunks: list[str] = []
        try:
            with self._session.post(
                f"{self._config.ollama_url}/api/generate",
                json=payload,
                timeout=(4, timeout_seconds),
                stream=True,
            ) as response:
                if response.status_code >= 500:
                    self._logger.warning("ollama stream 5xx status=%s model=%s", response.status_code, target_model)
                    self._recover_async(target_model)
                    return f"The local model '{target_model}' is still warming up or hit an internal Ollama error."
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = data.get("response", "")
                    if token:
                        chunks.append(token)
                        if on_token is not None:
                            try:
                                on_token(token)
                            except Exception:
                                self._logger.debug("stream token callback failed", exc_info=True)
                    if data.get("done"):
                        break
        except requests.RequestException:
            self._logger.warning("ollama stream request exception model=%s", target_model, exc_info=True)
            self._recover_async(target_model)
            if chunks:
                return "".join(chunks).strip()
            return self._run_model(
                model=target_model,
                prompt=prompt,
                history=history,
                system_instruction=system_instruction,
                max_predict=max_predict,
                timeout_seconds=timeout_seconds,
                temperature=temperature,
            )
        except Exception:
            self._logger.exception("unexpected streaming runtime error model=%s", target_model)
            if chunks:
                return "".join(chunks).strip()
            return f"I hit a local model runtime issue for '{target_model}', but I am recovering it in the background."

        return "".join(chunks).strip() or "The local model returned an empty response."

    def _compose_prompt(self, system_instruction: str, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:
        from datetime import datetime
        now_dt = datetime.now()
        if context_kwargs:
            try:
                system_instruction = system_instruction.format(**context_kwargs)
            except KeyError:
                pass
        now_str = now_dt.strftime("%I:%M %p, %A, %d %B %Y")
        hour = now_dt.hour

        # ── Time-of-day micro-persona shift ────────────────────────────────────
        if 5 <= hour < 12:
            time_note = "It's morning. Keep responses energising and forward-looking."
        elif 12 <= hour < 17:
            time_note = "Mid-day session. User is likely deep in work — be efficient and direct."
        elif 17 <= hour < 21:
            time_note = "Evening. Slightly warmer tone is appropriate; user may be winding down."
        else:
            time_note = "Late night. User is still working — acknowledge that briefly if relevant, keep it supportive."

        # ── SITUATIONAL AWARENESS block ────────────────────────────────────────
        awareness_block = (
            f"## SITUATIONAL AWARENESS\n"
            f"- Current time: {now_str}\n"
            f"- {time_note}\n"
        )

        # ── Build conversation transcript ──────────────────────────────────────
        transcript = []
        for item in list(history)[-self._config.history_max_messages:]:
            prefix = "YOU" if item.source == "user" else "EDITH"
            transcript.append(f"{prefix}: {item.text}")

        chat_history = "\n".join(transcript) if transcript else "No prior context this session."

        return (
            f"{system_instruction}\n\n"
            f"{awareness_block}\n"
            "## Conversation History\n"
            f"{chat_history}\n\n"
            f"YOU: {prompt}\n"
            "EDITH:"
        )

    def _select_available_model(self, requested: str) -> str:
        if self._model_available(requested):
            return requested
        for fallback in (
            self._config.creative_model,
            self._config.ollama_model,
            self._config.fast_model,
            self._config.planner_model,
        ):
            if fallback and self._model_available(fallback):
                self._logger.info("falling back from model=%s to model=%s", requested, fallback)
                return fallback
        return requested

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
