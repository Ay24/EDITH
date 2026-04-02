from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
import time

import requests

try:
    from PIL import Image
except ImportError:
    Image = None

from edith_app.config import AppConfig


class VisionService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session = requests.Session()
        self._tags_cache: tuple[float, set[str]] = (0.0, set())
        self._caption_cache: dict[str, tuple[float, str]] = {}
        self._resolved_model_cache: tuple[float, str] = (0.0, "")
        self._fallback_candidates = [
            "llama3.2-vision",
            "llava",
            "llava:7b",
            "moondream",
            "bakllava",
        ]

    @property
    def enabled(self) -> bool:
        return bool(self._resolve_model())

    def describe_image(self, path: Path) -> str:
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

        payload = {
            "model": model,
            "prompt": (
                "Describe this image briefly for desktop organization. "
                "Focus on likely category words such as screenshot, receipt, document, poster, logo, family, trip, wallpaper, UI, notes, code, chart, selfie, or product. "
                "Return one short line."
            ),
            "images": [encoded],
            "stream": False,
        }
        try:
            response = self._session.post(f"{self._config.ollama_url}/api/generate", json=payload, timeout=90)
            response.raise_for_status()
            text = response.json().get("response", "").strip()
        except requests.RequestException:
            return ""

        if text:
            self._caption_cache[cache_key] = (mtime, text)
        return text

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
            response = self._session.get(f"{self._config.ollama_url}/api/tags", timeout=2)
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
                image.thumbnail((768, 768))
                from io import BytesIO

                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=70, optimize=True)
            return base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:
            return base64.b64encode(path.read_bytes()).decode("ascii")
