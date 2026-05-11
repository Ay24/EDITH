"""
edith_cloud.services.cloud_embeddings
=======================================
Cloud-backed embedding generation using HuggingFace Inference API.

Used by the RAG pipeline when running in cloud mode — avoids loading
nomic-embed-text locally via Ollama.

Falls back to local Ollama embeddings if HF API is unavailable.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger("edith.cloud_embeddings")


class CloudEmbeddingsService:
    """
    Generate embeddings via HuggingFace Inference API.

    Designed to be used as an embedding function override in ChromaDB
    or directly by the RAG pipeline.
    """

    def __init__(self, config: Any) -> None:
        self._api_key = getattr(config, "hf_api_key", "")
        self._model = getattr(
            config, "cloud_embed_model",
            "sentence-transformers/all-MiniLM-L6-v2",
        )
        self._base_url = "https://api-inference.huggingface.co/pipeline/feature-extraction"
        self._session = requests.Session()
        if self._api_key:
            self._session.headers["Authorization"] = f"Bearer {self._api_key}"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts using HuggingFace Inference API.

        Returns a list of embedding vectors. Falls back to empty vectors
        if the API is unavailable.
        """
        if not self._api_key:
            logger.warning("HF_API_KEY not set — cloud embeddings unavailable")
            return [[] for _ in texts]

        url = f"{self._base_url}/{self._model}"
        try:
            response = self._session.post(
                url,
                json={"inputs": texts, "options": {"wait_for_model": True}},
                timeout=15,
            )
            response.raise_for_status()
            embeddings = response.json()

            # HF returns list[list[float]] for batch input
            if isinstance(embeddings, list) and len(embeddings) > 0:
                if isinstance(embeddings[0], list):
                    return embeddings
                # Single text input returns list[float]
                return [embeddings]
            return [[] for _ in texts]
        except Exception as exc:
            logger.warning("HF embeddings failed: %s", exc)
            return [[] for _ in texts]

    def embed_single(self, text: str) -> list[float]:
        """Embed a single text string."""
        results = self.embed([text])
        return results[0] if results else []

    def __call__(self, input: list[str]) -> list[list[float]]:
        """ChromaDB-compatible embedding function interface."""
        return self.embed(input)
