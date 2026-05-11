"""
edith_app.core.neural_router
============================
JARVIS-level Neural Brain using a ReAct (Reason + Act) text loop.

Works with BOTH native llama-cpp-python AND Ollama backends.
Includes native support for OS control, RAG memory, and WhatsApp automation.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import Callable, Any

from edith_app.config import AppConfig

logger = logging.getLogger("edith.neural_router")

# ── Safety constants ───────────────────────────────────────────────────────────
FORBIDDEN_PS_COMMANDS = [
    "remove-item", "del ", "rm ", "rmdir", "rd ",
    "format", "clear-content", "set-content",
    "recycle", "remove-physicaldisk", "clear-disk",
]

PROTECTED_PROCESSES = {
    "ollama", "python", "edith", "svchost", "explorer",
    "system", "csrss", "lsass", "winlogon", "dwm", "smss",
}

# ── ReAct system prompt ────────────────────────────────────────────────────────
_REACT_SYSTEM = """\
You are EDITH, an autonomous AI desktop assistant. You think step-by-step and take actions.

On each turn you MUST output exactly ONE JSON object on a single line — nothing else:

  {"action": "powershell", "input": "<command>"}
  {"action": "search_memory", "input": "<query>"}
  {"action": "whatsapp_send", "contact": "<name>", "message": "<text>"}
  {"action": "whatsapp_call", "contact": "<name>", "video": false}
  {"action": "whatsapp_read", "input": ""}
  {"action": "list_contacts", "input": ""}
  {"action": "reply", "input": "<final message for the user>"}

