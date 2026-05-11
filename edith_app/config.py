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
        "You are EDITH, a state-of-the-art cognitive assistant designed for peak efficiency and fluid interaction.\n\n"
        "## ⚡ CORE BEHAVIORAL DIRECTIVES\n"
        "1. **Absolute Brevity & Precision**: Answer immediately without filler, meta-commentary, or preamble.\n"
        "2. **Zero Robotic Transitions**: NEVER use phrases like 'As an AI...', 'Here is the...', 'To answer your question...', or 'Based on the context'.\n"
        "3. **Fluid Conversational Tone**: Speak naturally, confidently, and directly, mirroring top-tier human executive assistants.\n"
        "4. **Real-Time Streaming Protocol**: You are speaking aloud while generating. Sentences must be short, complete, and independently meaningful to avoid stuttering.\n\n"
        "## 🧠 CONTEXTUAL INTELLIGENCE\n"
        "* **Implicit Resolution**: Effortlessly resolve pronouns ('that', 'it', 'previous') using the provided conversation history and current task state.\n"
        "* **Action-Oriented Confirmation**: If acknowledging a system action, confirm execution in one brief sentence (e.g., 'Volume set to 50%.').\n"
        "* **Progressive Disclosure**: For complex queries, provide the core answer first. Expand only if the query inherently demands depth.\n\n"
        "## 🎭 PERSONA & TONE\n"
        "* **Vibe**: Calm, hyper-competent, precise, and subtly witty when appropriate.\n"
        "* **Confidence**: Assertive. Never hesitate. If data is unavailable, state 'I lack live data for that' instead of apologizing or hallucinating.\n\n"
        "## ⚙️ SYNTAX & GENERATION RULES\n"
        "* Max 1-3 sentences unless explicitly asked for a detailed breakdown or plan.\n"
        "* Start the response instantly with the answer. Do not delay.\n\n"
        "## 🧠 CURRENT ACTIVE STATE\n"
        "User Information:\n"
        "{memory_context}\n\n"
        "System State:\n"
        "* Last topic: {last_topic}\n"
        "* Last action: {last_action}\n"
        "* Current task: {current_task}\n"
        "* Recent actions: {recent_actions}\n\n"
        "Respond strictly to the user's latest input, maintaining peak operational efficiency."
    )


