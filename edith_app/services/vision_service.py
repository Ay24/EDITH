from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
import time

import requests

try:
    from PIL import Image
except ImportError:
    Image = None
try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    import psutil as _psutil
except ImportError:
    _psutil = None

from edith_app.config import AppConfig

# Minimum free system RAM (MB) required before attempting to load a vision model.
# moondream2 needs ~1.2 GB RAM when running CPU-only, more when GPU is contested.
_MIN_FREE_RAM_MB = 1800


def _free_ram_mb() -> int:
    """Return available system RAM in MB, or a large number if psutil is unavailable."""
    if _psutil is None:
        return 9999
    try:
        return int(_psutil.virtual_memory().available / (1024 * 1024))
    except Exception:
        return 9999


class VisionService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session = requests.Session()
        self._tags_cache: tuple[float, set[str]] = (0.0, set())
        self._caption_cache: dict[str, tuple[float, str]] = {}
        self._resolved_model_cache: tuple[float, str] = (0.0, "")
        self._fallback_candidates = [
            "moondream",
            "llama3.2-vision",
            "llava",
            "llava:7b",
            "bakllava",
        ]

    @property
    def enabled(self) -> bool:
        return bool(self._resolve_model())

    def describe_image(self, path: Path, prompt: str | None = None) -> str:
        if not path.exists() or not path.is_file():
            return ""
        cache_key = str(path.resolve())
        mtime = path.stat().st_mtime
        cached = self._caption_cache.get(cache_key)
        if cached and cached[0] == mtime:
            return cached[1]

        model = self._resolve_model()
        if not model:
            return ""

        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type is None or not mime_type.startswith("image/"):
            return ""

        try:
            encoded = self._encode_image(path)
        except Exception:
            return ""
        if not encoded:
            return ""

        # ── Safety check: ensure enough RAM before calling vision model ────────
        free_mb = _free_ram_mb()
        if free_mb < _MIN_FREE_RAM_MB:
            return f"[Vision skipped — only {free_mb} MB RAM free, need {_MIN_FREE_RAM_MB} MB]"

        # ── Free the main LLM from VRAM before loading vision model ───────────
        # Sending keep_alive=0 tells Ollama to immediately unload the current
        # model runner so its VRAM/RAM is available for the vision model.
        self._release_main_model()

        payload = {
            "model": model,
            "prompt": prompt or (
                "Describe this image briefly for desktop organization. "
                "Focus on likely category words such as screenshot, receipt, document, poster, logo, family, trip, wallpaper, UI, notes, code, chart, selfie, or product. "
                "Return one short line."
            ),
            "images": [encoded],
            "stream": False,
            "keep_alive": "5m",     # let Ollama manage unloading after use
            "options": {
                "num_ctx": 1024,    # reduced context → 192 MB KV instead of 384 MB
            },
        }
        try:
            response = self._session.post(
                f"{self._config.ollama_url}/api/generate",
                json=payload,
                timeout=90,
            )
            response.raise_for_status()
            text = response.json().get("response", "").strip()
        except requests.RequestException:
            return ""

        if text:
            self._caption_cache[cache_key] = (mtime, text)
        return text

    def describe_screen(self, path: Path, prompt: str | None = None) -> str:
        """
        Alias for describe_image specifically for live screen vision.
        Performs the same RAM guard and model release.
        """
        return self.describe_image(path, prompt=prompt)

    def extract_chat_text(self, path: Path) -> str:
        if not path.exists() or not path.is_file():
            return ""
        # Primary: OCR (proven for UI text extraction, zero extra RAM needed)
        ocr_text = self._ocr_chat_text(path)
        if ocr_text:
            return ocr_text

        # Fallback: vision model transcription
        model = self._resolve_model()
        if not model:
            return ""

        # ── Safety check ───────────────────────────────────────────────────────
        free_mb = _free_ram_mb()
        if free_mb < _MIN_FREE_RAM_MB:
            return ""

        try:
            encoded = self._encode_image(path)
        except Exception:
            return ""
        if not encoded:
            return ""

        self._release_main_model()

        payload = {
            "model": model,
            "prompt": (
                "This is a screenshot of a WhatsApp chat. "
                "Transcribe the visible conversation text as accurately as possible. "
                "Keep each message on a new line. "
                "Do not summarize. Do not explain. Return only transcribed chat text."
            ),
            "images": [encoded],
            "stream": False,
            "options": {
                "num_ctx": 1024,
            },
        }
        try:
            response = self._session.post(
                f"{self._config.ollama_url}/api/generate",
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()
        except requests.RequestException:
            return ""

    def _release_main_model(self) -> None:
        """
        Ask Ollama to unload the currently loaded LLM so its VRAM/RAM is freed
        before we load the vision model. Uses keep_alive=0 which triggers
        an immediate unload of that model runner.
        """
        main_model = self._config.ollama_model
        if not main_model:
            return
        try:
            # A minimal generate call with keep_alive=0 causes Ollama to
            # schedule an immediate unload of that model.
            self._session.post(
                f"{self._config.ollama_url}/api/generate",
                json={
                    "model": main_model,
                    "prompt": "",
                    "keep_alive": 0,
                    "stream": False,
                },
                timeout=5,
            )
            # Give the runner a moment to actually unload
            time.sleep(1.5)
        except Exception:
            pass

    def _ocr_chat_text(self, path: Path) -> str:
        if pytesseract is None or Image is None:
            return ""
        try:
            tess_cmd = os.getenv("EDITH_TESSERACT_CMD", "").strip()
            if tess_cmd:
                pytesseract.pytesseract.tesseract_cmd = tess_cmd
            with Image.open(path) as image:
                gray = image.convert("L")
                bw = gray.point(lambda p: 255 if p > 145 else 0)
                text = pytesseract.image_to_string(
                    bw,
                    config="--oem 3 --psm 6",
                ).strip()
                if len(text) >= 20:
                    return text
                text2 = pytesseract.image_to_string(
                    gray,
                    config="--oem 3 --psm 6",
                ).strip()
                if len(text2) >= 20:
                    return text2
                return ""
        except Exception:
            return ""

    def _resolve_model(self) -> str:
        cached_at, cached_name = self._resolved_model_cache
        if time.monotonic() - cached_at < 30.0:
            return cached_name
        available = self._available_models()
        configured = self._config.vision_model.strip()
        if configured and configured in available:
            self._resolved_model_cache = (time.monotonic(), configured)
            return configured
        for candidate in self._fallback_candidates:
            if candidate in available:
                self._resolved_model_cache = (time.monotonic(), candidate)
                return candidate
        self._resolved_model_cache = (time.monotonic(), "")
        return ""

    def _available_models(self) -> set[str]:
        now = time.monotonic()
        cached_at, cached_names = self._tags_cache
        if now - cached_at < 30.0:
            return cached_names
        try:
            response = self._session.get(
                f"{self._config.ollama_url}/api/tags", timeout=2
            )
            response.raise_for_status()
            data = response.json()
            names = set()
            for item in data.get("models", []):
                name = item.get("name", "")
                if not name:
                    continue
                names.add(name)
                names.add(name.split(":", 1)[0])
            self._tags_cache = (now, names)
            return names
        except requests.RequestException:
            return set()

    def _encode_image(self, path: Path) -> str:
        if Image is None:
            return base64.b64encode(path.read_bytes()).decode("ascii")
        try:
            with Image.open(path) as image:
                image = image.convert("RGB")
                # Cap at 1024px — moondream doesn't benefit from larger inputs
                # and smaller images drastically reduce encoding + inference time
                image.thumbnail((1024, 1024))
                from io import BytesIO
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=80, optimize=True)
            return base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:
            return base64.b64encode(path.read_bytes()).decode("ascii")
