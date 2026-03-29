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
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "phi3"))
    planner_model: str = field(default_factory=lambda: os.getenv("EDITH_PLANNER_MODEL", "phi3"))
    creative_model: str = field(default_factory=lambda: os.getenv("EDITH_CREATIVE_MODEL", "mistral"))
    fast_model: str = field(default_factory=lambda: os.getenv("EDITH_FAST_MODEL", "phi3"))
    ollama_executable: str = field(default_factory=lambda: os.getenv("OLLAMA_EXECUTABLE", "ollama"))
    ollama_models_path: str = field(default_factory=lambda: os.getenv("OLLAMA_MODELS", r"F:\OllamaModels"))
    wake_word: str = field(default_factory=lambda: os.getenv("EDITH_WAKE_WORD", "edith"))
    voice_command_timeout: int = field(default_factory=lambda: int(os.getenv("EDITH_VOICE_TIMEOUT", "6")))
    auto_listen: bool = field(default_factory=lambda: os.getenv("EDITH_AUTO_LISTEN", "1") != "0")
    require_wake_word: bool = field(default_factory=lambda: os.getenv("EDITH_REQUIRE_WAKE_WORD", "0") == "1")
    lightweight_mode: bool = field(default_factory=lambda: os.getenv("EDITH_LIGHTWEIGHT_MODE", "1") != "0")
    auto_pull_models: bool = field(default_factory=lambda: os.getenv("EDITH_AUTO_PULL_MODELS", "1") != "0")
    spotify_app_path: str = field(
        default_factory=lambda: os.getenv(
            "SPOTIFY_APP_PATH",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\spotify.exe"),
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
    contacts: dict[str, str] = field(
        default_factory=lambda: {
            "primary_contact": "+10000000001",
            "friend_alias": "+10000000001",
            "secondary_contact": "+10000000002",
            
            "friend_alias": "+10000000001",
            "friend_alias": "+10000000001",
            
            "me": "+10000000003",
        }
    )
    whatsapp_display_names: dict[str, str] = field(
        default_factory=lambda: {
            "primary_contact": "Primary Contact",
            "friend_alias": "Primary Contact",
            "friend_alias": "Primary Contact",
            "friend_alias": "Primary Contact",
            "secondary_contact": "Secondary Contact",
        }
    )
