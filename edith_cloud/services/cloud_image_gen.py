"""
edith_cloud.services.cloud_image_gen
======================================
Image generation using Pollinations.ai — completely free, zero API key.

New capability for EDITH cloud mode. Generates images from text prompts
and saves them to data/generated/.
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("edith.cloud_image_gen")


class CloudImageGenService:
    """
    Generate images via Pollinations.ai.

    Usage:
        svc = CloudImageGenService(config)
        path = svc.generate("a futuristic city at night")
        # -> Path("data/generated/img_1715180000.png")
    """

    def __init__(self, config: Any = None) -> None:
        self._base_url = getattr(
            config, "cloud_image_gen_base",
            "https://image.pollinations.ai/prompt",
        ) if config else "https://image.pollinations.ai/prompt"

        self._output_dir = Path(
            getattr(config, "data_dir", "data") if config else "data"
        ) / "generated"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()

    def generate(self, prompt: str, width: int = 1024, height: int = 1024) -> str:
        """
        Generate an image from a text prompt.

        Returns:
            Path string to the saved image, or an error message.
        """
        if not prompt.strip():
            return "I need a description to generate an image."

        encoded = urllib.parse.quote(prompt.strip())
        url = f"{self._base_url}/{encoded}?width={width}&height={height}&nologo=true"

        try:
            response = self._session.get(url, timeout=30, stream=True)
            response.raise_for_status()

            # Verify we got an image
            content_type = response.headers.get("content-type", "")
            if "image" not in content_type:
                return "The image generation service returned an unexpected response."

            # Save to disk
            timestamp = int(time.time())
            filename = f"img_{timestamp}.png"
            save_path = self._output_dir / filename

            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            size_kb = save_path.stat().st_size / 1024
            logger.info("Generated image: %s (%.0f KB)", save_path, size_kb)
            return f"Image generated and saved to {save_path}"

        except requests.Timeout:
            return "Image generation timed out. Try again with a simpler prompt."
        except requests.RequestException as exc:
            logger.warning("Pollinations.ai request failed: %s", exc)
            return "Image generation failed. The service may be temporarily unavailable."
        except Exception as exc:
            logger.error("Unexpected image gen error: %s", exc)
            return f"Image generation error: {exc}"

    def generate_and_display(self, prompt: str) -> tuple[str, str | None]:
        """
        Generate an image and return (status_message, image_path_or_none).
        Useful for UI integration that wants to display the result.
        """
        result = self.generate(prompt)
        if result.startswith("Image generated"):
            # Extract path from the result string
            path_str = result.split("saved to ")[-1].strip()
            return result, path_str
        return result, None
