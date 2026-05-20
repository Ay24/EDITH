"""
launch_adaptive.py — EDITH Native Inference Launcher
=====================================================
This script is the fully self-contained, auto-setup launcher for EDITH's
native inference mode. Run it instead of main.py for maximum speed.

What it auto-installs / auto-downloads:
  1. psutil, pynvml           — Hardware monitoring
  2. llama-cpp-python          — Native inference (with CUDA if GPU detected)
  3. huggingface-hub           — For model downloading
  4. Llama-3.2-3B-Instruct.Q4_K_M.gguf — The model file (2.0 GB)

Usage:
  python launch_adaptive.py

Environment overrides:
  EDITH_NATIVE_MODEL=path/to/custom.gguf   Override the model path
  EDITH_PROFILE=balanced|performance|ultra_stable
"""

from __future__ import annotations

import os
import sys
import subprocess
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("EDITH.Launcher")

# ── Constants ─────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
MODELS_DIR   = PROJECT_ROOT / "models"
MODEL_PATH   = Path(os.getenv(
    "EDITH_NATIVE_MODEL",
    str(MODELS_DIR / "llama-3.2-3b-instruct-q4_k_m.gguf")
))
# Hugging Face model repo and filename for auto-download
HF_REPO_ID   = "bartowski/Llama-3.2-3B-Instruct-GGUF"
HF_FILENAME  = "Llama-3.2-3B-Instruct-Q4_K_M.gguf"
PROFILE      = os.getenv("EDITH_PROFILE", "balanced")


def _pip_install(packages: list[str], extra_args: list[str] | None = None) -> bool:
    """Silently install packages via pip. Returns True on success."""
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade"] + (extra_args or []) + packages
    logger.info(f"Installing: {', '.join(packages)}")
    try:
        subprocess.check_call(cmd)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"pip install failed: {e}")
        return False


