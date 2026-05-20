"""Detect stable partial transcripts for early command submission."""
from __future__ import annotations

import re
import time


class StreamingIntentDetector:
    """
    Emits a command string when a partial transcript stabilizes or a final arrives.
    Reduces end-to-utterance wait by firing before Vosk finalizes in some cases.
    """

    _ACTION_STARTERS = (
        "open", "close", "play", "stop", "set", "turn", "send", "message", "call",
        "search", "find", "list", "show", "create", "run", "lock", "mute", "volume",
        "what", "how", "when", "where", "why", "tell", "remind", "add", "delete",
    )

    def __init__(
        self,
        min_words: int = 3,
        stable_ticks: int = 3,
        min_chars: int = 10,
        cooldown_seconds: float = 1.2,
    ) -> None:
        self._min_words = max(2, min_words)
        self._stable_ticks = max(2, stable_ticks)
        self._min_chars = max(6, min_chars)
        self._cooldown = cooldown_seconds
        self._last_partial = ""
        self._stable_count = 0
        self._last_emit_at = 0.0
        self._emitted_text = ""

    def reset(self) -> None:
        self._last_partial = ""
        self._stable_count = 0
        self._emitted_text = ""

    def feed_partial(self, text: str) -> str | None:
        cleaned = " ".join((text or "").strip().split()).lower()
        if not cleaned or len(cleaned) < self._min_chars:
            self._stable_count = 0
            self._last_partial = cleaned
            return None

        if cleaned == self._last_partial:
            self._stable_count += 1
        else:
            self._last_partial = cleaned
            self._stable_count = 1

        if self._stable_count < self._stable_ticks:
            return None
        if not self._looks_like_command(cleaned):
            return None
        if cleaned == self._emitted_text:
            return None
        now = time.monotonic()
        if now - self._last_emit_at < self._cooldown:
            return None

        self._emitted_text = cleaned
        self._last_emit_at = now
        self._stable_count = 0
        return cleaned

    def feed_final(self, text: str) -> str | None:
        cleaned = " ".join((text or "").strip().split()).lower()
        if not cleaned:
            return None
        if cleaned == self._emitted_text:
            return None
        self._emitted_text = cleaned
        self._last_emit_at = time.monotonic()
        return cleaned

    def _looks_like_command(self, text: str) -> bool:
        words = text.split()
        if len(words) >= self._min_words:
            return True
        if words and words[0] in self._ACTION_STARTERS:
            return len(text) >= self._min_chars
        if re.match(r"^(yes|no|cancel|stop|okay|ok)\b", text):
            return True
        return False
