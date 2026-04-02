from __future__ import annotations

import re
from dataclasses import dataclass

from edith_app.core.planner import CoworkPlanner
from edith_app.core.session_memory import SessionMemory
from edith_app.core.tool_registry import ToolObservation, ToolRegistry
from edith_app.core.verifier import CoworkVerifier
from edith_app.models import ChatMessage
from edith_app.services.agent_service import AgentService


@dataclass(slots=True)
class CoworkRun:
    reply: str
    plan: str
    summary: str
    edit_brief: str = ""


class AgentLoop:
    def __init__(self, agent: AgentService, tools: ToolRegistry, memory: SessionMemory) -> None:
        self._agent = agent
        self._tools = tools
        self._memory = memory
        self._planner = CoworkPlanner(agent)
        self._verifier = CoworkVerifier()

    def run(self, goal: str, history: list[ChatMessage], mode: str = "cowork") -> CoworkRun:
        related = [
            f"{item.goal} -> {item.summary}"
            for item in self._memory.relevant(goal, limit=3)
        ]
        plan = self._planner.build_plan(goal, history, related)
        observations = self._execute(goal, mode)
        summary = self._verifier.summarize_status(observations)
        edit_brief = self._build_edit_brief(goal, history, observations) if mode in {"coding", "edit"} else ""
        reflection = self._agent.quick_think(
            "Summarize this cowork run for the user in a teammate-like way.\n"
            f"Goal: {goal}\n"
            f"Plan:\n{plan}\n"
            f"Verified observations:\n{summary}\n"
            f"Safe edit proposal:\n{edit_brief or 'None'}\n"
            "Be concise, useful, and action-oriented.",
            history,
        )
        reply = f"{reflection}\n\nPlan\n{plan}\n\nVerified\n{summary}"
        if edit_brief:
            reply += f"\n\nSafe Edit Proposal\n{edit_brief}"
        self._memory.add(goal=goal, plan=plan, summary=summary, mode=mode)
        return CoworkRun(reply=reply, plan=plan, summary=summary, edit_brief=edit_brief)

    def _execute(self, goal: str, mode: str) -> list[ToolObservation]:
        observations: list[ToolObservation] = [self._tools.workspace_snapshot(), self._tools.project_summary()]
        lowered = goal.lower()

        if mode in {"workspace", "coding", "cowork"}:
            observations.append(self._tools.run_compile_check())

        needles = self._extract_needles(goal)
        if "error" in lowered or "bug" in lowered or "crash" in lowered:
            needles.extend(["traceback", "error", "exception"])
        if "whatsapp" in lowered:
            needles.append("whatsapp")
        if "voice" in lowered or "speech" in lowered:
            needles.extend(["voice", "speech"])
        if "volume" in lowered:
            needles.append("volume")

        seen: set[str] = set()
        for needle in needles:
            if needle in seen:
                continue
            seen.add(needle)
            observations.append(self._tools.search_text(needle))
            observations.append(self._tools.search_filenames(needle))

        file_candidates = self._extract_paths(goal)
        for relative_path in file_candidates[:2]:
            observations.append(self._tools.read_file(relative_path))

        if mode == "browser":
            observations.append(self._tools.open_browser_search(goal))
        if mode in {"coding", "edit"}:
            observations.append(self._tools.suggest_edit_targets(goal))

        return observations

    def _build_edit_brief(self, goal: str, history: list[ChatMessage], observations: list[ToolObservation]) -> str:
        relevant = []
        for item in observations:
            if item.name in {"edit_targets", "search_text", "search_filenames"}:
                relevant.append(f"{item.name}:\n{item.detail}")
        prompt = (
            "Propose a safe edit plan only. Do not write code. "
            "List the likely files to touch, what to change, and what to verify after editing.\n"
            f"Goal: {goal}\n"
            f"Observations:\n{chr(10).join(relevant[:4])}"
        )
        return self._agent.plan(prompt, history)

    def _extract_needles(self, goal: str) -> list[str]:
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", goal)
        if quoted:
            return [item.strip() for item in quoted if item.strip()]
        words = [word.strip(".,:;!?()[]{}") for word in goal.lower().split()]
        return [word for word in words if len(word) >= 5][:4]

    def _extract_paths(self, goal: str) -> list[str]:
        return re.findall(r"[\w./\\-]+\.(?:py|md|txt|json|toml|yml|yaml)", goal, flags=re.IGNORECASE)
