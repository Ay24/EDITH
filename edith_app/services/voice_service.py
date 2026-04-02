from __future__ import annotations

import json
from pathlib import Path

from edith_app.config import AppConfig

try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    from vosk import KaldiRecognizer, Model
except ImportError:
    KaldiRecognizer = None
    Model = None


class VoiceService:
    def __init__(self, config: AppConfig) -> None:
        self._recognizer = sr.Recognizer() if sr is not None else None
        self._ambient_calibrated = False
        self._capture_count = 0
        self._prefer_offline = config.prefer_offline_voice
        self._vosk_model = self._load_vosk_model(config.vosk_model_path)
        if self._recognizer is not None:
            self._recognizer.dynamic_energy_threshold = True
            self._recognizer.energy_threshold = 250
            self._recognizer.pause_threshold = 1.0
            self._recognizer.non_speaking_duration = 0.35

    @property
    def enabled(self) -> bool:
        return self._recognizer is not None

    def listen_once(self) -> str:
        return self._capture(timeout=None, phrase_time_limit=6, pause_threshold=1.1)

    def listen_for_command(self, timeout: int = 7, phrase_time_limit: int = 8) -> str:
        return self._capture(timeout=timeout, phrase_time_limit=min(phrase_time_limit, 8), pause_threshold=1.0)

    def listen_for_interrupt(self) -> str:
        return self._capture(timeout=0.8, phrase_time_limit=2, pause_threshold=0.45)

    def _capture(self, timeout: int | None, phrase_time_limit: int, pause_threshold: float) -> str:
        if sr is None or self._recognizer is None:
            return ""
        try:
            with sr.Microphone() as source:
                self._prepare_source(source, pause_threshold)
                audio = self._recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
            self._capture_count += 1
            return self._normalize(self._recognize(audio))
        except Exception:
            self._recover_recognizer_state()
            return ""

    def _prepare_source(self, source: object, pause_threshold: float) -> None:
        self._recognizer.pause_threshold = pause_threshold
        self._recognizer.non_speaking_duration = 0.35
        should_recalibrate = (self._capture_count % 24 == 0 and self._capture_count > 0)
        if not self._ambient_calibrated or should_recalibrate:
            self._recognizer.adjust_for_ambient_noise(source, duration=0.2)
            self._ambient_calibrated = True

    def estimate_confidence(self, text: str) -> float:
        cleaned = " ".join(text.strip().split()).lower()
        if not cleaned:
            return 0.0
        words = cleaned.split()
        if len(words) == 1 and len(words[0]) <= 2:
            return 0.15
        filler = {"uh", "um", "hmm", "ah", "er"}
        filler_hits = sum(1 for word in words if word in filler)
        confidence = 0.55
        confidence += min(0.25, len(words) * 0.04)
        confidence -= min(0.25, filler_hits * 0.08)
        if cleaned.endswith(("to", "for", "and", "then", "the", "a", "an")):
            confidence -= 0.2
        return max(0.0, min(1.0, confidence))

    def _recover_recognizer_state(self) -> None:
        if sr is None:
            return
        try:
            self._recognizer = sr.Recognizer()
            self._recognizer.dynamic_energy_threshold = True
            self._recognizer.energy_threshold = 250
            self._recognizer.pause_threshold = 1.0
            self._recognizer.non_speaking_duration = 0.35
            self._ambient_calibrated = False
        except Exception:
            pass

    def _recognize(self, audio: object) -> str:
        if self._prefer_offline and self._vosk_model is not None:
            text = self._recognize_vosk(audio)
            if text:
                return text
        if self._recognizer is None:
            return ""
        try:
            return self._recognizer.recognize_google(audio, language="en-us")
        except Exception:
            if self._vosk_model is not None:
                return self._recognize_vosk(audio)
            return ""

    def _recognize_vosk(self, audio: object) -> str:
        if self._vosk_model is None or KaldiRecognizer is None:
            return ""
        try:
            recognizer = KaldiRecognizer(self._vosk_model, 16_000)
            recognizer.AcceptWaveform(audio.get_raw_data(convert_rate=16_000, convert_width=2))
            result = json.loads(recognizer.FinalResult())
            return result.get("text", "")
        except Exception:
            return ""

    def _load_vosk_model(self, model_path: str) -> object | None:
        if Model is None:
            return None
        path = Path(model_path).expanduser()
        if not path.exists():
            return None
        try:
            return Model(str(path))
        except Exception:
            return None

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
