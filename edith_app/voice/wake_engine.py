"""Dedicated wake-word detection: openWakeWord (preferred) or Vosk-keyword fallback."""
from __future__ import annotations

import logging
import struct
import threading
from typing import Callable

logger = logging.getLogger("edith.wake")


class WakeEngine:
    """
    Processes 16 kHz mono PCM16 frames. Fires on_wake() when a wake phrase is detected.
    """

    def __init__(
        self,
        keywords: tuple[str, ...] = ("edith", "jarvis", "friday"),
        backend: str = "auto",
        openwakeword_models: tuple[str, ...] = ("hey_jarvis",),
        score_threshold: float = 0.55,
    ) -> None:
        self._keywords = tuple(k.lower().strip() for k in keywords if k.strip())
        self._backend = backend.lower().strip()
        self._oww_models = openwakeword_models
        self._threshold = score_threshold
        self._on_wake: Callable[[str], None] | None = None
        self._armed = False
        self._lock = threading.Lock()
        self._oww = None
        self._use_oww = False
        self._init_backend()

    @property
    def enabled(self) -> bool:
        return bool(self._keywords) or self._use_oww

    def set_callback(self, callback: Callable[[str], None]) -> None:
        self._on_wake = callback

    def arm(self) -> None:
        with self._lock:
            self._armed = True

    def disarm(self) -> None:
        with self._lock:
            self._armed = False

    def is_armed(self) -> bool:
        with self._lock:
            return self._armed

    def feed_pcm16(self, data: bytes, sample_rate: int = 16000) -> None:
        if not data:
            return
        if self._use_oww and self._oww is not None:
            try:
                import numpy as np
                samples = np.frombuffer(data, dtype=np.int16)
                if sample_rate != 16000 and sample_rate > 0:
                    # Simple decimation for non-16k (rare)
                    step = max(1, sample_rate // 16000)
                    samples = samples[::step]
                scores = self._oww.predict(samples)
                for name, score in (scores or {}).items():
                    if float(score) >= self._threshold:
                        self._fire(f"oww:{name}")
                        return
            except Exception:
                pass

    def feed_partial_transcript(self, partial: str) -> None:
        """Vosk-keyword fallback when openWakeWord is unavailable."""
        if self._use_oww:
            return
        text = partial.lower().strip()
        if not text:
            return
        for kw in self._keywords:
            if kw in text.split() or text.startswith(kw + " ") or text == kw:
                self._fire(f"keyword:{kw}")
                return

    def _fire(self, source: str) -> None:
        with self._lock:
            if self._armed:
                return
            self._armed = True
        logger.debug("Wake detected via %s", source)
        if self._on_wake:
            try:
                self._on_wake(source)
            except Exception:
                pass

    def _init_backend(self) -> None:
        want_oww = self._backend in {"auto", "openwakeword", "oww"}
        if want_oww:
            try:
                from openwakeword.model import Model as OwwModel
                models = list(self._oww_models) if self._oww_models else ["hey_jarvis"]
                self._oww = OwwModel(wakeword_models=models, inference_framework="onnx")
                self._use_oww = True
                logger.info("WakeEngine: openWakeWord active (%s)", models)
                return
            except Exception as exc:
                logger.info("WakeEngine: openWakeWord unavailable (%s), using keyword fallback", exc)
        self._use_oww = False
        logger.info("WakeEngine: Vosk keyword fallback for %s", self._keywords)

    @staticmethod
    def rms_energy(data: bytes) -> float:
        if len(data) < 2:
            return 0.0
        count = len(data) // 2
        if count == 0:
            return 0.0
        samples = struct.unpack(f"<{count}h", data[: count * 2])
        if not samples:
            return 0.0
        s = sum(x * x for x in samples)
        return (s / len(samples)) ** 0.5
