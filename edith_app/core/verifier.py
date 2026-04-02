from __future__ import annotations

from edith_app.core.tool_registry import ToolObservation


class CoworkVerifier:
    def summarize_status(self, observations: list[ToolObservation]) -> str:
        important = []
        for item in observations:
            text = item.detail.strip()
            if not text:
                continue
            first_line = text.splitlines()[0]
            important.append(f"- {item.name}: {first_line}")
        if not important:
            return "I gathered context, but there is not enough verified evidence yet."
        return "\n".join(important[:6])
