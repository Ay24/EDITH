from __future__ import annotations

import asyncio
import ctypes
import io
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    message="dropout option adds dropout after all but last recurrent layer",
    category=UserWarning,
)

try:
    from comtypes import CLSCTX_ALL
except ImportError:
    CLSCTX_ALL = None

try:
    from ctypes import POINTER, cast
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
except ImportError:
    POINTER = None
    cast = None
    AudioUtilities = None
    IAudioEndpointVolume = None

try:
    import win32com.client
except ImportError:
    win32com = None

try:
    import sounddevice as _sd
    import numpy as _np
    _SD_AVAILABLE = True
except ImportError:
    _sd = None
    _np = None
    _SD_AVAILABLE = False

# ── Kokoro ONNX — quantized, CPU-only, Kokoro quality, zero GPU impact ────────
_KOKORO_ONNX_DIR   = Path(__file__).resolve().parent.parent.parent / "models" / "kokoro-onnx"
_KOKORO_ONNX_MODEL = _KOKORO_ONNX_DIR / "kokoro-v1.0.int8.onnx"
_KOKORO_ONNX_VOICES= _KOKORO_ONNX_DIR / "voices-v1.0.bin"
_KOKORO_ONNX_MODEL_URL  = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx"
_KOKORO_ONNX_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

# ── Voice profiles ────────────────────────────────────────────────────────────
_KOKORO_ONNX_PROFILES = {
    "edith":  {"voice": "af_heart",   "speed": 1.0},   # warm, expressive
    "jarvis": {"voice": "am_michael", "speed": 0.93},  # deep, calm
    "friday": {"voice": "af_sarah",   "speed": 1.02},  # bright, friendly (FRIDAY)
}
_EDGE_PROFILES = {
    "edith":  "en-US-AriaNeural",
    "jarvis": "en-US-GuyNeural",
    "friday": "en-US-JennyNeural",
}
_SAPI_PROFILES = {
    "edith":  {"rate": 0,  "volume": 92, "hints": ("zira", "female", "english")},
    "jarvis": {"rate": -1, "volume": 95, "hints": ("david", "male",   "english")},
    "friday": {"rate": 1,  "volume": 90, "hints": ("zira", "female", "english")},
}
_EDGE_RATE = "+5%"

# Sentence-boundary pattern for smart chunking within TTS
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')

_THREAD_PRIORITY_BELOW_NORMAL = -1


def _set_thread_priority(priority: int) -> None:
    try:
        handle = ctypes.windll.kernel32.GetCurrentThread()
        ctypes.windll.kernel32.SetThreadPriority(handle, priority)
    except Exception:
        pass


def _download_file(url: str, dest: Path) -> bool:
    """Download a file with a progress indicator. Returns True on success."""
    import urllib.request
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        def _reporthook(count, block, total):
            pct = min(100, int(count * block * 100 / max(total, 1)))
            print(f"\r  Downloading {dest.name}: {pct}%", end="", flush=True)
        urllib.request.urlretrieve(url, tmp, reporthook=_reporthook)
        print()
        tmp.rename(dest)
        return True
    except Exception as e:
        print(f"\n  Download failed: {e}")
        return False


def _ensure_edge_tts() -> bool:
    try:
        import edge_tts  # noqa
        return True
    except ImportError:
        pass
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "edge-tts"],
            timeout=60,
        )
        import edge_tts  # noqa
        return True
    except Exception:
        return False


def _smart_chunk(text: str, max_chars: int = 220) -> list[str]:
    """
    Split text into natural-sounding TTS chunks at sentence boundaries.
    Keeps chunks under max_chars for low synthesis latency per chunk.
    """
    # First split at sentence endings
    raw = _SENTENCE_END.split(text.strip())
    chunks: list[str] = []
    current = ""
    for part in raw:
        part = part.strip()
        if not part:
            continue
        if current and len(current) + 1 + len(part) > max_chars:
            chunks.append(current)
            current = part
        else:
            current = (current + " " + part).strip() if current else part
    if current:
        chunks.append(current)
    return chunks or [text.strip()]


