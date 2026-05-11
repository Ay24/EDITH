from __future__ import annotations

import re
from typing import NamedTuple

class Intent(NamedTuple):
    lane: str
    confidence: float
    reason: str

class CommandClassifier:
    """Lightweight intent classification for rapid routing."""

    def __init__(self):
        # Direct System Patterns (High Confidence)
        self.system_patterns = [
            r"volume", r"mute", r"unmute", r"time", r"date", r"open", r"find file",
            r"lock pc", r"sleep pc", r"wifi", r"brightness", r"status",
        ]
        
        # Project/Task Patterns
        self.task_patterns = [
            r"cowork", r"task", r"analyze workspace", r"propose edit", r"queue",
        ]
        
        # Research/Media Patterns
        self.media_patterns = [
            r"play", r"youtube", r"spotify", r"search google", r"search the web", r"browse",
        ]

    def classify(self, command: str) -> Intent:
        lowered = self._normalize(command)
        
        # 1. Check System
        for p in self.system_patterns:
            if re.search(r"\b" + p, lowered):
                return Intent(lane="system", confidence=0.9, reason=f"Matched system pattern: {p}")
                
        # 2. Check Task
        for p in self.task_patterns:
            if re.search(r"\b" + p, lowered):
                return Intent(lane="cowork", confidence=0.85, reason=f"Matched task pattern: {p}")
                
        # 3. Check Media
        for p in self.media_patterns:
            if re.search(r"\b" + p, lowered):
                return Intent(lane="media", confidence=0.85, reason=f"Matched media pattern: {p}")
                
        # 4. Default to Chat
        return Intent(lane="chat", confidence=0.5, reason="Defaulting to general chat/intellectual inquiry")

    def _normalize(self, command: str) -> str:
        lowered = command.lower().strip()
        lowered = re.sub(
            r"^(edith[, ]+)?(can you|could you|would you|please|hey|hi|hello)\s+",
            "",
            lowered,
        )
        return lowered.strip()
