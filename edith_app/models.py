from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


MessageSource = Literal["system", "user", "assistant", "error"]


@dataclass(slots=True)
class ChatMessage:
    source: MessageSource
    text: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class CommandResult:
    reply: str
    action: str = "reply"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AssistantSnapshot:
    mode: str
    ai_enabled: bool
    voice_enabled: bool
    audio_enabled: bool
