from __future__ import annotations

from dataclasses import dataclass
import html
import re
import urllib.parse

import requests


@dataclass(slots=True)
class SearchHit:
    title: str
    snippet: str
    url: str


class ResearchService:
    """Lightweight live-search summarizer with fast fallbacks."""

    def __init__(self) -> None:
        self._session = requests.Session()
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
        scoped_query = f"site:{domain} {query}" if domain else query
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(scoped_query)
        try:
            response = self._session.get(
                url,
                headers={"User-Agent": "Edith/1.0 research-service"},
                timeout=4.5,
            )
            response.raise_for_status()
            hits = self._parse_duckduckgo_html(response.text, limit=limit)
        except requests.RequestException:
            hits = []
        self._cache[key] = hits
        if len(self._cache) > 64:
            self._cache.pop(next(iter(self._cache)), None)
        return hits

    def _parse_duckduckgo_html(self, markup: str, limit: int) -> list[SearchHit]:
        blocks = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?(?:<a[^>]*class="result__snippet"[^>]*>(?P<snippet_a>.*?)</a>|<div[^>]*class="result__snippet"[^>]*>(?P<snippet_div>.*?)</div>)',
            markup,
            flags=re.IGNORECASE | re.DOTALL,
        )
        hits: list[SearchHit] = []
        for url, title, snippet_a, snippet_div in blocks:
            clean_title = self._clean_html(title)
            clean_snippet = self._clean_html(snippet_a or snippet_div)
            clean_url = html.unescape(url)
            if not clean_title:
                continue
            hits.append(SearchHit(title=clean_title, snippet=clean_snippet, url=clean_url))
            if len(hits) >= limit:
                break
        return hits

    def _clean_html(self, text: str) -> str:
        cleaned = re.sub(r"<[^>]+>", " ", text)
        cleaned = html.unescape(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _clip(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."
