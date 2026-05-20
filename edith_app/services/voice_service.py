from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Callable

from edith_app.config import AppConfig
from edith_app.voice.streaming_intent import StreamingIntentDetector
from edith_app.voice.wake_engine import WakeEngine

try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    import pyaudio
except ImportError:
    pyaudio = None

import warnings as _warnings_vs
_warnings_vs.filterwarnings(
    "ignore",
    message=".*dropout option adds dropout after all but last recurrent layer.*",
    category=UserWarning,
)
_warnings_vs.filterwarnings("ignore", module="torch.*")

try:
    from vosk import KaldiRecognizer, Model
except Exception:
    KaldiRecognizer = None
    Model = None






class VoiceService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._recognizer = sr.Recognizer() if sr is not None else None
        self._ambient_calibrated = False
        self._capture_count = 0
        self._prefer_offline = config.prefer_offline_voice
        self._vosk_model = None
        self._vosk_model_path = config.vosk_model_path
        self._vosk_checked = False
        self._pause_threshold = max(0.25, float(config.voice_pause_threshold))
        self._non_speaking_duration = max(0.12, float(config.voice_non_speaking_duration))
        self._phrase_time_limit = max(4, int(config.voice_phrase_time_limit))
        self._skip_llm_normalize = bool(config.skip_llm_stt_normalize)
        self.on_interrupt = None
        self.on_partial: Callable[[str], None] | None = None
        self.on_wake: Callable[[str], None] | None = None
        self.on_energy: Callable[[float], None] | None = None

        self._mic_stream = None
        self._pyaudio_instance = None
        self._transcription_queue: queue.Queue[str] = queue.Queue()
        self._intent_queue: queue.Queue[str] = queue.Queue()
        self._partial_queue: queue.Queue[tuple[str, float]] = queue.Queue()
        self._is_recording = False
        self._record_thread: threading.Thread | None = None
        self.agent = None
        self._command_armed = True
        if config.wake_engine_enabled and config.always_listen_wake:
            self._command_armed = False
        self._wake_engine: WakeEngine | None = None
        self._streaming: StreamingIntentDetector | None = None
        if config.streaming_intent_enabled:
            self._streaming = StreamingIntentDetector(
                min_words=config.streaming_intent_min_words,
                stable_ticks=3 if config.ultra_latency else 4,
            )
        if config.wake_engine_enabled:
            self._wake_engine = WakeEngine(
                keywords=config.wake_keyword_list(),
                backend=config.wake_backend,
                openwakeword_models=config.openwakeword_model_list(),
                score_threshold=config.wake_score_threshold,
            )
            self._wake_engine.set_callback(self._on_wake_detected)
        
        if self._recognizer is not None:
            self._recognizer.dynamic_energy_threshold = True
            self._recognizer.energy_threshold = 250
            self._recognizer.pause_threshold = self._pause_threshold
            self._recognizer.non_speaking_duration = self._non_speaking_duration
            
        if config.preload_vosk_model:
            self._ensure_vosk_model()

    def set_agent(self, agent) -> None:
        """Inject the LLM agent for NLP-powered STT correction."""
        self.agent = agent

    def arm_command_window(self) -> None:
        """After wake word, accept utterances without repeating the wake phrase."""
        self._command_armed = True
        if self._streaming:
            self._streaming.reset()

    def disarm_command_window(self) -> None:
        if self._config.always_listen_wake and self._config.wake_engine_enabled:
            self._command_armed = False
        else:
            self._command_armed = True

    def _on_wake_detected(self, _source: str) -> None:
        self.arm_command_window()
        if self.on_wake:
            try:
                self.on_wake(_source)
            except Exception:
                pass

    def _strip_wake_prefix(self, text: str) -> str:
        lowered = text.lower().strip()
        for kw in self._config.wake_keyword_list():
            if lowered == kw:
                return ""
            if lowered.startswith(kw + " "):
                return lowered[len(kw) :].strip()
        return lowered

    def start_session(self) -> None:
        """Start optional low-latency voice resources for active voice mode."""
        if pyaudio is not None:
            self._start_persistent_stream()

    def stop_session(self) -> None:
        """Release microphone and streaming resources when voice mode is disabled."""
        self._stop_persistent_stream()
        if hasattr(self, "_cached_mic") and self._cached_mic is not None:
            try:
                self._cached_mic.__exit__(None, None, None)
            except Exception:
                pass
            self._cached_mic = None

    @property
    def enabled(self) -> bool:
        return self._recognizer is not None or (self._vosk_model is not None and self._mic_stream is not None)

    def listen_once(self) -> str:
        return self.listen_for_command(timeout=None)

    def listen_for_command(self, timeout: int | None = 7, phrase_time_limit: int | None = None) -> str:
        phrase_limit = self._phrase_time_limit if phrase_time_limit is None else min(phrase_time_limit, self._phrase_time_limit)
        if not self._is_recording:
            return self._capture(
                timeout=timeout,
                phrase_time_limit=phrase_limit,
                pause_threshold=self._pause_threshold,
            )

        try:
            early = self._intent_queue.get_nowait()
            if early:
                return early
        except queue.Empty:
            pass

        try:
            while not self._transcription_queue.empty():
                self._transcription_queue.get_nowait()
            while not self._intent_queue.empty():
                self._intent_queue.get_nowait()

            deadline = time.monotonic() + (timeout if timeout is not None else 7)
            while time.monotonic() < deadline:
                remaining = max(0.05, deadline - time.monotonic())
                try:
                    return self._intent_queue.get(timeout=min(0.12, remaining))
                except queue.Empty:
                    pass
                try:
                    return self._transcription_queue.get(timeout=min(0.12, remaining))
                except queue.Empty:
                    continue
            return ""
        except Exception:
            return ""

    def poll_partial(self) -> tuple[str, float] | None:
        try:
            return self._partial_queue.get_nowait()
        except queue.Empty:
            return None

    def listen_for_interrupt(self) -> str:
        # For interrupt, we check the queue immediately for any recent transcription
        try:
            return self._transcription_queue.get_nowait()
        except queue.Empty:
            return ""

    def _start_persistent_stream(self) -> None:
        if self._pyaudio_instance is not None or self._is_recording:
            return
        
        model = self._ensure_vosk_model()
        if not model:
            return
            
        try:
            self._pyaudio_instance = pyaudio.PyAudio()
            self._mic_stream = self._pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=8000
            )
            self._is_recording = True
            self._record_thread = threading.Thread(target=self._transcription_loop, daemon=True)
            self._record_thread.start()
        except Exception:
            self._is_recording = False
            if self._pyaudio_instance:
                self._pyaudio_instance.terminate()
                self._pyaudio_instance = None

    def _stop_persistent_stream(self) -> None:
        self._is_recording = False
        if self._mic_stream is not None:
            try:
                self._mic_stream.stop_stream()
            except Exception:
                pass
            try:
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None
        if self._pyaudio_instance is not None:
            try:
                self._pyaudio_instance.terminate()
            except Exception:
                pass
            self._pyaudio_instance = None
        self._record_thread = None

    def _transcription_loop(self) -> None:
        if not self._vosk_model or not self._mic_stream:
            return
            
        recognizer = KaldiRecognizer(self._vosk_model, 16000)
        while self._is_recording:
            try:
                data = self._mic_stream.read(4000, exception_on_overflow=False)
                if len(data) == 0:
                    continue
                
                energy = WakeEngine.rms_energy(data)
                if self.on_energy:
                    try:
                        self.on_energy(min(1.0, energy / 4000.0))
                    except Exception:
                        pass

                if self._wake_engine is not None:
                    self._wake_engine.feed_pcm16(data)

                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").strip()
                    if text:
                        self._handle_final_transcript(text)
                else:
                    partial = json.loads(recognizer.PartialResult())
                    partial_text = partial.get("partial", "").strip()
                    if self._wake_engine is not None:
                        self._wake_engine.feed_partial_transcript(partial_text)
                    if partial_text:
                        self._partial_queue.put((partial_text, energy))
                        if self.on_partial:
                            try:
                                self.on_partial(partial_text)
                            except Exception:
                                pass
                        if self._streaming and self._command_armed:
                            early = self._streaming.feed_partial(partial_text)
                            if early:
                                self._intent_queue.put(self._normalize(early))
                    if len(partial_text) > 2 and self.on_interrupt:
                        self.on_interrupt()
            except Exception:
                time.sleep(0.02)
                continue

    def _get_microphone(self):
        if not hasattr(self, '_cached_mic') or self._cached_mic is None:
            self._cached_mic = sr.Microphone()
            self._cached_mic.__enter__() # Keep stream open permanently to avoid Windows Audio handle exhaustion
        return self._cached_mic

    def _capture(self, timeout: int | None, phrase_time_limit: int, pause_threshold: float) -> str:
        if sr is None or self._recognizer is None:
            return ""
        try:
            source = self._get_microphone()
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
        self._recognizer.non_speaking_duration = self._non_speaking_duration
        should_recalibrate = (self._capture_count % 24 == 0 and self._capture_count > 0)
        if not self._ambient_calibrated or should_recalibrate:
            calibrate_s = 0.08 if getattr(self._config, "ultra_latency", False) else 0.2
            self._recognizer.adjust_for_ambient_noise(source, duration=calibrate_s)
            self._ambient_calibrated = True

    def estimate_confidence(self, text: str) -> float:
        cleaned = " ".join(text.strip().split()).lower()
        if not cleaned:
            return 0.0
            
        # Explicit high confidence for clear confirmation/negation
        if cleaned in {"yes", "no", "yeah", "yep", "nope", "okay", "ok", "cancel", "stop"}:
            return 0.95
            
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
            self._recognizer.pause_threshold = self._pause_threshold
            self._recognizer.non_speaking_duration = self._non_speaking_duration
            self._ambient_calibrated = False
            if hasattr(self, '_cached_mic') and self._cached_mic is not None:
                try:
                    self._cached_mic.__exit__(None, None, None)
                except Exception:
                    pass
                self._cached_mic = None
        except Exception:
            pass

    def _recognize(self, audio: object) -> str:
        vosk_model = self._ensure_vosk_model() if self._prefer_offline else None
        if self._prefer_offline and vosk_model is not None:
            text = self._recognize_vosk(audio)
            if text:
                return text
                
        if self._recognizer is None:
            return ""
        try:
            return self._recognizer.recognize_google(audio, language="en-us")
        except Exception:
            if self._ensure_vosk_model() is not None:
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
            import warnings as _w
            with _w.catch_warnings():
                _w.simplefilter("ignore")  # Suppresses PyTorch RNN dropout warning at instantiation
                return Model(str(path))
        except Exception:
            return None

    def _handle_final_transcript(self, text: str) -> None:
        normalized = self._normalize(text)
        if not normalized:
            return
        if self._wake_engine and self._config.wake_engine_enabled and not self._command_armed:
            if any(kw in normalized.split() or normalized.startswith(kw) for kw in self._config.wake_keyword_list()):
                self.arm_command_window()
                stripped = self._strip_wake_prefix(normalized)
                if stripped:
                    normalized = stripped
                else:
                    return
            else:
                return

        if self._config.require_wake_word:
            stripped = self._strip_wake_prefix(normalized)
            if not stripped:
                return
            normalized = stripped

        if self._streaming:
            early = self._streaming.feed_final(normalized)
            if early:
                self._intent_queue.put(early)
                return
        self._transcription_queue.put(normalized)

    def _ensure_vosk_model(self) -> object | None:
        if self._vosk_checked:
            return self._vosk_model
        self._vosk_checked = True
        self._vosk_model = self._load_vosk_model(self._vosk_model_path)
        return self._vosk_model


    def _normalize(self, text: str) -> str:
        lowered = " ".join(text.strip().split()).lower()
        if not lowered:
            return lowered
            
        replacements = {
            "what's app": "whatsapp",
            "you tube": "youtube",
            "wi fi": "wifi",
            "blue tooth": "bluetooth",
        }
        for wrong, right in replacements.items():
            lowered = lowered.replace(wrong, right)
            
        # Optional LLM homophone pass — disabled in ultra-latency mode (adds 200–500ms).
        word_count = len(lowered.split())
        if (
            not self._skip_llm_normalize
            and word_count > 6
            and getattr(self, "agent", None) is not None
            and self.agent.enabled
        ):
            try:
                import concurrent.futures
                def _do_nlp():
                    return self.agent.specialist_reply(
                        prompt=f"Fix spelling/grammar/homophones in this voice transcript. Return ONLY the corrected text: '{lowered}'",
                        history=[],
                        specialist_instruction="You are a silent NLP corrector. Return exact corrected text only.",
                        prefer_fast=True
                    )
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_do_nlp)
                    corrected = future.result(timeout=0.5).strip()
                    if corrected and len(corrected) < len(lowered) * 2.0:
                        corrected = corrected.strip("'\"")
                        return corrected.lower()
            except Exception:
                pass  # Timeout — silently use raw text
                
        return lowered