def _detect_cuda() -> tuple[bool, str]:
    """
    Check if a CUDA-capable GPU is present and return the CUDA version
    from the driver (e.g. '12.1'). Returns (False, '') if no GPU found.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0 or not result.stdout.strip():
            logger.info("No CUDA GPU detected — will use CPU-only build.")
            return False, ""
        gpu_name = result.stdout.strip().split("\n")[0]

        # Get CUDA driver version from nvidia-smi
        ver_result = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=5
        )
        cuda_ver = "12.1"  # safe default
        for line in ver_result.stdout.splitlines():
            if "CUDA Version" in line:
                parts = line.split("CUDA Version:")
                if len(parts) > 1:
                    raw = parts[1].strip().split()[0]  # e.g. "12.4"
                    major, minor = raw.split(".")[:2]
                    ver_int = int(major) * 10 + int(minor)
                    if ver_int >= 125:
                        cuda_ver = "12.5"
                    elif ver_int >= 124:
                        cuda_ver = "12.4"
                    elif ver_int >= 123:
                        cuda_ver = "12.3"
                    elif ver_int >= 122:
                        cuda_ver = "12.2"
                    else:
                        cuda_ver = "12.1"
                break

        logger.info(f"CUDA GPU detected: {gpu_name} | Driver CUDA: {cuda_ver}")
        return True, cuda_ver

    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.info("nvidia-smi not found — using CPU-only build.")
        return False, ""


def _ensure_base_deps() -> None:
    """Ensure psutil and pynvml are installed."""
    missing = []
    try:
        import psutil  # noqa
    except ImportError:
        missing.append("psutil")
    try:
        import pynvml  # noqa
    except ImportError:
        missing.append("pynvml")
    if missing:
        _pip_install(missing)


def _ensure_huggingface_hub() -> None:
    """Ensure huggingface-hub is installed for model downloading."""
    try:
        import huggingface_hub  # noqa
    except ImportError:
        _pip_install(["huggingface-hub"])


def _ensure_llama_cpp(cuda: bool, cuda_ver: str) -> bool:
    """
    Install llama-cpp-python using pre-built wheels (no CUDA Toolkit needed).
    Falls back to CPU-only if GPU wheels fail.
    Returns True if the package is available.
    """
    try:
        import llama_cpp  # noqa
        logger.info("llama-cpp-python already installed.")
        return True
    except ImportError:
        pass

    logger.info("llama-cpp-python not found. Installing now...")

    if cuda and cuda_ver:
        # Use official pre-built CUDA wheels — no nvcc / CUDA Toolkit required
        wheel_tag = cuda_ver.replace(".", "")  # "12.1" → "121"
        index_url = f"https://abetlen.github.io/llama-cpp-python/whl/cu{wheel_tag}"
        logger.info(f"Fetching pre-built CUDA {cuda_ver} wheel from: {index_url}")
        cmd = [
            sys.executable, "-m", "pip", "install",
            "--quiet", "--upgrade",
            "llama-cpp-python",
            "--extra-index-url", index_url,
        ]
        try:
            subprocess.check_call(cmd)
            import llama_cpp  # noqa
            logger.info(f"llama-cpp-python installed with CUDA {cuda_ver} support.")
            return True
        except Exception:
            logger.warning("Pre-built CUDA wheel failed. Falling back to CPU-only build...")

    # CPU-only fallback
    logger.info("Installing CPU-only build of llama-cpp-python...")
    cpu_index = "https://abetlen.github.io/llama-cpp-python/whl/cpu"
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--quiet", "--upgrade",
        "llama-cpp-python",
        "--extra-index-url", cpu_index,
    ]
    try:
        subprocess.check_call(cmd)
        import llama_cpp  # noqa
        logger.info("llama-cpp-python installed (CPU only).")
        return True
    except Exception as e:
        logger.error(f"All install attempts failed: {e}")
        return False


def _download_model() -> bool:
    """
    Download the GGUF model from Hugging Face Hub if not already present.
    Returns True if model is ready.
    """
    if MODEL_PATH.exists():
        size_mb = MODEL_PATH.stat().st_size / (1024 * 1024)
        logger.info(f"Model already present: {MODEL_PATH.name} ({size_mb:.0f} MB)")
        return True

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Downloading model from Hugging Face: {HF_REPO_ID}/{HF_FILENAME}")
    logger.info("This is a ~2.0 GB download. This only happens once.")

    try:
        from huggingface_hub import hf_hub_download
        downloaded_path = hf_hub_download(
            repo_id=HF_REPO_ID,
            filename=HF_FILENAME,
            local_dir=str(MODELS_DIR),
            local_dir_use_symlinks=False,
        )
        # Move to expected path if HF saved it under a different name
        downloaded = Path(downloaded_path)
        if downloaded.resolve() != MODEL_PATH.resolve():
            downloaded.rename(MODEL_PATH)
        logger.info(f"Model downloaded to: {MODEL_PATH}")
        return True
    except Exception as e:
        logger.error(f"Model download failed: {e}")
        logger.error("You can manually download the model from:")
        logger.error(f"  https://huggingface.co/{HF_REPO_ID}/resolve/main/{HF_FILENAME}")
        logger.error(f"  and place it at: {MODEL_PATH}")
        return False


def _run_preflight_test() -> bool:
    """Run a quick generation test to confirm the engine is operational."""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from edith_app.core.inference_manager import AdaptiveLlamaEngine
    except ImportError as e:
        logger.error(f"Could not import AdaptiveLlamaEngine: {e}")
        return False

    logger.info("Running native engine pre-flight test...")
    engine = None
    try:
        engine = AdaptiveLlamaEngine(model_path=str(MODEL_PATH), profile_name=PROFILE)
        response = engine.generate(
            "Respond with exactly three words: 'Native core online.'",
            max_tokens=12,
            stream=False,
        )
        output = response["choices"][0]["text"].strip()
        logger.info(f"Pre-flight result: '{output[:60]}'")
        return True
    except Exception as e:
        logger.error(f"Pre-flight test failed: {e}")
        return False
    finally:
        # CRITICAL: explicitly shut down and delete the engine so the GPU VRAM
        # is fully released before the main app creates its own engine instance.
        # Without this, the GTX 1650's 4GB VRAM is already occupied and the
        # second Llama load fails with "Failed to load model from file".
        if engine is not None:
            try:
                engine.shutdown()
            except Exception:
                pass
            del engine
        import gc
        gc.collect()
        import time
        time.sleep(1.0)  # give the CUDA driver time to reclaim VRAM



def main() -> None:
    logger.info("=" * 60)
    logger.info("  EDITH Adaptive Native Engine — Auto Setup Launcher")
    logger.info("=" * 60)

    # ── Step 1: Hardware Detection ────────────────────────────────────────────
    cuda_available, cuda_ver = _detect_cuda()

    # ── Step 2: Install Base Dependencies ─────────────────────────────────────
    logger.info("[1/4] Checking base dependencies (psutil, pynvml)...")
    _ensure_base_deps()

    # ── Step 3: Install llama-cpp-python ──────────────────────────────────────
    logger.info("[2/4] Checking llama-cpp-python...")
    if not _ensure_llama_cpp(cuda=cuda_available, cuda_ver=cuda_ver):
        logger.error("Cannot continue without llama-cpp-python. Exiting.")
        sys.exit(1)

    # ── Step 4: Download model ────────────────────────────────────────────────
    logger.info("[3/4] Checking model file...")
    _ensure_huggingface_hub()
    if not _download_model():
        logger.error("Cannot continue without model file. Exiting.")
        sys.exit(1)

    # ── Step 5: Pre-flight test ───────────────────────────────────────────────
    logger.info("[4/4] Running pre-flight test...")
    if not _run_preflight_test():
        logger.warning("Pre-flight failed — falling back to standard Ollama mode.")
        import main as edith_main
        edith_main.main()
        return

    # ── Step 6: Launch EDITH in Native Mode ───────────────────────────────────
    logger.info("=" * 60)
    logger.info("  All systems nominal. Launching EDITH in Native Mode.")
    logger.info(f"  Model  : {MODEL_PATH.name}")
    logger.info(f"  Profile: {PROFILE}")
    logger.info(f"  GPU    : {'CUDA ' + cuda_ver + ' (pre-built wheel)' if cuda_available else 'CPU Only'}")
    logger.info("=" * 60)

    os.environ["EDITH_USE_NATIVE_LLM"] = "1"
    os.environ["EDITH_NATIVE_MODEL_PATH"] = str(MODEL_PATH)

    sys.path.insert(0, str(PROJECT_ROOT))
    import main as edith_main
    edith_main.main()


if __name__ == "__main__":
    main()
