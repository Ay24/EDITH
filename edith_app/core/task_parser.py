"""
task_parser.py  —  Auto-detect and extract tasks from user conversations.
Uses fast regex heuristics first; no LLM call needed for obvious patterns.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edith_app.core.task_engine import Priority

# ─── Trigger Patterns ────────────────────────────────────────────────────────

_TASK_TRIGGERS = re.compile(
    r"\b("
    r"i need to|i have to|i must|i should|remind me to|don't forget to|"
    r"need to finish|need to complete|make sure to|task:|todo:|"
    r"plan to|going to work on|working on|i want to|let's do|we need to|"
    r"my task is|remember this task|new task"
    r")\b",
    re.IGNORECASE,
)

_DEADLINE_PATTERNS = {
    r"\btoday\b": 0,
    r"\btomorrow\b": 1,
    r"\bthis week\b": 3,
    r"\bnext week\b": 7,
    r"\bin (\d+) days?\b": None,  # handled specially
    r"\bby (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b": None,
}

_PRIORITY_WORDS = {
    "high":   r"\b(urgent|asap|immediately|critical|high priority|important|must|crucial)\b",
    "medium": r"\b(soon|medium|moderate|mid)\b",
    "low":    r"\b(someday|low priority|eventually|when possible|nice to have)\b",
}

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}


def _extract_due_date(text: str) -> str | None:
    text_lower = text.lower()
    today = date.today()
    if re.search(r"\btoday\b", text_lower):
        return today.isoformat()
    if re.search(r"\btomorrow\b", text_lower):
        return (today + timedelta(days=1)).isoformat()
    if re.search(r"\bthis week\b", text_lower):
        return (today + timedelta(days=3)).isoformat()
    if re.search(r"\bnext week\b", text_lower):
        return (today + timedelta(days=7)).isoformat()
    m = re.search(r"\bin (\d+) days?\b", text_lower)
    if m:
        return (today + timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r"\bby (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text_lower)
    if m:
        target_day = _WEEKDAYS[m.group(1)]
        current_day = today.weekday()
        delta = (target_day - current_day) % 7 or 7
        return (today + timedelta(days=delta)).isoformat()
    return None


def _extract_priority(text: str) -> "Priority":
    for level, pattern in _PRIORITY_WORDS.items():
        if re.search(pattern, text, re.IGNORECASE):
            return level  # type: ignore[return-value]
    return "medium"


def _extract_title(text: str) -> str:
    """Strip trigger phrases and deadline markers to get a clean title."""
    cleaned = re.sub(_TASK_TRIGGERS, "", text, count=1).strip()
    cleaned = re.sub(
        r"\b(by tomorrow|by today|this week|next week|in \d+ days?|urgently|asap|immediately)\b",
        "", cleaned, flags=re.IGNORECASE,
    ).strip()
    # Capitalize first letter
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned[:120]  # cap at 120 chars


class TaskParser:
    """Stateless parser that detects likely tasks in user speech/text."""

    def should_create_task(self, text: str) -> bool:
        """Return True if the text likely contains a task intent."""
        return bool(_TASK_TRIGGERS.search(text))

    def parse(self, text: str, conversation_context: str = "") -> dict | None:
        """
        Returns a dict suitable for TaskEngine.create(**result) or None.
        """
        if not self.should_create_task(text):
            return None
        title     = _extract_title(text)
        if len(title) < 4:
            return None
        due_date  = _extract_due_date(text)
        priority  = _extract_priority(text)
        return {
            "title":       title,
            "description": text.strip()[:350],
            "priority":    priority,
            "due_date":    due_date,
            "context":     conversation_context[:200] if conversation_context else "",
        }
