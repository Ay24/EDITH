"""
edith_cloud.cloud_assistant
=============================
Cloud-mode orchestrator for EDITH.

Wires cloud services (Groq LLM, Groq Whisper, Edge-TTS, DDG, Pollinations,
Groq Vision) into the existing EdithAssistant by overriding its service
attributes after construction.

The existing assistant.py, ui.py, and all routing logic remain
completely untouched — we just swap the service backends.
"""
from __future__ import annotations

import logging
import sys
import traceback
import tkinter as tk

from edith_cloud.config import CloudConfig
from edith_cloud.services.cloud_llm import CloudLLMService
from edith_cloud.services.cloud_stt import CloudSTTService
from edith_cloud.services.cloud_tts import CloudTTSService
from edith_cloud.services.cloud_search import CloudSearchService
from edith_cloud.services.cloud_image_gen import CloudImageGenService
from edith_cloud.services.cloud_vision import CloudVisionService
from edith_cloud.cloud_router import CloudNeuralRouter

from edith_app.assistant import EdithAssistant
from edith_app.services.bootstrap_service import BootstrapService
from edith_app.services.logging_service import get_logger
from edith_app.ui import EdithDesktopUI

logger = logging.getLogger("edith.cloud")


def build_cloud_assistant(config: CloudConfig) -> EdithAssistant:
    """
    Construct an EdithAssistant and hot-swap its services with cloud
    backends.  The assistant itself is unchanged — only the underlying
    service objects are replaced.
    """

    # 1. Build the standard assistant (local services init normally)
    assistant = EdithAssistant(config)

    # 2. Override LLM backend → Groq
    if config.groq_ready:
        cloud_llm = CloudLLMService(config)
        assistant.agent = cloud_llm
        logger.info("☁ LLM backend: Groq (%s)", config.cloud_llm_model)
    else:
        logger.warning("GROQ_API_KEY not set — using local Ollama for LLM")

    # 3. Override Voice → Groq Whisper STT
    if config.groq_ready:
        cloud_stt = CloudSTTService(config)
        # Preserve the interrupt callback wiring
        cloud_stt.on_interrupt = assistant.audio.stop
        assistant.voice = cloud_stt
        logger.info("☁ STT backend: Groq Whisper (%s)", config.cloud_stt_model)

    # 4. Override Audio/TTS → Edge-TTS
    cloud_tts = CloudTTSService(config)
    assistant.audio = cloud_tts
    # Re-wire voice interrupt to new TTS
    if hasattr(assistant.voice, 'on_interrupt'):
        assistant.voice.on_interrupt = cloud_tts.stop
    logger.info("☁ TTS backend: Edge-TTS (%s)", config.cloud_tts_voice)

    # 5. Override Vision → Groq Vision
    if config.groq_ready:
        cloud_vision = CloudVisionService(config)
        assistant.vision = cloud_vision
        # Re-wire system service to use cloud vision
        assistant.system._vision = cloud_vision
        logger.info("☁ Vision backend: Groq Vision (%s)", config.cloud_vision_model)

    # 6. Add Image Generation (new capability)
    cloud_image_gen = CloudImageGenService(config)
    assistant.image_gen = cloud_image_gen
    logger.info("☁ Image Gen: Pollinations.ai (free, no key)")

    # 7. Override Search → DDG SDK
    cloud_search = CloudSearchService()
    # The ResearchService is used inside system_service — we also set it on assistant
    assistant.cloud_search = cloud_search
    logger.info("☁ Search: DuckDuckGo SDK (structured)")

    # 8. Wire the CloudNeuralRouter (adds generate_image + web_search actions)
    assistant.neural_router = CloudNeuralRouter(
        config=config,
        agent_service=assistant.agent,
        rag_service=assistant.rag,
        whatsapp_service=assistant.whatsapp,
        image_gen_service=cloud_image_gen,
        search_service=cloud_search,
    )
    logger.info("☁ Neural Router: Cloud-extended (image gen + web search)")

    # 9. Update the cowork agent loop to use cloud LLM
    assistant.cowork._agent = assistant.agent

    return assistant


def main() -> None:
    """Cloud-mode entry point — mirrors edith_app.app.main()."""

    root = tk.Tk()
    root.withdraw()

    config = CloudConfig()
    log = get_logger("edith.cloud_app", config.runtime_log_path)

    def _handle_uncaught(exc_type, exc_value, exc_tb) -> None:
        log.error(
            "Uncaught exception: %s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )

    sys.excepthook = _handle_uncaught

    # Print cloud mode banner
    print("=" * 60)
    print("  EDITH — Cloud-Accelerated Mode")
    print("=" * 60)
    if config.groq_ready:
        print(f"  LLM    : Groq {config.cloud_llm_model}")
        print(f"  Fast   : Groq {config.cloud_fast_model}")
        print(f"  STT    : Groq Whisper {config.cloud_stt_model}")
        print(f"  Vision : Groq {config.cloud_vision_model}")
    else:
        print("  ⚠ GROQ_API_KEY not set — LLM/STT/Vision use local Ollama")
    print(f"  TTS    : Edge-TTS ({config.cloud_tts_voice})")
    print(f"  Search : DuckDuckGo SDK")
    print(f"  ImageGen: Pollinations.ai (free)")
    print("=" * 60)

    log.info("Starting EDITH in Cloud-Accelerated Mode")

    bootstrap = BootstrapService(config)
    bootstrap.start_async()

    assistant = build_cloud_assistant(config)

    ui = EdithDesktopUI(assistant, root=root)
    ui.run()