class AudioService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._speaking = False
        self._fallback_volume = 50
        self._fallback_muted = False
        self._speech_queue: queue.Queue[str | None] = queue.Queue()
        self._queue_worker: threading.Thread | None = None
        self._queue_lock = threading.Lock()
        self._speaker = None
        self._active_profile = "edith"
        self._stop_event = threading.Event()

        # Engine state
        self._kokoro_onnx: object | None = None   # KokoroOnnx instance
        self._kokoro_onnx_ready = False
        self._edge_tts_ok = False

        # Active voice settings
        self._onnx_voice = _KOKORO_ONNX_PROFILES["edith"]["voice"]
        self._onnx_speed = _KOKORO_ONNX_PROFILES["edith"]["speed"]

        # ── Engine 1: Kokoro ONNX (primary — Kokoro quality, CPU, no GPU lag) ─
        threading.Thread(target=self._init_kokoro_onnx, daemon=True).start()

        # ── Engine 2: Edge TTS (online fallback — Azure Neural voices) ────────
        threading.Thread(target=self._init_edge_tts, daemon=True).start()

        # ── Engine 3: Windows SAPI (offline fallback, always zero-cost) ───────
        if win32com is not None:
            try:
                self._speaker = win32com.client.Dispatch("SAPI.SpVoice")
                self.set_voice_profile("edith")
            except Exception:
                self._speaker = None

    # ── Engine initializers ───────────────────────────────────────────────────

    def _init_kokoro_onnx(self) -> None:
        """
        Download Kokoro ONNX model files if needed, then initialize the engine.
        Runs in a background thread so startup is never blocked.
        """
        try:
            from kokoro_onnx import Kokoro as _KokoroOnnx
        except ImportError:
            return  # package not installed — fall back to edge-tts

        # Download model files if missing (~300 MB total, one-time only)
        if not _KOKORO_ONNX_MODEL.exists():
            print("[EDITH] Downloading Kokoro ONNX model (~300 MB, one-time)...")
            if not _download_file(_KOKORO_ONNX_MODEL_URL, _KOKORO_ONNX_MODEL):
                return
        if not _KOKORO_ONNX_VOICES.exists():
            print("[EDITH] Downloading Kokoro voice embeddings (~10 MB)...")
            if not _download_file(_KOKORO_ONNX_VOICES_URL, _KOKORO_ONNX_VOICES):
                return

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._kokoro_onnx = _KokoroOnnx(
                    str(_KOKORO_ONNX_MODEL),
                    str(_KOKORO_ONNX_VOICES),
                )
            self._kokoro_onnx_ready = True
            # Pre-warm: synthesize a silent phrase so first real call is instant
            threading.Thread(target=self._warmup_kokoro_onnx, daemon=True).start()
        except Exception:
            self._kokoro_onnx = None

    def _warmup_kokoro_onnx(self) -> None:
        """Single silent synthesis to JIT-warm the ONNX runtime."""
        if self._kokoro_onnx is None:
            return
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._kokoro_onnx.create(
                    "Ready.", voice=self._onnx_voice,
                    speed=self._onnx_speed, lang="en-us",
                )
        except Exception:
            pass

    def _init_edge_tts(self) -> None:
        self._edge_tts_ok = _ensure_edge_tts()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def tts_enabled(self) -> bool:
        return self._kokoro_onnx_ready or self._edge_tts_ok or self._speaker is not None

    @property
    def system_audio_enabled(self) -> bool:
        return AudioUtilities is not None and IAudioEndpointVolume is not None and CLSCTX_ALL is not None

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
        if self._speaker:
            try:
                self._speaker.Speak("", 1)
            except Exception:
                pass
        self._speaking = False
        self._stop_event.clear()

    def set_voice_profile(self, profile: str) -> str:
        profile = profile.lower().strip()
        if profile not in _KOKORO_ONNX_PROFILES:
            return "Choose a voice profile: Edith, Jarvis, or Friday."
        self._active_profile = profile
        cfg = _KOKORO_ONNX_PROFILES[profile]
        self._onnx_voice = cfg["voice"]
        self._onnx_speed = cfg["speed"]

        if self._speaker is not None:
            selected = _SAPI_PROFILES.get(profile)
            if selected:
                try:
                    voices = list(self._speaker.GetVoices())
                    for hint in selected["hints"]:
                        match = next(
                            (v for v in voices if hint in v.GetDescription().lower()), None
                        )
                        if match:
                            self._speaker.Voice = match
                            break
                    self._speaker.Rate = selected["rate"]
                    self._speaker.Volume = selected["volume"]
                except Exception:
                    pass
        return f"Voice profile set to {profile.title()}."

    # ── Speech queue / loop ───────────────────────────────────────────────────

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
                spoken = False
                # Priority 1: Kokoro ONNX (best quality, lightweight, no GPU)
                if self._kokoro_onnx_ready and self._kokoro_onnx is not None:
                    self._speak_kokoro_onnx(chunk)
                    spoken = True
                # Priority 2: Edge TTS (online neural, zero local load)
                if not spoken and self._edge_tts_ok:
                    spoken = self._speak_edge_tts(chunk)
                # Priority 3: SAPI (always available offline)
                if not spoken and self._speaker is not None:
                    self._speaker.Speak(chunk)
            except Exception:
                pass
            finally:
                self._speaking = False

    # ── Kokoro ONNX engine ────────────────────────────────────────────────────

    def _speak_kokoro_onnx(self, text: str) -> None:
        """
        Kokoro ONNX — same voice quality as full Kokoro-82M, but:
          • Runs on ONNX Runtime (CPU-only, no GPU at all)
          • ~5x faster synthesis than PyTorch on CPU
          • ~300 MB RAM, zero VRAM — no display stutter

        Architecture:
          Thread A (synth):  text chunks → ONNX synthesis → audio_q
          Thread B (player): audio_q → sd.play(blocking=False) + sd.wait()

        The GIL is released during sd.wait(), so the VOSK mic thread runs
        freely during playback — you can always speak back to EDITH.
        """
        if _sd is None or _np is None or self._kokoro_onnx is None:
            return

        chunks = _smart_chunk(text)
        audio_q: queue.Queue = queue.Queue(maxsize=4)

        def _synthesize() -> None:
            _set_thread_priority(_THREAD_PRIORITY_BELOW_NORMAL)
            for chunk in chunks:
                if self._stop_event.is_set():
                    break
                chunk = chunk.strip()
                if not chunk:
                    continue
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        samples, sr = self._kokoro_onnx.create(
                            chunk,
                            voice=self._onnx_voice,
                            speed=self._onnx_speed,
                            lang="en-us",
                        )
                    if samples is not None and len(samples) > 0:
                        audio_q.put((samples, sr))
                except Exception:
                    pass
            audio_q.put(None)  # sentinel

        threading.Thread(target=_synthesize, daemon=True).start()

        while True:
            if self._stop_event.is_set():
                break
            try:
                item = audio_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            if self._stop_event.is_set():
                break
            samples, sr = item
            # Non-blocking play → sd.wait() releases GIL → mic thread stays live
            _sd.play(samples, samplerate=sr, blocking=False)
            _sd.wait()

    # ── Edge TTS fallback ─────────────────────────────────────────────────────

    def _speak_edge_tts(self, text: str) -> bool:
        try:
            import edge_tts
        except ImportError:
            return False

        voice = _EDGE_PROFILES.get(self._active_profile, "en-US-AriaNeural")

        async def _fetch() -> bytes:
            communicate = edge_tts.Communicate(text, voice, rate=_EDGE_RATE)
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
                return False

            if _sd is not None and _np is not None and raw[:4] == b"RIFF":
                pos = raw.find(b"data")
                if pos != -1:
                    pcm = _np.frombuffer(raw[pos + 8:], dtype=_np.int16).astype(_np.float32) / 32768.0
                    _sd.play(pcm, samplerate=24000, blocking=False)
                    _sd.wait()
                    return True

            return self._play_mp3_bytes(raw)
        except Exception:
            return False

    def _play_mp3_bytes(self, data: bytes) -> bool:
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(data)
                tmp = f.name
            mci = ctypes.windll.winmm.mciSendStringW
            mci(f'open "{tmp}" type mpegvideo alias edith_tts', None, 0, 0)
            mci("play edith_tts wait", None, 0, 0)
            mci("close edith_tts", None, 0, 0)
            os.unlink(tmp)
            return True
        except Exception:
            return False

    # ── Volume / system audio controls ────────────────────────────────────────

    def adjust_volume(self, delta: float) -> str:
        endpoint = self._get_endpoint_volume()
        if endpoint is not None:
            current = endpoint.GetMasterVolumeLevelScalar()
            new_volume = max(0.0, min(1.0, current + delta))
            endpoint.SetMasterVolumeLevelScalar(new_volume, None)
            return f"Volume is now {int(new_volume * 100)}%."
        return "System volume controls are unavailable."

    def set_volume(self, level: int) -> str:
        endpoint = self._get_endpoint_volume()
        bounded = max(0, min(100, level))
        if endpoint is not None:
            endpoint.SetMasterVolumeLevelScalar(bounded / 100.0, None)
            return f"Volume set to {bounded}%."
        return "System volume controls are unavailable."

    def mute(self) -> str:
        endpoint = self._get_endpoint_volume()
        if endpoint is not None:
            endpoint.SetMute(1, None)
            return "Volume muted."
        return "System volume controls are unavailable."

    def unmute(self) -> str:
        endpoint = self._get_endpoint_volume()
        if endpoint is not None:
            endpoint.SetMute(0, None)
            return "Volume unmuted."
        return "System volume controls are unavailable."

    def _get_endpoint_volume(self):
        if not self.system_audio_enabled or POINTER is None or cast is None:
            return None
        try:
            device = AudioUtilities.GetSpeakers()
            endpoint = getattr(device, "EndpointVolume", None)
            if endpoint is not None:
                return endpoint
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return cast(interface, POINTER(IAudioEndpointVolume))
        except Exception:
            return None
