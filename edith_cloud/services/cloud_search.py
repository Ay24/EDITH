"""
edith_cloud.services.cloud_search
===================================
Cloud search using the duckduckgo-search SDK.

Drop-in replacement for ResearchService — returns structured JSON
results instead of scraping HTML, making it faster and more reliable.
Zero API key required.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("edith.cloud_search")

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None


@dataclass(slots=True)
class SearchHit:
    title: str
    snippet: str
    url: str


class CloudSearchService:
    """
    Structured DuckDuckGo search via the duckduckgo-search SDK.

    Same API as ResearchService:
      - search(query, limit, domain) -> list[SearchHit]
      - summarize_query(query, limit, domain) -> str
    """

    def __init__(self) -> None:
        self._cache: dict[str, list[SearchHit]] = {}

    def summarize_query(self, query: str, limit: int = 5, domain: str | None = None) -> str:
        hits = self.search(query, limit=limit, domain=domain)
        if not hits:
            return ""
        lines = [f"Quick results for {query}:"]
        for index, hit in enumerate(hits[:limit], start=1):
            snippet = self._clip(hit.snippet or hit.title, 120)
            lines.append(f"{index}. {hit.title} - {snippet}")
        return "\n".join(lines)

    def search(self, query: str, limit: int = 5, domain: str | None = None) -> list[SearchHit]:
        key = f"{domain or ''}::{query.lower().strip()}::{limit}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        if DDGS is None:
            logger.warning("duckduckgo-search not installed. Falling back to empty results.")
            return []

        scoped_query = f"site:{domain} {query}" if domain else query
        hits: list[SearchHit] = []

        try:
            with DDGS() as ddgs:
                results = ddgs.text(scoped_query, max_results=limit)
                for r in results:
                    hits.append(SearchHit(
                        title=r.get("title", ""),
                        snippet=r.get("body", ""),
                        url=r.get("href", ""),
                    ))
        except Exception as exc:
            logger.warning("DuckDuckGo search failed: %s", exc)

        self._cache[key] = hits
        if len(self._cache) > 64:
            self._cache.pop(next(iter(self._cache)), None)
        return hits

    @staticmethod
    def _clip(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars - 3].rstrip() + "..."
