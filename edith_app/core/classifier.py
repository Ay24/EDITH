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

        # Emotional / support — route before media so "play something I'm sad" still hits media;
        # we check emotional only when not clearly a media-first phrase
        self.emotional_patterns = [
            r"\b(i feel|i'm feeling|im feeling|feeling)\s+(sad|down|awful|terrible|anxious|stressed|overwhelmed|lost|empty|alone)\b",
            r"\b(i am|i'm|im)\s+(sad|depressed|anxious|stressed|exhausted|burnt out|burned out|overwhelmed|not okay|not ok)\b",
            r"\b(i hate my life|i can't cope|i need help|i'm scared|i am scared)\b",
            r"\b(i'm lonely|i am lonely|i feel lonely)\b",
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
                
        # 2. Emotional (short venting / state — not mixed with clear automation verbs)
        if not re.search(r"\b(play|open|search|set|turn|send|run|find)\b", lowered):
            for p in self.emotional_patterns:
                if re.search(p, lowered):
                    return Intent(lane="emotional", confidence=0.82, reason=f"Matched emotional pattern: {p}")

        # 3. Check Task
        for p in self.task_patterns:
            if re.search(r"\b" + p, lowered):
                return Intent(lane="cowork", confidence=0.85, reason=f"Matched task pattern: {p}")
                
        # 4. Check Media
        for p in self.media_patterns:
            if re.search(r"\b" + p, lowered):
                return Intent(lane="media", confidence=0.85, reason=f"Matched media pattern: {p}")
                
        # 5. Default to Chat
        return Intent(lane="chat", confidence=0.5, reason="Defaulting to general chat/intellectual inquiry")

    def _normalize(self, command: str) -> str:
        lowered = command.lower().strip()
        lowered = re.sub(
            r"^(edith[, ]+)?(can you|could you|would you|please|hey|hi|hello)\s+",
            "",
            lowered,
        )
        return lowered.strip()
