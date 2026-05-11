from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(slots=True)
class RouteDecision:
    lane: str
    confidence: float
    reason: str


class ToolRouter:
    """Routes requests into high-level EDITH lanes before command execution."""

    def __init__(self) -> None:
        self._cowork_prefixes = (
            "cowork on ",
            "analyze workspace",
            "analyze this project",
            "coding task ",
            "propose edit for ",
            "browser task ",
            "queue task ",
            "show tasks",
            "show cowork tasks",
            "list tasks",
            "task list",
            "next task",
            "next cowork task",
            "complete task ",
            "clear done tasks",
            "clear completed tasks",
            "what were we working on",
            "resume cowork",
            "resume our work",
            "cowork mode",
            "co work mode",
            "co-work mode",
        )
        self._media_prefixes = (
            "open youtube",
            "open amazon",
            "open amazon.in",
            "youtube",
            "open yt",
            "yt",
            "play ",
            "youtube mix",
            "open spotify",
            "spotify search",
            "spotify playlist",
            "open github",
            "open stack",
            "open stack overflow",
            "open stackoverflow",
            "open gmail",
            "open google",
            "google",
            "search google for",
            "search the web for",
            "look up ",
            "browse ",
            "latest news",
            "news",
            "latest news please",
        )
        self._memory_prefixes = (
            "self improve",
            "self-improve",
            "propose skill for ",
            "save note",
            "send message to",
            "message ",
            "text ",
            "call ",
            "video call ",
            "read my whatsapp messages",
            "read my messages",
            "read whatsapp messages",
        )
        self._system_prefixes = (
            "open folder ",
            "analyze ",
            "preview organize ",
            "organize ",
            "organise ",
            "organised ",
            "organized ",
            "smart organize ",
            "clean ",
            "declutter ",
            "undo last organization",
            "undo organization",
            "revert last organization",
            "move ",
            "find file ",
            "find folder ",
            "find ",
            "open calculator",
            "open notepad",
            "open settings",
            "open explorer",
            "open files",
            "open downloads",
            "open documents",
            "open desktop",
            "go to ",
            "open ",
            "time",
            "what is the time",
            "the time",
            "date",
            "what is the date",
            "today's date",
            "todays date",
            "mute",
            "unmute",
            "set volume",
            "volume",
            "change volume",
            "increase volume",
            "decrease volume",
            "brightness",
            "set brightness",
            "brightness to",
            "increase brightness",
            "decrease brightness",
            "raise brightness",
            "lower brightness",
            "turn brightness",
            "wifi ",
            "bluetooth ",
            "check updates",
            "check for updates",
            "update apps",
            "upgrade apps",
            "update everything",
            "lock pc",
            "lock system",
            "lock computer",
            "turn off",
            "shutdown",
            "shut down",
            "restart",
            "reboot",
            "sleep pc",
            "sleep system",
            "put computer to sleep",
            "run preflight",
            "preflight",
            "system preflight",
            "export debug bundle",
            "export diagnostics",
            "debug bundle",
            "status",
            "system status",
            "command list",
            "commands list",
            "show commands",
            "voice profile ",
            "set voice ",
            "voice edith",
            "voice jarvis",
            "voice friday",
            "focus mode",
            "start focus mode",
            "start research mode",
            "research mode",
            "start coding mode",
            "coding mode",
            "start cinematic mode",
            "cinematic mode",
        )

    def route(self, command: str) -> RouteDecision:
        lowered = self._normalize(command)
        if not lowered:
            return RouteDecision("chat", 0.5, "empty")
        if lowered.startswith(self._cowork_prefixes):
            return RouteDecision("cowork", 0.98, "matched cowork prefix")
        if lowered.startswith(self._system_prefixes):
            return RouteDecision("system", 0.9, "matched system or file flow")
        if lowered.startswith(self._memory_prefixes) or any(token in lowered for token in ("self improve", "note this")):
            return RouteDecision("memory", 0.9, "matched memory or messaging flow")
        if lowered.startswith(self._media_prefixes) or any(token in lowered for token in ("youtube", "spotify", "wikipedia", "news")):
            return RouteDecision("media", 0.88, "matched media or browser flow")
        if self._looks_like_system_intent(lowered):
            return RouteDecision("system", 0.78, "matched system intent tokens")
        if self._looks_like_media_intent(lowered):
            return RouteDecision("media", 0.78, "matched media intent tokens")
        return RouteDecision("chat", 0.65, "default conversational fallback")

    def _normalize(self, command: str) -> str:
        lowered = command.lower().strip()
        lowered = re.sub(
            r"^(edith[, ]+)?(can you|could you|would you|please|hey|hi|hello)\s+",
            "",
            lowered,
        )
        lowered = re.sub(r"^(edith[, ]+)", "", lowered).strip()
        return lowered

    def _looks_like_system_intent(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in (
                "open ",
                "set volume",
                "set brightness",
                "wifi",
                "bluetooth",
                "shutdown",
                "restart",
                "sleep",
                "lock",
                "organize",
                "analyze folder",
            )
        )

    def _looks_like_media_intent(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in (
                "play ",
                "youtube",
                "spotify",
                "search the web",
                "search google",
                "look up",
                "browse",
            )
        )
