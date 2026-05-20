"""
edith_cloud.services.cloud_stt
================================
Cloud-backed Speech-to-Text using Groq Whisper API.

Drop-in replacement for VoiceService — same public interface.
Records audio locally via pyaudio, sends to Groq Whisper for
sub-400ms transcription, then returns the text.

Falls back to local VoiceService if Groq is unavailable.
"""
from __future__ import annotations

import io
import logging
import queue
import struct
import threading
import time
import wave
import audioop
from typing import Any

logger = logging.getLogger("edith.cloud_stt")

try:
    import pyaudio
except ImportError:
    pyaudio = None

try:
    from groq import Groq
except ImportError:
    Groq = None


class CloudSTTService:
    """
    Cloud speech-to-text via Groq Whisper.

    Exposes the same API as VoiceService:
      - listen_once() -> str
      - listen_for_command(timeout, phrase_time_limit) -> str
      - listen_for_interrupt() -> str
      - estimate_confidence(text) -> float
      - enabled: bool
      - on_interrupt: callback
      - start_session() / stop_session()
    """

    def __init__(self, config: Any) -> None:
        self._api_key = getattr(config, "groq_api_key", "")
        self._stt_model = getattr(config, "cloud_stt_model", "whisper-large-v3")
        self._client = None
        self.on_interrupt = None

        # Persistent mic state
        self._pyaudio_instance = None
        self._mic_stream = None
        self._is_recording = False
        self._transcription_queue: queue.Queue[str] = queue.Queue()
        self._record_thread: threading.Thread | None = None

        # Local fallback
        self._local_voice = None
        self._config = config

    @property
    def enabled(self) -> bool:
        return bool(self._api_key) and pyaudio is not None

    def start_session(self) -> None:
        """Start persistent mic for background listening."""
        if pyaudio is None or self._is_recording:
            return
        try:
            self._pyaudio_instance = pyaudio.PyAudio()
            self._mic_stream = self._pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=4000,
            )
            self._is_recording = True
            self._record_thread = threading.Thread(
                target=self._background_listen_loop, daemon=True
            )
            self._record_thread.start()
        except Exception as exc:
            logger.warning("Failed to start cloud STT session: %s", exc)
            self._is_recording = False

    def stop_session(self) -> None:
        self._is_recording = False
        if self._mic_stream:
            try:
                self._mic_stream.stop_stream()
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None
        if self._pyaudio_instance:
            try:
                self._pyaudio_instance.terminate()
            except Exception:
                pass
            self._pyaudio_instance = None

    def listen_once(self) -> str:
        return self.listen_for_command(timeout=None)

    def listen_for_command(self, timeout: int | None = 7, phrase_time_limit: int = 8) -> str:
        """Record a chunk of audio and transcribe via Groq Whisper."""
        if not self._is_recording:
            # One-shot recording
            return self._record_and_transcribe(
                duration=min(phrase_time_limit, 8),
                timeout=timeout,
            )

        # Persistent mode — wait for queued transcription
        try:
            while not self._transcription_queue.empty():
                self._transcription_queue.get_nowait()
            return self._transcription_queue.get(timeout=timeout or 10)
        except queue.Empty:
            return ""

    def listen_for_interrupt(self) -> str:
        try:
            return self._transcription_queue.get_nowait()
        except queue.Empty:
            return ""

    def estimate_confidence(self, text: str) -> float:
        """Whisper transcriptions are high-confidence; simple heuristic."""
        cleaned = " ".join(text.strip().split()).lower()
        if not cleaned:
            return 0.0
        if cleaned in {"yes", "no", "yeah", "yep", "nope", "okay", "ok", "cancel", "stop"}:
            return 0.95
        words = cleaned.split()
        if len(words) == 1 and len(words[0]) <= 2:
            return 0.15
        # Whisper output is generally cleaner than Vosk
        return min(1.0, 0.65 + len(words) * 0.03)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None and Groq is not None and self._api_key:
            self._client = Groq(api_key=self._api_key)
        return self._client

    def _record_and_transcribe(self, duration: int = 6, timeout: int | None = 7) -> str:
        """One-shot: record audio, send to Groq Whisper, return text."""
        if pyaudio is None:
            return self._local_fallback_listen()

        try:
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=4000,
            )

            # Simple energy-based VAD: wait for speech, then record
            frames: list[bytes] = []
            silence_chunks = 0
            max_chunks = int(16000 / 4000 * duration)
            speech_started = False

            for _ in range(max_chunks + 20):  # extra buffer for silence detection
                data = stream.read(4000, exception_on_overflow=False)
                # Simple RMS energy check
                rms = self._rms(data)
                if rms > 300:
                    speech_started = True
                    silence_chunks = 0
                elif speech_started:
                    silence_chunks += 1

                if speech_started:
                    frames.append(data)

                if speech_started and silence_chunks > 6:  # ~1.5s silence
                    break

            stream.stop_stream()
            stream.close()
            pa.terminate()

            if not frames:
                return ""

            return self._transcribe_frames(frames)
        except Exception as exc:
            logger.warning("Recording failed: %s", exc)
            return self._local_fallback_listen()

    def _transcribe_frames(self, frames: list[bytes]) -> str:
        """Send raw PCM frames to Groq Whisper as a WAV file."""
        client = self._get_client()
        if client is None:
            return self._local_fallback_listen()

        # Build in-memory WAV
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(16000)
            wf.writeframes(b"".join(frames))
        buf.seek(0)
        buf.name = "audio.wav"

        try:
            transcription = client.audio.transcriptions.create(
                model=self._stt_model,
                file=buf,
                language="en",
                response_format="text",
            )
            text = transcription.strip() if isinstance(transcription, str) else str(transcription).strip()
            return self._normalize(text)
        except Exception as exc:
            logger.warning("Groq Whisper failed: %s", exc)
            return ""

    def _background_listen_loop(self) -> None:
        """Persistent background listening with chunked Whisper transcription."""
        while self._is_recording and self._mic_stream:
            try:
                frames: list[bytes] = []
                silence_chunks = 0
                speech_started = False

                for _ in range(80):  # ~20 seconds max
                    if not self._is_recording:
                        return
                    data = self._mic_stream.read(4000, exception_on_overflow=False)
                    rms = self._rms(data)

                    if rms > 300:
                        speech_started = True
                        silence_chunks = 0
                    elif speech_started:
                        silence_chunks += 1

                    if speech_started:
                        frames.append(data)

                    # Partial speech detected — trigger interrupt callback
                    if speech_started and len(frames) > 2 and self.on_interrupt:
                        self.on_interrupt()

                    if speech_started and silence_chunks > 6:
                        break

                if frames:
                    text = self._transcribe_frames(frames)
                    if text:
                        self._transcription_queue.put(text)
            except Exception:
                time.sleep(0.2)

    @staticmethod
    def _rms(data: bytes) -> float:
        """Compute RMS energy of 16-bit PCM audio."""
        if not data:
            return 0.0
        try:
            return float(audioop.rms(data, 2))
        except Exception:
            count = len(data) // 2
            if count == 0:
                return 0.0
            shorts = struct.unpack(f"<{count}h", data)
            sum_sq = sum(s * s for s in shorts)
            return (sum_sq / count) ** 0.5

    def _normalize(self, text: str) -> str:
        lowered = " ".join(text.strip().split()).lower()
        replacements = {
            "what's app": "whatsapp",
            "you tube": "youtube",
            "wi fi": "wifi",
            "blue tooth": "bluetooth",
        }
        for wrong, right in replacements.items():
            lowered = lowered.replace(wrong, right)
        return lowered

    def _local_fallback_listen(self) -> str:
        """Fall back to local VoiceService if cloud STT fails."""
        if self._local_voice is None:
            try:
                from edith_app.services.voice_service import VoiceService
                self._local_voice = VoiceService(self._config)
            except Exception:
                return ""
        try:
            return self._local_voice.listen_for_command()
        except Exception:
            return ""
