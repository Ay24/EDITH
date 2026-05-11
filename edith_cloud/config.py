"""
edith_cloud.config
==================
Cloud-specific configuration layered on top of AppConfig.

All cloud env vars are optional except GROQ_API_KEY.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from edith_app.config import AppConfig


@dataclass(slots=True)
class CloudConfig(AppConfig):
    """Extends AppConfig with cloud-backend settings."""

    # ── Groq (LLM + Vision + STT) ─────────────────────────────────────────────
    groq_api_key: str = field(
        default_factory=lambda: os.getenv("GROQ_API_KEY", "")
    )
    cloud_llm_model: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_CLOUD_LLM_MODEL", "llama-3.3-70b-versatile"
        )
    )
    cloud_fast_model: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_CLOUD_FAST_MODEL", "llama-3.1-8b-instant"
        )
    )
    cloud_vision_model: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_CLOUD_VISION_MODEL", "llama-3.2-90b-vision-preview"
        )
    )
    cloud_stt_model: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_CLOUD_STT_MODEL", "whisper-large-v3"
        )
    )

    # ── Edge-TTS (completely free, no key) ─────────────────────────────────────
    cloud_tts_voice: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_CLOUD_TTS_VOICE", "en-US-AriaNeural"
        )
    )
    cloud_tts_rate: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_CLOUD_TTS_RATE", "+5%"
        )
    )

    # ── HuggingFace (optional — for cloud embeddings) ──────────────────────────
    hf_api_key: str = field(
        default_factory=lambda: os.getenv("HF_API_KEY", "")
    )
    cloud_embed_model: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_CLOUD_EMBED_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        )
    )

    # ── Pollinations (image gen — zero key, unlimited) ─────────────────────────
    cloud_image_gen_base: str = field(
        default_factory=lambda: os.getenv(
            "EDITH_CLOUD_IMAGE_GEN_BASE",
            "https://image.pollinations.ai/prompt",
        )
    )

    # ── Feature flags ──────────────────────────────────────────────────────────
    cloud_mode: bool = True
    fallback_to_ollama: bool = field(
        default_factory=lambda: os.getenv("EDITH_CLOUD_FALLBACK_OLLAMA", "1") != "0"
    )

    @property
    def groq_ready(self) -> bool:
        return bool(self.groq_api_key)
