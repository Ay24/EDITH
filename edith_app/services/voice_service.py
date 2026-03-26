from __future__ import annotations

try:
    import speech_recognition as sr
except ImportError:
    sr = None


class VoiceService:
    def __init__(self) -> None:
        self._recognizer = sr.Recognizer() if sr is not None else None
        self._ambient_calibrated = False

    @property
    def enabled(self) -> bool:
        return self._recognizer is not None

    def listen_once(self) -> str:
        if sr is None or self._recognizer is None:
            return ""
        try:
            with sr.Microphone() as source:
                self._recognizer.pause_threshold = 1.2
                if not self._ambient_calibrated:
                    self._recognizer.adjust_for_ambient_noise(source, duration=0.15)
                    self._ambient_calibrated = True
                audio = self._recognizer.listen(source)
            return self._recognizer.recognize_google(audio, language="en-us")
        except Exception:
            return ""

    def listen_for_command(self, timeout: int = 7, phrase_time_limit: int = 8) -> str:
        if sr is None or self._recognizer is None:
            return ""
        try:
            with sr.Microphone() as source:
                self._recognizer.pause_threshold = 1.0
                if not self._ambient_calibrated:
                    self._recognizer.adjust_for_ambient_noise(source, duration=0.15)
                    self._ambient_calibrated = True
                audio = self._recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=min(phrase_time_limit, 6),
                )
            return self._recognizer.recognize_google(audio, language="en-us")
        except Exception:
            return ""
