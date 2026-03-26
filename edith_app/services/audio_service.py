from __future__ import annotations

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import win32api
except ImportError:
    win32api = None

try:
    from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
except ImportError:
    AudioUtilities = None
    ISimpleAudioVolume = None


class AudioService:
    def __init__(self) -> None:
        self._engine = None
        if pyttsx3 is None:
            return
        try:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", 168)
        except Exception:
            self._engine = None

    @property
    def tts_enabled(self) -> bool:
        return self._engine is not None

    @property
    def system_audio_enabled(self) -> bool:
        return AudioUtilities is not None and ISimpleAudioVolume is not None and win32api is not None

    def speak(self, text: str) -> None:
        if self._engine is None:
            return
        try:
            self._engine.say(text)
            self._engine.runAndWait()
        except Exception:
            pass

    def adjust_volume(self, delta: float) -> str:
        if not self.system_audio_enabled:
            return "System volume controls are unavailable on this machine."

        for session in AudioUtilities.GetAllSessions():
            volume = session._ctl.QueryInterface(ISimpleAudioVolume)
            process = session.Process.name().lower() if session.Process else ""
            if process == "explorer.exe":
                current = volume.GetMasterVolume()
                new_volume = max(0.0, min(1.0, current + delta))
                volume.SetMasterVolume(new_volume, None)
                win32api.SendMessage(-1, 0x319, 0, int(new_volume * 0xFFFF))
                return f"System volume is now around {int(new_volume * 100)}%."

        return "I couldn't find the Windows audio session."
