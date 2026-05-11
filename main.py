import os
import warnings

# ── GPU VRAM budget ──────────────────────────────────────────────────────────
# GTX 1650 has only 4 GB VRAM.  Ollama needs the full GPU for Llama 3.2.
# Force PyTorch (used by Kokoro TTS + Vosk) to run on CPU so it doesn't
# compete with Ollama for VRAM.  This MUST be set before `import torch`.
os.environ["CUDA_VISIBLE_DEVICES"] = ""       # PyTorch → CPU only
os.environ.setdefault("OLLAMA_FLASH_ATTENTION", "1")  # Ollama: use less VRAM

# Suppress noisy library warnings before any heavy imports
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("PYTHONWARNINGS", "ignore::UserWarning,ignore::FutureWarning,ignore::DeprecationWarning")

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings(
    "ignore",
    message=".*dropout option adds dropout after all but last recurrent layer.*",
)
warnings.filterwarnings(
    "ignore",
    message=".*Torch was not compiled with flash attention.*",
)

from edith_app.app import main


if __name__ == "__main__":
    main()
