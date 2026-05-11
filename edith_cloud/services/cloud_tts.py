"""
edith_cloud.services.cloud_tts
================================
Cloud-backed TTS using Microsoft Edge-TTS (completely free, no API key).

Drop-in replacement for AudioService's TTS functionality.
Streams audio directly through sounddevice — zero temp file writes.

System volume controls (adjust_volume, set_volume, mute, unmute)
are delegated to the original AudioService.
"""
from __future__ import annotations

import asyncio
import ctypes
import logging
import queue
import re
import threading
from typing import Any

logger = logging.getLogger("edith.cloud_tts")

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    import sounddevice as _sd
    import numpy as _np
    _SD_AVAILABLE = True
except ImportError:
    _sd = None
    _np = None
    _SD_AVAILABLE = False

# Sentence-boundary splitter for chunked streaming
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')

# Voice profiles matching local EDITH profiles
_EDGE_PROFILES = {
    "edith":  "en-US-AriaNeural",
    "jarvis": "en-US-GuyNeural",
    "friday": "en-US-JennyNeural",
}

_THREAD_PRIORITY_BELOW_NORMAL = -1


def _set_thread_priority(priority: int) -> None:
    try:
        handle = ctypes.windll.kernel32.GetCurrentThread()
        ctypes.windll.kernel32.SetThreadPriority(handle, priority)
    except Exception:
        pass


class CloudTTSService:
    """
    Edge-TTS cloud TTS with the same API as AudioService.

    System audio controls are delegated to a local AudioService instance
    so volume/mute/unmute still work with Windows audio endpoints.
    """

    def __init__(self, config: Any = None) -> None:
        self._lock = threading.Lock()
        self._speaking = False
        self._speech_queue: queue.Queue[str | None] = queue.Queue()
        self._queue_worker: threading.Thread | None = None
        self._queue_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._active_profile = "edith"
        self._voice = _EDGE_PROFILES.get("edith", "en-US-AriaNeural")
        self._rate = getattr(config, "cloud_tts_rate", "+5%") if config else "+5%"

        # Delegate system audio controls to local AudioService
        self._local_audio = None
        self._local_audio_init = False

    def _ensure_local_audio(self):
        if not self._local_audio_init:
            self._local_audio_init = True
            try:
                from edith_app.services.audio_service import AudioService
                self._local_audio = AudioService()
            except Exception:
                pass
        return self._local_audio

    # ── Public API — mirrors AudioService ─────────────────────────────────────

    @property
    def tts_enabled(self) -> bool:
        return edge_tts is not None and _SD_AVAILABLE

    @property
    def system_audio_enabled(self) -> bool:
        local = self._ensure_local_audio()
        return local.system_audio_enabled if local else False

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def speak(self, text: str) -> None:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return
        self.stop()
        self.speak_queued(cleaned)

    def speak_queued(self, text: str) -> None:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return
        self._ensure_queue_worker()
        self._speech_queue.put(cleaned)

    def clear_queue(self) -> None:
        while True:
            try:
                self._speech_queue.get_nowait()
            except queue.Empty:
                break

    def stop(self) -> None:
        self._stop_event.set()
        self.clear_queue()
        if _sd is not None:
            try:
                _sd.stop()
            except Exception:
                pass
        self._speaking = False
        self._stop_event.clear()

    def set_voice_profile(self, profile: str) -> str:
        profile = profile.lower().strip()
        if profile not in _EDGE_PROFILES:
            return "Choose a voice profile: Edith, Jarvis, or Friday."
        self._active_profile = profile
        self._voice = _EDGE_PROFILES[profile]
        return f"Voice profile set to {profile.title()}."

    # ── System audio controls (delegated to local) ────────────────────────────

    def adjust_volume(self, delta: float) -> str:
        local = self._ensure_local_audio()
        return local.adjust_volume(delta) if local else "System volume controls unavailable."

    def set_volume(self, level: int) -> str:
        local = self._ensure_local_audio()
        return local.set_volume(level) if local else "System volume controls unavailable."

    def mute(self) -> str:
        local = self._ensure_local_audio()
        return local.mute() if local else "System volume controls unavailable."

    def unmute(self) -> str:
        local = self._ensure_local_audio()
        return local.unmute() if local else "System volume controls unavailable."

    # ── Queue worker ──────────────────────────────────────────────────────────

    def _ensure_queue_worker(self) -> None:
        with self._queue_lock:
            if self._queue_worker is not None and self._queue_worker.is_alive():
                return
            self._queue_worker = threading.Thread(
                target=self._speech_queue_loop, daemon=True
            )
            self._queue_worker.start()

    def _speech_queue_loop(self) -> None:
        _set_thread_priority(_THREAD_PRIORITY_BELOW_NORMAL)
        while True:
            chunk = self._speech_queue.get()
            if chunk is None:
                return
            self._speaking = True
            try:
                self._speak_edge_tts(chunk)
            except Exception as exc:
                logger.warning("Edge-TTS speech failed: %s", exc)
            finally:
                self._speaking = False

    # ── Edge-TTS synthesis + playback ─────────────────────────────────────────

    def _speak_edge_tts(self, text: str) -> None:
        if edge_tts is None or not _SD_AVAILABLE:
            return

        async def _fetch() -> bytes:
            communicate = edge_tts.Communicate(text, self._voice, rate=self._rate)
            try:
                communicate.audio_format = "riff-24khz-16bit-mono-pcm"
            except AttributeError:
                pass
            chunks: list[bytes] = []
            async for item in communicate.stream():
                if self._stop_event.is_set():
                    return b""
                if item["type"] == "audio":
                    chunks.append(item["data"])
            return b"".join(chunks)

        try:
            loop = asyncio.new_event_loop()
            try:
                raw = loop.run_until_complete(_fetch())
            finally:
                loop.close()

            if not raw or self._stop_event.is_set():
                return

            # Parse WAV → PCM → sounddevice
            if raw[:4] == b"RIFF":
                pos = raw.find(b"data")
                if pos != -1:
                    pcm = _np.frombuffer(raw[pos + 8:], dtype=_np.int16).astype(_np.float32) / 32768.0
                    _sd.play(pcm, samplerate=24000, blocking=False)
                    _sd.wait()
        except Exception as exc:
            logger.warning("Edge-TTS playback failed: %s", exc)
