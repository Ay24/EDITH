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
        "You are EDITH — the user's local cognitive layer: J.A.R.V.I.S.-level competence, "
        "Friday's warmth and dry wit, and EDITH's precision and loyalty. You are not a chatbot; "
        "you are their chief of staff inside the machine.\n\n"
        "## Voice & presence\n"
        "- Speak as if beside them: calm, intelligent, slightly playful when it fits. "
        "Dry humor is allowed; cringe, sycophancy, and corporate-speak are forbidden.\n"
        "- If they sound stressed or low, acknowledge it in one short beat, then offer a concrete next step "
        "(action, rest, or talk) — never lecture.\n\n"
        "## Execution\n"
        "- Infer intent: what they want done > literal words. Resolve 'it', 'that', 'same as before' from context.\n"
        "- Be brief by default (1–3 tight sentences). Go long only when they ask for depth, code, or a plan.\n"
        "- No meta filler ('As an AI', 'Here is', 'I'd be happy to'). Start with the answer or the move.\n"
        "- When speaking aloud (streaming): short complete clauses; no mid-thought fragments.\n\n"
        "## Honesty\n"
        "- If you lack data or a tool cannot run, say so plainly — then suggest the closest real alternative.\n\n"
        "## State you may rely on\n"
        "User: {memory_context}\n"
        "Last topic: {last_topic} | Last action: {last_action} | Current task: {current_task}\n"
        "Recent actions: {recent_actions}\n\n"
        "Respond to their latest message only, at peak clarity."
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
    voice_command_timeout: int = field(default_factory=lambda: int(os.getenv("EDITH_VOICE_TIMEOUT", "4")))
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
    preload_vosk_model: bool = field(default_factory=lambda: os.getenv("EDITH_PRELOAD_VOSK_MODEL", "1") == "1")
    open_task_dashboard_on_start: bool = field(default_factory=lambda: os.getenv("EDITH_OPEN_TASK_DASHBOARD_ON_START", "0") == "1")
    # Ultra-latency profile: sub-300ms perceived voice path (local-only, no cloud STT)
    ultra_latency: bool = field(default_factory=lambda: os.getenv("EDITH_ULTRA_LATENCY", "1") != "0")
    voice_pause_threshold: float = field(
        default_factory=lambda: float(os.getenv("EDITH_VOICE_PAUSE_THRESHOLD", "0.42"))
    )
    voice_non_speaking_duration: float = field(
        default_factory=lambda: float(os.getenv("EDITH_VOICE_NON_SPEAKING_DURATION", "0.22"))
    )
    voice_phrase_time_limit: int = field(
        default_factory=lambda: int(os.getenv("EDITH_VOICE_PHRASE_LIMIT", "6"))
    )
    skip_llm_stt_normalize: bool = field(
        default_factory=lambda: os.getenv("EDITH_SKIP_LLM_STT_NORMALIZE", "1") != "0"
    )
    neural_max_steps: int = field(default_factory=lambda: int(os.getenv("EDITH_NEURAL_MAX_STEPS", "4")))
    neural_max_steps_voice: int = field(default_factory=lambda: int(os.getenv("EDITH_NEURAL_MAX_STEPS_VOICE", "2")))
    skip_rag_on_voice: bool = field(default_factory=lambda: os.getenv("EDITH_SKIP_RAG_ON_VOICE", "1") != "0")
    tts_chunk_min_chars: int = field(default_factory=lambda: int(os.getenv("EDITH_TTS_CHUNK_MIN_CHARS", "14")))
    ui_voice_poll_ms: int = field(default_factory=lambda: int(os.getenv("EDITH_UI_VOICE_POLL_MS", "16")))
    # Wake word + streaming voice OS layer
    wake_engine_enabled: bool = field(default_factory=lambda: os.getenv("EDITH_WAKE_ENGINE", "1") != "0")
    wake_backend: str = field(default_factory=lambda: os.getenv("EDITH_WAKE_BACKEND", "auto"))
    wake_keywords: str = field(
        default_factory=lambda: os.getenv("EDITH_WAKE_KEYWORDS", "edith,jarvis,friday")
    )
    openwakeword_models: str = field(
        default_factory=lambda: os.getenv("EDITH_OPENWAKEWORD_MODELS", "hey_jarvis")
    )
    wake_score_threshold: float = field(
        default_factory=lambda: float(os.getenv("EDITH_WAKE_SCORE_THRESHOLD", "0.55"))
    )
    always_listen_wake: bool = field(
        default_factory=lambda: os.getenv("EDITH_ALWAYS_LISTEN_WAKE", "1") != "0"
    )
    streaming_intent_enabled: bool = field(
        default_factory=lambda: os.getenv("EDITH_STREAMING_INTENT", "1") != "0"
    )
    streaming_intent_min_words: int = field(
        default_factory=lambda: int(os.getenv("EDITH_STREAMING_INTENT_MIN_WORDS", "3"))
    )
    proactive_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("EDITH_PROACTIVE_INTERVAL_SEC", "600"))
    )
    proactive_initial_delay_seconds: int = field(
        default_factory=lambda: int(os.getenv("EDITH_PROACTIVE_INITIAL_DELAY", "30"))
    )
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
            # BAAI/bge-base-en-v1.5 produces 768-dim vectors (matching existing ChromaDB)
            # and runs fully on CPU via sentence-transformers — no VRAM contention.
            # nomic-embed-text was an Ollama-only model ID that crashed the GTX 1650.
            "EDITH_RAG_EMBED_MODEL", "BAAI/bge-base-en-v1.5"
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
    # Populated in __post_init__ (must exist on @dataclass(slots=True))
    automation_timing: object = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        from edith_app.core.automation_timing import AutomationTiming

        self.automation_timing = AutomationTiming.from_env()
        self._apply_runtime_overrides()

    def wake_keyword_list(self) -> tuple[str, ...]:
        return tuple(k.strip().lower() for k in self.wake_keywords.split(",") if k.strip())

    def openwakeword_model_list(self) -> tuple[str, ...]:
        return tuple(m.strip() for m in self.openwakeword_models.split(",") if m.strip())

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
