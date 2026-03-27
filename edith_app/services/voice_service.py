from __future__ import annotations

try:
    import speech_recognition as sr
except ImportError:
    sr = None


class VoiceService:
    def __init__(self) -> None:
        self._recognizer = sr.Recognizer() if sr is not None else None
        self._ambient_calibrated = False
        if self._recognizer is not None:
            self._recognizer.dynamic_energy_threshold = True
            self._recognizer.energy_threshold = 250
            self._recognizer.pause_threshold = 0.9
            self._recognizer.non_speaking_duration = 0.35

    @property
    def enabled(self) -> bool:
        return self._recognizer is not None

    def listen_once(self) -> str:
        if sr is None or self._recognizer is None:
            return ""
        try:
            with sr.Microphone() as source:
                self._prepare_source(source, pause_threshold=1.1)
                audio = self._recognizer.listen(source, phrase_time_limit=5)
            return self._normalize(self._recognizer.recognize_google(audio, language="en-us"))
        except Exception:
            return ""

    def listen_for_command(self, timeout: int = 7, phrase_time_limit: int = 8) -> str:
        if sr is None or self._recognizer is None:
            return ""
        try:
            with sr.Microphone() as source:
                self._prepare_source(source, pause_threshold=0.9)
                audio = self._recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=min(phrase_time_limit, 7),
                )
            return self._normalize(self._recognizer.recognize_google(audio, language="en-us"))
        except Exception:
            return ""

    def listen_for_interrupt(self) -> str:
        if sr is None or self._recognizer is None:
            return ""
        try:
            with sr.Microphone() as source:
                self._prepare_source(source, pause_threshold=0.45)
                audio = self._recognizer.listen(
                    source,
                    timeout=0.8,
                    phrase_time_limit=2,
                )
            return self._normalize(self._recognizer.recognize_google(audio, language="en-us"))
        except Exception:
            return ""

    def _prepare_source(self, source: object, pause_threshold: float) -> None:
        self._recognizer.pause_threshold = pause_threshold
        self._recognizer.non_speaking_duration = 0.35
        if not self._ambient_calibrated:
            self._recognizer.adjust_for_ambient_noise(source, duration=0.2)
            self._ambient_calibrated = True

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
