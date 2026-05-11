from __future__ import annotations

from dataclasses import dataclass

from edith_app.core.specialist_prompts import SPECIALIST_PROMPTS


@dataclass(slots=True)
class SpecialistProfile:
    key: str
    lane: str
    title: str
    system_instruction: str


class SpecialistRegistry:
    """Compact specialist catalogue inspired by multi-agent assistant systems."""

    def __init__(self) -> None:
        self._profiles = {
            "cowork": SpecialistProfile(
                key="cowork_engineer",
                lane="cowork",
                title="Cowork Engineer",
                system_instruction=(
                    "You are Edith's cowork engineering specialist. Inspect carefully, reason in steps, "
                    "surface risks early, and prefer practical, low-risk next actions. "
                    f"{SPECIALIST_PROMPTS['cowork']}"
                ),
            ),
            "system": SpecialistProfile(
                key="system_operator",
                lane="system",
                title="System Operator",
                system_instruction=(
                    "You are Edith's system operations specialist. Be precise, safe, concise, and execution-minded. "
                    "Avoid unnecessary explanation when the requested action is straightforward. "
                    f"{SPECIALIST_PROMPTS['system']}"
                ),
            ),
            "media": SpecialistProfile(
                key="media_concierge",
                lane="media",
                title="Media Concierge",
                system_instruction=(
                    "You are Edith's media and web specialist. Be quick, friendly, and natural. "
                    "Optimize for smooth, low-friction interaction. "
                    f"{SPECIALIST_PROMPTS['media']}"
                ),
            ),
            "memory": SpecialistProfile(
                key="memory_keeper",
                lane="memory",
                title="Memory Keeper",
                system_instruction=(
                    "You are Edith's memory and continuity specialist. Preserve context, recall the most relevant details, "
                    "and keep responses warm and dependable. "
                    f"{SPECIALIST_PROMPTS['memory']}"
                ),
            ),
            "chat": SpecialistProfile(
                key="conversation_companion",
                lane="chat",
                title="Conversation Companion",
                system_instruction=(
                    "You are Edith's conversation specialist. Sound calm, intelligent, natural, and lightly witty, "
                    "like a polished JARVIS-style assistant. "
                    f"{SPECIALIST_PROMPTS['chat']}"
                ),
            ),
        }

    def get(self, lane: str) -> SpecialistProfile:
        return self._profiles.get(lane, self._profiles["chat"])
