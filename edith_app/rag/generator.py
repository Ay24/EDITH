"""
edith_app.rag.generator
========================
Grounded answer generation for EDITH's RAG pipeline.

Sends a strictly-grounded prompt to the local Ollama LLM and returns
the generated answer along with provenance metadata.

Design principles
-----------------
* Uses the existing AgentService connection (reuses the Ollama HTTP session)
* Falls back to a direct Ollama HTTP call if AgentService not available
* Strict "answer from context only" instruction prevents hallucination
* Supports both streaming (token callback) and blocking modes
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from edith_app.rag.context_builder import BuiltContext

logger = logging.getLogger("edith.rag.generator")


@dataclass
class GeneratorResult:
    """Result from the RAG generator."""
    answer: str
    sources: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    context_chars: int = 0
    model_used: str = ""
    was_grounded: bool = True      # False if model said it couldn't find the answer


# Phrases that indicate the LLM couldn't answer from context
_NO_ANSWER_PHRASES = (
    "i don't have that information",
    "not present in the context",
    "not mentioned in",
    "cannot find",
    "no relevant information",
    "context does not",
    "the provided context does not",
)


def _is_grounded_refusal(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in _NO_ANSWER_PHRASES)


class RAGGenerator:
    """
    Generates grounded answers using the local Ollama LLM.

    Parameters
    ----------
    ollama_url    : Ollama server URL
    model         : model name to use for generation
    max_tokens    : maximum tokens to generate
    temperature   : sampling temperature (lower = more faithful to context)
    timeout       : HTTP request timeout in seconds
    """

    def __init__(
        self,
        ollama_url: str = "http://127.0.0.1:11434",
        model: str = "phi3",
        max_tokens: int = 300,
        temperature: float = 0.2,
        timeout: int = 45,
    ) -> None:
        self._url = ollama_url
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._timeout = timeout
        self._session = None

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        context: BuiltContext,
        on_token: Callable[[str], None] | None = None,
    ) -> GeneratorResult:
        """
        Generate an answer from the grounded prompt.

        Parameters
        ----------
        prompt   : the full grounded prompt (from ContextBuilder.format_for_prompt)
        context  : the BuiltContext object (for metadata)
        on_token : optional streaming callback called per token
        """
        t0 = time.monotonic()

        if on_token is not None:
            answer = self._stream(prompt, on_token)
        else:
            answer = self._blocking(prompt)

        latency_ms = (time.monotonic() - t0) * 1000

        result = GeneratorResult(
            answer=answer,
            sources=context.sources,
            latency_ms=latency_ms,
            context_chars=context.char_count,
            model_used=self._model,
            was_grounded=not _is_grounded_refusal(answer),
        )

        logger.debug(
            "Generated answer in %.0fms via model=%s, grounded=%s",
            latency_ms,
            self._model,
            result.was_grounded,
        )
        return result

    def set_model(self, model: str) -> None:
        """Hot-swap the generation model."""
        self._model = model

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_session(self):
        if self._session is None:
            import requests  # type: ignore
            self._session = requests.Session()
        return self._session

    def _blocking(self, prompt: str) -> str:
        """Non-streaming single-shot generation via /api/chat."""
        try:
            session = self._get_session()
            payload = {
                "model": self._model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are EDITH's knowledge retrieval engine. "
                            "Answer strictly from the provided context. "
                            "Be concise and factual."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "keep_alive": "10m",
                "options": {
                    "num_predict": self._max_tokens,
                    "temperature": self._temperature,
                    "stop": ["\nQuestion:", "\nAnswer:", "---"],
                },
            }
            resp = session.post(
                f"{self._url}/api/chat",
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "").strip()
        except Exception as exc:
            logger.warning("RAG generation (blocking) failed: %s", exc)
            return "I encountered an issue generating an answer. Please try again."

    def _stream(self, prompt: str, on_token: Callable[[str], None]) -> str:
        """Streaming generation with per-token callback via /api/chat."""
        chunks: list[str] = []
        try:
            session = self._get_session()
            payload = {
                "model": self._model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are EDITH's knowledge retrieval engine. "
                            "Answer strictly from the provided context. "
                            "Be concise and factual."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "stream": True,
                "keep_alive": "10m",
                "options": {
                    "num_predict": self._max_tokens,
                    "temperature": self._temperature,
                    "stop": ["\nQuestion:", "\nAnswer:", "---"],
                },
            }
            with session.post(
                f"{self._url}/api/chat",
                json=payload,
                timeout=(4, self._timeout),
                stream=True,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # /api/chat streams tokens in message.content
                    token = data.get("message", {}).get("content", "")
                    if token:
                        chunks.append(token)
                        try:
                            on_token(token)
                        except Exception:
                            pass
                    if data.get("done"):
                        break
        except Exception as exc:
            logger.warning("RAG generation (streaming) failed: %s", exc)
            if chunks:
                return "".join(chunks).strip()
            return "I encountered an issue generating an answer. Please try again."
        return "".join(chunks).strip()
