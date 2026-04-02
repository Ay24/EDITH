from __future__ import annotations

from typing import Iterable

from edith_app.models import ChatMessage
from edith_app.services.agent_service import AgentService


class CoworkPlanner:
    def __init__(self, agent: AgentService) -> None:
        self._agent = agent

    def build_plan(self, goal: str, history: Iterable[ChatMessage], relevant_context: list[str]) -> str:
        context_block = "\n".join(f"- {item}" for item in relevant_context if item)
        prompt = (
            "Build a short execution plan for this user goal.\n"
            "Return 3 to 5 tight steps. Prefer actions that inspect, verify, and then conclude.\n"
        )
        if context_block:
            prompt += f"Relevant prior context:\n{context_block}\n"
        prompt += f"Goal: {goal}"
        plan = self._agent.plan(prompt, history)
        cleaned = "\n".join(line.strip() for line in plan.splitlines() if line.strip())
        return cleaned or "1. Inspect the workspace.\n2. Gather evidence.\n3. Summarize findings and next actions."