Rules:
- Use "powershell" to open apps, control system, check RAM/processes. NEVER delete files.
- Use "search_memory" to look up facts, past conversations, or user preferences.
- Use "whatsapp_send" to send a message. ALWAYS confirm the contact name first if unsure.
- Use "whatsapp_call" to start a voice or video call.
- Use "whatsapp_read" to read the current open chat window.
- Use "list_contacts" to see a list of known contacts and their display names.
- Use "reply" ONLY when your goal is fully complete. This ends the loop.
- If the user just wants conversation (greetings, questions), go straight to "reply".
- Output ONLY the JSON line. No markdown. No explanation. No prose before/after the JSON.
"""


class NeuralRouter:
    """
    JARVIS-level Neural Brain using a ReAct text loop.
    """

    def __init__(self, config: AppConfig, agent_service: Any, rag_service: Any, whatsapp_service: Any = None):
        self._config = config
        self._agent = agent_service
        self._rag = rag_service
        self._whatsapp = whatsapp_service

    def process(
        self,
        user_prompt: str,
        vision_context: str = "",
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """
        Runs the ReAct loop to fulfil the user's prompt.
        """
        transcript: list[str] = []
        if vision_context:
            transcript.append(f"[Vision] {vision_context.strip()}")

        transcript.append(f"User: {user_prompt}")

        max_steps = 5
        for step in range(max_steps):
            history_block = "\n".join(transcript)
            react_prompt = (
                f"{_REACT_SYSTEM}\n\n"
                f"Known Contacts: {list(self._config.whatsapp_display_names.keys())}\n\n"
                f"Conversation so far:\n{history_block}\n\n"
                f"Your next JSON action:"
            )

            raw = self._agent.quick_think(react_prompt, history=[])
            raw = raw.strip() if raw else ""

            logger.debug("NeuralBrain step=%d raw=%s", step, raw[:200])

            # Parse the JSON action
            action_data = self._parse_action_data(raw)
            action = action_data.get("action")

            if action is None:
                reply = raw or "I've processed your request."
                reply = self._clean_reply(reply)
                if on_token:
                    on_token(reply)
                return reply

            logger.info("NeuralBrain action=%s", action)

            if action == "reply":
                reply = self._clean_reply(action_data.get("input", ""))
                if on_token:
                    on_token(reply)
                return reply

            elif action == "powershell":
                cmd = action_data.get("input", "")
                result = self._safe_powershell(cmd)
                transcript.append(f'Action: {{"action": "powershell", "input": {json.dumps(cmd)}}}')
                transcript.append(f"Result: {result[:800]}")

            elif action == "search_memory":
                query = action_data.get("input", "")
                result = self._search_memory(query)
                transcript.append(f'Action: {{"action": "search_memory", "input": {json.dumps(query)}}}')
                transcript.append(f"Memory: {result[:800]}")

            elif action == "whatsapp_send":
                contact = action_data.get("contact", "")
                msg = action_data.get("message", "")
                resolved = self._resolve_whatsapp_name(contact)
                if self._whatsapp:
                    res = self._whatsapp.send_message(resolved, msg)
                else:
                    res = "WhatsApp service unavailable."
                transcript.append(f'Action: {{"action": "whatsapp_send", "contact": "{contact}", "message": "{msg}"}}')
                transcript.append(f"Result: {res}")

            elif action == "whatsapp_call":
                contact = action_data.get("contact", "")
                video = bool(action_data.get("video", False))
                resolved = self._resolve_whatsapp_name(contact)
                if self._whatsapp:
                    res = self._whatsapp.video_call(resolved) if video else self._whatsapp.voice_call(resolved)
                else:
                    res = "WhatsApp service unavailable."
                transcript.append(f'Action: {{"action": "whatsapp_call", "contact": "{contact}", "video": {str(video).lower()}}}')
                transcript.append(f"Result: {res}")

            elif action == "whatsapp_read":
                if self._whatsapp:
                    res = self._whatsapp.read_current_chat()
                else:
                    res = "WhatsApp service unavailable."
                transcript.append(f'Action: {{"action": "whatsapp_read"}}')
                transcript.append(f"Chat Content: {res[:800]}")

            elif action == "list_contacts":
                contacts = self._config.whatsapp_display_names
                res = json.dumps(contacts, indent=2)
                transcript.append(f'Action: {{"action": "list_contacts"}}')
                transcript.append(f"Contacts: {res}")

            else:
                transcript.append(f"Error: unknown action '{action}'")

        summary_prompt = (
            f"{_REACT_SYSTEM}\n\n"
            f"Conversation so far:\n" + "\n".join(transcript) +
            "\n\nYou have reached the step limit. Summarise and reply to the user now.\n"
            'Output exactly: {"action": "reply", "input": "<your message>"}'
        )
        raw = self._agent.quick_think(summary_prompt, history=[])
        final_data = self._parse_action_data(raw.strip() if raw else "")
        reply = self._clean_reply(final_data.get("input") or raw or "Task complete.")
        if on_token:
            on_token(reply)
        return reply

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _parse_action_data(self, text: str) -> dict:
        """Extract JSON action object from the model's output."""
        text = re.sub(r"```(?:json)?", "", text).strip()
        match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
        if not match:
            return {}

        try:
            obj = json.loads(match.group())
            if "action" in obj:
                obj["action"] = str(obj["action"]).strip().lower()
            return obj
        except (json.JSONDecodeError, AttributeError):
            return {}

    def _clean_reply(self, text: str) -> str:
        """Remove common LLM artifacts from the final reply."""
        leak = re.search(r'(?i)reply_to_user\s*\(\s*["\'](.+?)["\']\s*\)', text, re.DOTALL)
        if leak:
            text = leak.group(1).strip()
        text = re.sub(r"```", "", text).strip()
        text = re.sub(r"^\s*(user|assistant|edith)\s*:\s*", "", text, flags=re.IGNORECASE)
        return text.strip() or "Done."

    def _safe_powershell(self, command: str) -> str:
        """Execute a PowerShell command with data-safety checks."""
        if not isinstance(command, str):
            command = str(command)
        lowered = command.lower()

        for forbidden in FORBIDDEN_PS_COMMANDS:
            if forbidden in lowered:
                return "Blocked: forbidden operation."

        if "stop-process" in lowered or "taskkill" in lowered:
            for proc in PROTECTED_PROCESSES:
                if proc in lowered:
                    return f"Blocked: critical process '{proc}'."

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True, text=True, timeout=15,
            )
            out = result.stdout.strip()
            err = result.stderr.strip()
            if err and not out:
                return f"Error: {err[:500]}"
            return out[:2000] if out else "Success."
        except Exception as exc:
            return f"Failed: {exc}"

    def _search_memory(self, query: str) -> str:
        """Query EDITH's RAG knowledge base."""
        if not isinstance(query, str):
            query = str(query)
        try:
            if hasattr(self._rag, "ask_docs"):
                return self._rag.ask_docs(query) or "No relevant memory found."
        except Exception as exc:
            logger.warning("Memory search failed: %s", exc)
        return "Memory offline."

    def _resolve_whatsapp_name(self, name: str) -> str:
        """Map config keys to actual WhatsApp display names."""
        lowered = name.lower().strip()
        configured = self._config.whatsapp_display_names.get(lowered)
        if configured:
            return configured
        return name.strip()
