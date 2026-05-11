"""
edith_cloud.services.cloud_llm
================================
Drop-in replacement for AgentService that routes all LLM calls through
the Groq API.  Exposes the identical public interface so the rest of
EDITH (assistant.py, NeuralRouter, AgentLoop) works unchanged.

Falls back to local Ollama if Groq returns 429 (rate-limit) or if the
key is missing and fallback_to_ollama is enabled.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from typing import Callable, Iterable, Any

import requests

from edith_app.config import AppConfig
from edith_app.models import ChatMessage
from edith_app.services.logging_service import get_logger

logger = logging.getLogger("edith.cloud_llm")

# ── Lazy Groq import ──────────────────────────────────────────────────────────
_groq_client = None
_groq_lock = threading.Lock()


def _get_groq(api_key: str):
    """Lazy-init a shared Groq client."""
    global _groq_client
    if _groq_client is not None:
        return _groq_client
    with _groq_lock:
        if _groq_client is not None:
            return _groq_client
        try:
            from groq import Groq
            _groq_client = Groq(api_key=api_key)
            return _groq_client
        except ImportError:
            logger.error("groq package not installed. Run: pip install groq")
            return None


class CloudLLMService:
    """
    Cloud-backed LLM service using Groq.

    Mirrors the full AgentService public API so EdithAssistant and
    NeuralRouter can use it without changes.
    """

    def __init__(self, config: Any) -> None:
        self._config = config
        self._logger = get_logger("edith.cloud_llm", config.runtime_log_path)
        self._api_key = getattr(config, "groq_api_key", "")
        self._heavy_model = getattr(config, "cloud_llm_model", "llama-3.3-70b-versatile")
        self._fast_model = getattr(config, "cloud_fast_model", "llama-3.1-8b-instant")
        self._fallback_to_ollama = getattr(config, "fallback_to_ollama", True)

        # Ollama fallback agent (lazy)
        self._ollama_agent = None

    # ── AgentService compatibility properties ─────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def runtime_status(self) -> tuple[bool, str]:
        if not self._api_key:
            return False, "GROQ_API_KEY not set"
        return True, f"Groq cloud — {self._heavy_model}"

    # ── Public LLM methods (identical to AgentService) ────────────────────────

    def reply(self, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:
        return self._call(
            model=self._fast_model,
            prompt=prompt,
            history=history,
            system_instruction=(
                f"{self._config.persona.system_prompt} "
                "Default to crisp, direct responses. Usually keep it to 2 to 4 short sentences."
            ),
            max_tokens=200,
            temperature=0.45,
            context_kwargs=context_kwargs,
        )

    def plan(self, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:
        return self._call(
            model=self._heavy_model,
            prompt=prompt,
            history=history,
            system_instruction=(
                "You are Edith's planning model. Break problems into clear steps, identify tradeoffs, "
                "and propose a practical path forward. Keep the plan punchy and compact."
            ),
            max_tokens=600,
            temperature=0.5,
            context_kwargs=context_kwargs,
        )

    def brainstorm(self, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:
        return self._call(
            model=self._heavy_model,
            prompt=prompt,
            history=history,
            system_instruction=(
                "You are Edith's creative ideation model. Generate bold but practical ideas, alternatives, "
                "angles, and next experiments. Keep it lively but compact."
            ),
            max_tokens=500,
            temperature=0.75,
            context_kwargs=context_kwargs,
        )

    def quick_think(self, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:
        return self._call(
            model=self._fast_model,
            prompt=prompt,
            history=history,
            system_instruction=(
                "You are Edith's fast tactical model. Give a concise, decisive answer with the next best move."
            ),
            max_tokens=160,
            temperature=0.3,
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
        model = self._fast_model if prefer_fast else self._heavy_model
        return self._call(
            model=model,
            prompt=prompt,
            history=history,
            system_instruction=(
                f"{self._config.persona.system_prompt} "
                f"{specialist_instruction} "
                "Be direct, natural, and context-aware."
            ),
            max_tokens=300,
            temperature=0.45,
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
        model = self._fast_model if prefer_fast else self._heavy_model
        return self._call_stream(
            model=model,
            prompt=prompt,
            history=history,
            system_instruction=(
                f"{self._config.persona.system_prompt} "
                f"{specialist_instruction} "
                "Be direct, natural, and context-aware."
            ),
            max_tokens=300,
            temperature=0.45,
            on_token=on_token,
            context_kwargs=context_kwargs,
        )

    def parse_intent(self, prompt: str, history: Iterable[ChatMessage], prefer_fast: bool = False, context_kwargs: dict[str, str] | None = None) -> str:
        return self._call(
            model=self._fast_model,
            prompt=prompt,
            history=history,
            system_instruction=(
                "You are Edith's intent parser. Return strict JSON only, no markdown, no prose."
            ),
            max_tokens=200,
            temperature=0.2,
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

    # ── Core Groq call (non-streaming) ────────────────────────────────────────

    def _call(
        self,
        model: str,
        prompt: str,
        history: Iterable[ChatMessage],
        system_instruction: str,
        max_tokens: int = 200,
        temperature: float = 0.45,
        context_kwargs: dict[str, str] | None = None,
    ) -> str:
        client = _get_groq(self._api_key)
        if client is None:
            return self._ollama_fallback("reply", prompt, history, context_kwargs)

        messages = self._build_messages(system_instruction, prompt, history, context_kwargs)

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
            text = response.choices[0].message.content or ""
            return text.strip() or "The cloud model returned an empty response."
        except Exception as exc:
            err_str = str(exc).lower()
            if "429" in err_str or "rate" in err_str:
                self._logger.warning("Groq rate-limited, falling back to Ollama")
                return self._ollama_fallback("reply", prompt, history, context_kwargs)
            self._logger.error("Groq API error: %s", exc)
            return self._ollama_fallback("reply", prompt, history, context_kwargs)

    # ── Core Groq call (streaming) ────────────────────────────────────────────

    def _call_stream(
        self,
        model: str,
        prompt: str,
        history: Iterable[ChatMessage],
        system_instruction: str,
        max_tokens: int = 200,
        temperature: float = 0.45,
        on_token: Callable[[str], None] | None = None,
        context_kwargs: dict[str, str] | None = None,
    ) -> str:
        client = _get_groq(self._api_key)
        if client is None:
            return self._ollama_fallback("reply", prompt, history, context_kwargs)

        messages = self._build_messages(system_instruction, prompt, history, context_kwargs)
        chunks: list[str] = []

        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    token = delta.content
                    chunks.append(token)
                    if on_token:
                        try:
                            on_token(token)
                        except Exception:
                            pass
            return "".join(chunks).strip() or "The cloud model returned an empty response."
        except Exception as exc:
            self._logger.error("Groq stream error: %s", exc)
            if chunks:
                return "".join(chunks).strip()
            return self._ollama_fallback("reply", prompt, history, context_kwargs)

    # ── Message builder (Groq uses OpenAI-style messages) ─────────────────────

    def _build_messages(
        self,
        system_instruction: str,
        prompt: str,
        history: Iterable[ChatMessage],
        context_kwargs: dict[str, str] | None = None,
    ) -> list[dict]:
        if context_kwargs:
            try:
                system_instruction = system_instruction.format(**context_kwargs)
            except KeyError:
                pass

        now_dt = datetime.now()
        now_str = now_dt.strftime("%I:%M %p, %A, %d %B %Y")
        hour = now_dt.hour
        if 5 <= hour < 12:
            time_note = "It's morning."
        elif 12 <= hour < 17:
            time_note = "Mid-day session."
        elif 17 <= hour < 21:
            time_note = "Evening."
        else:
            time_note = "Late night."

        system_content = (
            f"{system_instruction}\n\n"
            f"## SITUATIONAL AWARENESS\n"
            f"- Current time: {now_str}\n"
            f"- {time_note}\n"
        )

        messages: list[dict] = [{"role": "system", "content": system_content}]

        hist_list = list(history)[-self._config.history_max_messages:]
        for item in hist_list:
            role = "user" if item.source == "user" else "assistant"
            messages.append({"role": role, "content": item.text})

        messages.append({"role": "user", "content": prompt})
        return messages

    # ── Ollama fallback ───────────────────────────────────────────────────────

    def _ollama_fallback(self, method: str, prompt: str, history: Iterable[ChatMessage], context_kwargs: dict[str, str] | None = None) -> str:
        if not self._fallback_to_ollama:
            return "Cloud LLM unavailable and local fallback is disabled."
        if self._ollama_agent is None:
            try:
                from edith_app.services.agent_service import AgentService
                self._ollama_agent = AgentService(self._config)
            except Exception as exc:
                self._logger.error("Ollama fallback init failed: %s", exc)
                return "Both cloud and local LLM are unavailable."
        try:
            fn = getattr(self._ollama_agent, method, self._ollama_agent.reply)
            return fn(prompt, history, context_kwargs=context_kwargs)
        except Exception as exc:
            self._logger.error("Ollama fallback call failed: %s", exc)
            return "Both cloud and local LLM are currently unavailable."
