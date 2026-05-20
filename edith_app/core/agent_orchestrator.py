"""
Multi-agent orchestration layer for EDITH OS.
Routes classified intents to specialist agents; falls through to NeuralRouter when needed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("edith.orchestrator")


@dataclass(slots=True)
class AgentResult:
    handled: bool
    reply: str = ""
    action: str = "orchestrator"
    lane: str = "chat"


class AgentOrchestrator:
    """
    Coordinates specialist agents. Each agent is a thin handler — not a separate LLM
  unless the lane requires deep reasoning (delegated to NeuralRouter).
    """

    LANES = (
        "system",
        "media",
        "cowork",
        "memory",
        "automation",
        "productivity",
        "emotional",
        "web",
        "coding",
        "chat",
    )

    def __init__(self, services: dict[str, Any], pattern_router: Any, tool_dispatcher: Any) -> None:
        self._services = services
        self._pattern_router = pattern_router
        self._tool_dispatcher = tool_dispatcher
        self._emotional_markers = re.compile(
            r"\b(sad|stressed|anxious|worried|tired|frustrated|upset|lonely|overwhelmed|"
            r"depressed|exhausted|scared|hopeless|burnt out|burned out|not okay|not ok|i feel|i'm feeling)\b",
            re.I,
        )

    def route(self, command: str, lane: str) -> AgentResult | None:
        lowered = command.lower().strip()
        if not lowered:
            return None

        if lane == "emotional":
            return self._route_emotional(command)

        if lane == "system":
            return self._route_system(lowered)
        if lane == "media":
            return self._route_media(lowered)
        if lane == "cowork":
            return self._route_cowork(lowered)
        if lane == "memory":
            return self._route_memory(lowered)
        if lane == "automation" or lane == "productivity":
            routed = self._pattern_router.route(lowered)
            if routed:
                try:
                    out = self._tool_dispatcher.dispatch(routed.action, routed.params)
                    return AgentResult(True, out.replace("[USER_PROMPT]", "").strip(), lane=lane)
                except Exception as exc:
                    logger.warning("Orchestrator dispatch failed: %s", exc)
        if self._emotional_markers.search(command) and lane == "chat":
            return self._route_emotional(command)
        return None

    def _route_system(self, lowered: str) -> AgentResult | None:
        routed = self._pattern_router.route(lowered)
        if not routed:
            return None
        try:
            out = self._tool_dispatcher.dispatch(routed.action, routed.params)
            return AgentResult(True, out.replace("[USER_PROMPT]", "").strip(), lane="system")
        except Exception:
            return None

    def _route_media(self, lowered: str) -> AgentResult | None:
        media = self._services.get("media")
        if media is None:
            return None
        if "youtube" in lowered or "play" in lowered:
            q = lowered.replace("play", "").replace("youtube", "").strip()
            if q:
                return AgentResult(True, media.play_youtube(q), lane="media")
        if "spotify" in lowered:
            q = lowered.replace("spotify", "").replace("play", "").strip()
            if q:
                return AgentResult(True, media.play_spotify(q), lane="media")
        return None

    def _route_cowork(self, lowered: str) -> AgentResult | None:
        cowork = self._services.get("cowork")
        if cowork is None:
            return None
        if "sync" in lowered or "status" in lowered:
            try:
                return AgentResult(True, cowork.status_summary(), lane="cowork")
            except Exception:
                pass
        return None

    def _route_memory(self, lowered: str) -> AgentResult | None:
        memory = self._services.get("memory")
        rag = self._services.get("rag")
        if "remember" in lowered and memory is not None:
            fact = lowered.split("remember", 1)[-1].strip(" :.-")
            if fact:
                memory.save_fact(fact)
                return AgentResult(True, "Noted.", lane="memory")
        if rag is not None and rag.available and ("recall" in lowered or "what did i" in lowered):
            try:
                hits = rag.get_user_memory(lowered, limit=3)
                if hits:
                    lines = [h.text if hasattr(h, "text") else str(h) for h in hits]
                    return AgentResult(True, "\n".join(lines), lane="memory")
            except Exception:
                pass
        return None

    def _route_emotional(self, command: str) -> AgentResult | None:
        """Brief FRIDAY-style grounding for short emotional cues; defer depth to LLM."""
        text = command.strip()
        words = text.split()
        if len(words) > 14:
            return None
        lowered = text.lower()

        if any(x in lowered for x in ("exhausted", "tired", "can't sleep", "cant sleep", "burnt out", "burned out")):
            reply = "You're running hot. Want me to clear the deck — tasks, focus playlist, or ten minutes of quiet?"
        elif any(x in lowered for x in ("anxious", "stressed", "overwhelmed", "panic")):
            reply = "Understood. One thing at a time: pick the single fire you want me to put out first."
        elif any(x in lowered for x in ("sad", "lonely", "down", "depressed", "empty")):
            reply = "I'm here. No performance needed. Want to talk it through, or should I handle something concrete for you?"
        elif "scared" in lowered or "afraid" in lowered:
            reply = "I've got you. Name what's in front of you — we'll tackle it step by step."
        else:
            reply = "Noted. Tell me what you need handled first; I'll take point."

        return AgentResult(True, reply, lane="emotional")
