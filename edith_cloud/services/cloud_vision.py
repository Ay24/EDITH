"""
edith_cloud.services.cloud_vision
===================================
Cloud-backed vision analysis using Groq Vision API.

Drop-in replacement for VisionService — same public interface.
Sends base64-encoded images to Groq's vision model for description.
Falls back to local VisionService if Groq is unavailable.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("edith.cloud_vision")

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from groq import Groq
except ImportError:
    Groq = None


class CloudVisionService:
    """
    Vision analysis via Groq Vision API.

    Same API as VisionService:
      - enabled: bool
      - describe_image(path, prompt) -> str
      - describe_screen(path, prompt) -> str
      - extract_chat_text(path) -> str
    """

    def __init__(self, config: Any) -> None:
        self._config = config
        self._api_key = getattr(config, "groq_api_key", "")
        self._model = getattr(config, "cloud_vision_model", "llama-3.2-90b-vision-preview")
        self._client = None
        self._caption_cache: dict[str, tuple[float, str]] = {}
        self._caption_cache_max = 128

        # Local fallback
        self._local_vision = None

    @property
    def enabled(self) -> bool:
        return bool(self._api_key) and Groq is not None

    def _get_client(self):
        if self._client is None and Groq is not None and self._api_key:
            self._client = Groq(api_key=self._api_key)
        return self._client

    def describe_image(self, path: Path, prompt: str | None = None) -> str:
        if not path.exists() or not path.is_file():
            return ""

        # Check cache
        cache_key = str(path.resolve())
        mtime = path.stat().st_mtime
        cached = self._caption_cache.get(cache_key)
        if cached and cached[0] == mtime:
            return cached[1]

        client = self._get_client()
        if client is None:
            return self._local_fallback("describe_image", path, prompt)

        # Encode image
        encoded = self._encode_image(path)
        if not encoded:
            return ""

        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type is None:
            mime_type = "image/png"

        image_prompt = prompt or (
            "Describe this image briefly for desktop organization. "
            "Focus on likely category words such as screenshot, receipt, document, "
            "poster, logo, family, trip, wallpaper, UI, notes, code, chart, selfie, or product. "
            "Return one short line."
        )

        try:
            response = client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": image_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{encoded}",
                            },
                        },
                    ],
                }],
                max_tokens=200,
                temperature=0.3,
            )
            text = response.choices[0].message.content or ""
            text = text.strip()
            if text:
                if len(self._caption_cache) >= self._caption_cache_max:
                    self._caption_cache.pop(next(iter(self._caption_cache)), None)
                self._caption_cache[cache_key] = (mtime, text)
            return text
        except Exception as exc:
            logger.warning("Groq Vision failed: %s", exc)
            return self._local_fallback("describe_image", path, prompt)

    def describe_screen(self, path: Path, prompt: str | None = None) -> str:
        return self.describe_image(path, prompt=prompt)

    def extract_chat_text(self, path: Path) -> str:
        if not path.exists() or not path.is_file():
            return ""

        client = self._get_client()
        if client is None:
            return self._local_fallback("extract_chat_text", path)

        encoded = self._encode_image(path)
        if not encoded:
            return ""

        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type is None:
            mime_type = "image/png"

        try:
            response = client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "This is a screenshot of a WhatsApp chat. "
                                "Transcribe the visible conversation text as accurately as possible. "
                                "Keep each message on a new line. "
                                "Do not summarize. Do not explain. Return only transcribed chat text."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{encoded}",
                            },
                        },
                    ],
                }],
                max_tokens=500,
                temperature=0.2,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.warning("Groq Vision chat extraction failed: %s", exc)
            return self._local_fallback("extract_chat_text", path)

    def _encode_image(self, path: Path) -> str:
        if Image is None:
            return base64.b64encode(path.read_bytes()).decode("ascii")
        try:
            with Image.open(path) as image:
                image = image.convert("RGB")
                image.thumbnail((1024, 1024))
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=80, optimize=True)
            return base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:
            return base64.b64encode(path.read_bytes()).decode("ascii")

    def _local_fallback(self, method: str, path: Path, prompt: str | None = None) -> str:
        if self._local_vision is None:
            try:
                from edith_app.services.vision_service import VisionService
                self._local_vision = VisionService(self._config)
            except Exception:
                return ""
        try:
            fn = getattr(self._local_vision, method)
            if method == "extract_chat_text":
                return fn(path)
            return fn(path, prompt)
        except Exception:
            return ""
