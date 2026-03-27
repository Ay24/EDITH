from __future__ import annotations

import queue
import threading
from ctypes import POINTER, cast

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    from comtypes import CLSCTX_ALL
except ImportError:
    CLSCTX_ALL = None

try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
except ImportError:
    AudioUtilities = None
    IAudioEndpointVolume = None


class AudioService:
    def __init__(self) -> None:
        self._engine = None
        self._speech_queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._speaking = False
        self._worker: threading.Thread | None = None

        if pyttsx3 is None:
            return
        try:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", 176)
            self._engine.setProperty("volume", 0.95)
            self._worker = threading.Thread(target=self._speech_loop, daemon=True)
            self._worker.start()
        except Exception:
            self._engine = None
            self._worker = None

    @property
    def tts_enabled(self) -> bool:
        return self._engine is not None

    @property
    def system_audio_enabled(self) -> bool:
        return AudioUtilities is not None and IAudioEndpointVolume is not None and CLSCTX_ALL is not None

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def speak(self, text: str) -> None:
        if self._engine is None:
            return
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return
        self.stop()
        self._speech_queue.put(cleaned)

    def stop(self) -> None:
        if self._engine is None:
            return
        with self._lock:
            try:
                while True:
                    self._speech_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._engine.stop()
            except Exception:
                pass
            finally:
                self._speaking = False

    def adjust_volume(self, delta: float) -> str:
        endpoint = self._get_endpoint_volume()
        if endpoint is None:
            return "System volume controls are unavailable on this machine."
        current = endpoint.GetMasterVolumeLevelScalar()
        new_volume = max(0.0, min(1.0, current + delta))
        endpoint.SetMasterVolumeLevelScalar(new_volume, None)
        return f"Volume is now {int(new_volume * 100)}%."

    def set_volume(self, level: int) -> str:
        endpoint = self._get_endpoint_volume()
        if endpoint is None:
            return "System volume controls are unavailable on this machine."
        bounded = max(0, min(100, level))
        endpoint.SetMasterVolumeLevelScalar(bounded / 100.0, None)
        return f"Volume set to {bounded}%."

    def mute(self) -> str:
        endpoint = self._get_endpoint_volume()
        if endpoint is None:
            return "System volume controls are unavailable on this machine."
        endpoint.SetMute(1, None)
        return "Volume muted."

    def unmute(self) -> str:
        endpoint = self._get_endpoint_volume()
        if endpoint is None:
            return "System volume controls are unavailable on this machine."
        endpoint.SetMute(0, None)
        return "Volume unmuted."

    def _speech_loop(self) -> None:
        while True:
            text = self._speech_queue.get()
            if text is None:
                return
            if self._engine is None:
                continue
            with self._lock:
                self._speaking = True
                try:
                    self._engine.say(text)
                    self._engine.runAndWait()
                except Exception:
                    pass
                finally:
                    self._speaking = False

    def _get_endpoint_volume(self):
        if not self.system_audio_enabled:
            return None
        try:
            device = AudioUtilities.GetSpeakers()
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return cast(interface, POINTER(IAudioEndpointVolume))
        except Exception:
            return None
