"""
launch_cloud.py — EDITH Cloud-Accelerated Launcher
=====================================================
Starts EDITH in cloud mode with:
  - Groq LLM (Llama 3.3 70B @ 800 tok/s)
  - Groq Whisper STT (< 400ms)
  - Edge-TTS (Microsoft Neural, free)
  - DuckDuckGo Search SDK
  - Pollinations.ai Image Generation
  - Groq Vision

Setup:
  1. Copy .env.cloud.example → .env.cloud
  2. Set GROQ_API_KEY (free at console.groq.com)
  3. pip install -r requirements_cloud.txt
  4. python launch_cloud.py

The local Ollama version (launch_edith.bat) remains untouched.
"""
from __future__ import annotations

import os
import subprocess
import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("EDITH.CloudLauncher")

PROJECT_ROOT = Path(__file__).resolve().parent


def _load_env_file(path: Path) -> None:
    """Load a .env file into os.environ (simple parser, no dependencies)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and not os.getenv(key):
            os.environ[key] = value


def _ensure_cloud_deps() -> bool:
    """Install cloud-specific dependencies if missing."""
    missing: list[str] = []

    try:
        import groq  # noqa
    except ImportError:
        missing.append("groq>=0.9.0")

    try:
        import edge_tts  # noqa
    except ImportError:
        missing.append("edge-tts>=6.1.9")

    try:
        from duckduckgo_search import DDGS  # noqa
    except ImportError:
        missing.append("duckduckgo-search>=6.1.0")

    if not missing:
        logger.info("All cloud dependencies present.")
        return True

    logger.info("Installing missing cloud deps: %s", ", ".join(missing))
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + missing,
            timeout=120,
        )
        return True
    except Exception as exc:
        logger.error("Failed to install cloud deps: %s", exc)
        logger.error("Run manually: pip install -r requirements_cloud.txt")
        return False


def _check_groq_key() -> bool:
    """Check if GROQ_API_KEY is configured."""
    key = os.getenv("GROQ_API_KEY", "")
    if key and key != "gsk_your_key_here":
        logger.info("GROQ_API_KEY found.")
        return True
    logger.warning(
        "GROQ_API_KEY not set. Get a free key at https://console.groq.com\n"
        "  Set it in .env.cloud or as an environment variable.\n"
        "  EDITH will fall back to local Ollama for LLM/STT/Vision."
    )
    return False


def main() -> None:
    logger.info("=" * 60)
    logger.info("  EDITH Cloud-Accelerated Launcher")
    logger.info("=" * 60)

    # ── Step 1: Load .env.cloud ───────────────────────────────────────────────
    env_path = PROJECT_ROOT / ".env.cloud"
    _load_env_file(env_path)
    logger.info("[1/3] Loaded environment from %s", env_path if env_path.exists() else "(not found)")

    # ── Step 2: Check GROQ_API_KEY ────────────────────────────────────────────
    logger.info("[2/3] Checking Groq API key...")
    _check_groq_key()

    # ── Step 3: Install cloud dependencies ────────────────────────────────────
    logger.info("[3/3] Checking cloud dependencies...")
    if not _ensure_cloud_deps():
        logger.error("Cloud dependency installation failed. Exiting.")
        sys.exit(1)

    # ── Launch ────────────────────────────────────────────────────────────────
    os.environ["EDITH_CLOUD_MODE"] = "1"
    sys.path.insert(0, str(PROJECT_ROOT))

    from edith_cloud.cloud_assistant import main as cloud_main
    cloud_main()


if __name__ == "__main__":
    main()