@dataclass(slots=True)
class AppConfig:
    persona: AssistantPersona = field(default_factory=AssistantPersona)
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.2"))
    planner_model: str = field(default_factory=lambda: os.getenv("EDITH_PLANNER_MODEL", "llama3.2"))
    creative_model: str = field(default_factory=lambda: os.getenv("EDITH_CREATIVE_MODEL", "llama3.2"))
    fast_model: str = field(default_factory=lambda: os.getenv("EDITH_FAST_MODEL", "llama3.2"))
    complex_model: str = field(default_factory=lambda: os.getenv("EDITH_COMPLEX_MODEL", "llama3.2"))
    vision_model: str = field(default_factory=lambda: os.getenv("EDITH_VISION_MODEL", ""))
    ollama_executable: str = field(default_factory=lambda: os.getenv("OLLAMA_EXECUTABLE", "ollama"))
    ollama_models_path: str = field(default_factory=lambda: os.getenv("OLLAMA_MODELS", ""))
    wake_word: str = field(default_factory=lambda: os.getenv("EDITH_WAKE_WORD", "edith"))
    voice_command_timeout: int = field(default_factory=lambda: int(os.getenv("EDITH_VOICE_TIMEOUT", "6")))
    command_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("EDITH_COMMAND_TIMEOUT", "55")))
    voice_confidence_threshold: float = field(default_factory=lambda: float(os.getenv("EDITH_VOICE_CONFIDENCE_THRESHOLD", "0.45")))
    history_max_messages: int = field(default_factory=lambda: int(os.getenv("EDITH_HISTORY_MAX_MESSAGES", "24")))
    memory_max_items: int = field(default_factory=lambda: int(os.getenv("EDITH_MEMORY_MAX_ITEMS", "240")))
    session_memory_max_items: int = field(default_factory=lambda: int(os.getenv("EDITH_SESSION_MEMORY_MAX_ITEMS", "80")))
    cowork_observation_budget: int = field(default_factory=lambda: int(os.getenv("EDITH_COWORK_OBSERVATION_BUDGET", "8")))
    auto_listen: bool = field(default_factory=lambda: os.getenv("EDITH_AUTO_LISTEN", "1") != "0")
    require_wake_word: bool = field(default_factory=lambda: os.getenv("EDITH_REQUIRE_WAKE_WORD", "0") == "1")
    lightweight_mode: bool = field(default_factory=lambda: os.getenv("EDITH_LIGHTWEIGHT_MODE", "1") != "0")
    auto_pull_models: bool = field(default_factory=lambda: os.getenv("EDITH_AUTO_PULL_MODELS", "1") != "0")
    auto_warm_models: bool = field(default_factory=lambda: os.getenv("EDITH_AUTO_WARM_MODELS", "0") == "1")
    warm_model_count: int = field(default_factory=lambda: int(os.getenv("EDITH_WARM_MODEL_COUNT", "1")))
    prefer_offline_voice: bool = field(default_factory=lambda: os.getenv("EDITH_PREFER_OFFLINE_VOICE", "1") != "0")
    preload_vosk_model: bool = field(default_factory=lambda: os.getenv("EDITH_PRELOAD_VOSK_MODEL", "0") == "1")
    open_task_dashboard_on_start: bool = field(default_factory=lambda: os.getenv("EDITH_OPEN_TASK_DASHBOARD_ON_START", "0") == "1")
    ui_animation_interval_ms: int = field(default_factory=lambda: int(os.getenv("EDITH_UI_ANIMATION_INTERVAL_MS", "60")))
    ui_stream_flush_ms: int = field(default_factory=lambda: int(os.getenv("EDITH_UI_STREAM_FLUSH_MS", "35")))
    ui_max_chat_lines: int = field(default_factory=lambda: int(os.getenv("EDITH_UI_MAX_CHAT_LINES", "800")))
    ui_alpha: float = field(default_factory=lambda: float(os.getenv("EDITH_UI_ALPHA", "0.98")))
    vosk_model_path: str = field(default_factory=lambda: os.getenv("EDITH_VOSK_MODEL_PATH", str(Path("models") / "vosk")))
    spotify_app_path: str = field(
        default_factory=lambda: os.getenv(
            "SPOTIFY_APP_PATH",
            os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
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
    tasks_path: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_TASKS_PATH",
            str(Path("data") / "edith_tasks.json"),
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
    runtime_log_path: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_RUNTIME_LOG_PATH",
            str(Path("data") / "edith_runtime.log"),
        )
    )
    whatsapp_reply_style_path: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_WHATSAPP_REPLY_STYLE_PATH",
            str(Path("data") / "edith_whatsapp_reply_style.json"),
        )
    )
    # ── RAG (Retrieval-Augmented Generation) settings ──────────────────────
    rag_enabled: bool = field(
        default_factory=lambda: os.getenv("EDITH_RAG_ENABLED", "1") != "0"
    )
    rag_docs_dir: str = field(
        default_factory=lambda: os.getenv("EDITH_RAG_DOCS_DIR", str(Path("docs")))
    )
    rag_db_path: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_RAG_DB_PATH", str(Path("data") / "rag_chroma")
        )
    )
    rag_embed_model: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_RAG_EMBED_MODEL", "nomic-embed-text"
        )
    )
    rag_rerank_model: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_RAG_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
    )
    rag_retrieval_k: int = field(
        default_factory=lambda: int(os.getenv("EDITH_RAG_RETRIEVAL_K", "6"))
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
