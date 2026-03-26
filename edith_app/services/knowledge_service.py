from __future__ import annotations

try:
    import spacy
except ImportError:
    spacy = None

try:
    import wikipediaapi
except ImportError:
    wikipediaapi = None


class KnowledgeService:
    def __init__(self, user_agent: str, lightweight_mode: bool = True) -> None:
        self._wiki = (
            wikipediaapi.Wikipedia(user_agent=user_agent, language="en")
            if wikipediaapi is not None
            else None
        )
        self._nlp = None
        if spacy is not None and not lightweight_mode:
            try:
                self._nlp = spacy.load("en_core_web_sm")
            except Exception:
                self._nlp = spacy.blank("en")

    def summarize_topic(self, topic: str) -> str:
        if self._wiki is None:
            return "Wikipedia support is unavailable until Wikipedia-API is installed."
        page = self._wiki.page(topic)
        if not page.exists():
            return f"I couldn't find a Wikipedia page for {topic}."
        return "According to Wikipedia, " + " ".join(page.summary.split()[:70]).strip()

    def extract_entities(self, text: str) -> list[str]:
        if self._nlp is None:
            return []
        doc = self._nlp(text)
        return [ent.text for ent in doc.ents]
