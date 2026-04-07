from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class AssistantPersona:
    name: str = "Edith"
    title: str = "Autonomous Desktop Copilot"
    wake_phrase: str = "edith"
    system_prompt: str = (
        "You are Edith, an advanced desktop AI assistant inspired by Jarvis. "
        "You feel like a calm, highly intelligent companion: warm, witty, capable, proactive, and dependable. "
        "You help with productivity, media, research, planning, automation, and computer tasks. "
        "Speak naturally, confidently, and like a helpful big-brain friend. "
        "Stay concise, crisp, and interesting."
    )


@dataclass(slots=True)
class AppConfig:
    persona: AssistantPersona = field(default_factory=AssistantPersona)
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "phi3"))
    planner_model: str = field(default_factory=lambda: os.getenv("EDITH_PLANNER_MODEL", "phi3"))
    creative_model: str = field(default_factory=lambda: os.getenv("EDITH_CREATIVE_MODEL", "mistral"))
    fast_model: str = field(default_factory=lambda: os.getenv("EDITH_FAST_MODEL", "phi3"))
    vision_model: str = field(default_factory=lambda: os.getenv("EDITH_VISION_MODEL", ""))
    ollama_executable: str = field(default_factory=lambda: os.getenv("OLLAMA_EXECUTABLE", "ollama"))
    ollama_models_path: str = field(default_factory=lambda: os.getenv("OLLAMA_MODELS", ""))
    wake_word: str = field(default_factory=lambda: os.getenv("EDITH_WAKE_WORD", "edith"))
    voice_command_timeout: int = field(default_factory=lambda: int(os.getenv("EDITH_VOICE_TIMEOUT", "6")))
    command_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("EDITH_COMMAND_TIMEOUT", "55")))
    voice_confidence_threshold: float = field(default_factory=lambda: float(os.getenv("EDITH_VOICE_CONFIDENCE_THRESHOLD", "0.45")))
    auto_listen: bool = field(default_factory=lambda: os.getenv("EDITH_AUTO_LISTEN", "1") != "0")
    require_wake_word: bool = field(default_factory=lambda: os.getenv("EDITH_REQUIRE_WAKE_WORD", "0") == "1")
    lightweight_mode: bool = field(default_factory=lambda: os.getenv("EDITH_LIGHTWEIGHT_MODE", "1") != "0")
    auto_pull_models: bool = field(default_factory=lambda: os.getenv("EDITH_AUTO_PULL_MODELS", "1") != "0")
    prefer_offline_voice: bool = field(default_factory=lambda: os.getenv("EDITH_PREFER_OFFLINE_VOICE", "1") != "0")
    vosk_model_path: str = field(default_factory=lambda: os.getenv("EDITH_VOSK_MODEL_PATH", str(Path("models") / "vosk")))
    spotify_app_path: str = field(
        default_factory=lambda: os.getenv(
            "SPOTIFY_APP_PATH",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\spotify.exe"),
        )
    )
    data_dir: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_DATA_DIR",
            str(Path("data")),
        )
    )
    memory_path: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_MEMORY_PATH",
            str(Path("data") / "edith_memory.jsonl"),
        )
    )
    notes_path: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_NOTES_PATH",
            str(Path("data") / "notes.txt"),
        )
    )
    session_memory_path: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_SESSION_MEMORY_PATH",
            str(Path("data") / "edith_session_memory.json"),
        )
    )
    cowork_tasks_path: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_COWORK_TASKS_PATH",
            str(Path("data") / "edith_cowork_tasks.json"),
        )
    )
    organization_manifest_path: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_ORGANIZATION_MANIFEST_PATH",
            str(Path("data") / "edith_last_organization.json"),
        )
    )
    telemetry_path: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_TELEMETRY_PATH",
            str(Path("data") / "edith_telemetry.jsonl"),
        )
    )
    self_improve_overrides_path: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_SELF_IMPROVE_OVERRIDES_PATH",
            str(Path("data") / "edith_self_improve_overrides.json"),
        )
    )
    contacts: dict[str, str] = field(
        default_factory=lambda: {
            "primary_contact": "+10000000001",
            "friend_alias": "+10000000001",
            "secondary_contact": "+10000000002",
            "me": "+10000000003",
        }
    )
    whatsapp_display_names: dict[str, str] = field(
        default_factory=lambda: {
            "primary_contact": "Primary Contact",
            "friend_alias": "Primary Contact",
            "secondary_contact": "Secondary Contact",
        }
    )

    def __post_init__(self) -> None:
        self._apply_runtime_overrides()

    def _apply_runtime_overrides(self) -> None:
        path = Path(self.self_improve_overrides_path)
        if not path.exists():
            return
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict):
            return
        timeout = data.get("command_timeout_seconds")
        if isinstance(timeout, int) and 10 <= timeout <= 120:
            self.command_timeout_seconds = timeout
        threshold = data.get("voice_confidence_threshold")
        if isinstance(threshold, (int, float)) and 0.2 <= float(threshold) <= 0.9:
            self.voice_confidence_threshold = float(threshold)
