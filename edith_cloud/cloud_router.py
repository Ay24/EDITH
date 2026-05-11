"""
edith_cloud.cloud_router
==========================
Extended NeuralRouter with additional cloud-only actions:
  - generate_image  (Pollinations.ai)
  - web_search      (DDG SDK, structured)

All existing actions (powershell, search_memory, whatsapp_*, reply)
are inherited unchanged from the base NeuralRouter.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Any

from edith_app.config import AppConfig
from edith_app.core.neural_router import NeuralRouter, _REACT_SYSTEM, FORBIDDEN_PS_COMMANDS, PROTECTED_PROCESSES

logger = logging.getLogger("edith.cloud_router")

# Extended system prompt with cloud actions
_CLOUD_REACT_SYSTEM = _REACT_SYSTEM.rstrip() + """
  {"action": "generate_image", "input": "<image description>"}
  {"action": "web_search", "input": "<search query>"}

Additional cloud rules:
- Use "generate_image" when the user asks you to create, generate, or make an image.
- Use "web_search" for fast structured web search results.
- All other rules from above still apply.
"""


class CloudNeuralRouter(NeuralRouter):
    """
    JARVIS-level Neural Brain with cloud-accelerated actions.

    Inherits all local actions from NeuralRouter and adds:
      - generate_image → Pollinations.ai
      - web_search     → DuckDuckGo SDK
    """

    def __init__(
        self,
        config: AppConfig,
        agent_service: Any,
        rag_service: Any,
        whatsapp_service: Any = None,
        image_gen_service: Any = None,
        search_service: Any = None,
    ):
        super().__init__(config, agent_service, rag_service, whatsapp_service)
        self._image_gen = image_gen_service
        self._search = search_service

    def process(
        self,
        user_prompt: str,
        vision_context: str = "",
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """
        Runs the extended ReAct loop with cloud actions.
        """
        transcript: list[str] = []
        if vision_context:
            transcript.append(f"[Vision] {vision_context.strip()}")

        transcript.append(f"User: {user_prompt}")

        max_steps = 6  # one extra step for image gen
        for step in range(max_steps):
            history_block = "\n".join(transcript)
            react_prompt = (
                f"{_CLOUD_REACT_SYSTEM}\n\n"
                f"Known Contacts: {list(self._config.whatsapp_display_names.keys())}\n\n"
                f"Conversation so far:\n{history_block}\n\n"
                f"Your next JSON action:"
            )

            raw = self._agent.quick_think(react_prompt, history=[])
            raw = raw.strip() if raw else ""

            logger.debug("CloudBrain step=%d raw=%s", step, raw[:200])

            action_data = self._parse_action_data(raw)
            action = action_data.get("action")

            if action is None:
                reply = raw or "I've processed your request."
                reply = self._clean_reply(reply)
                if on_token:
                    on_token(reply)
                return reply

            logger.info("CloudBrain action=%s", action)

            if action == "reply":
                reply = self._clean_reply(action_data.get("input", ""))
                if on_token:
                    on_token(reply)
                return reply

            elif action == "generate_image":
                prompt = action_data.get("input", "")
                if self._image_gen:
                    result = self._image_gen.generate(prompt)
                else:
                    result = "Image generation service unavailable."
                transcript.append(f'Action: {{"action": "generate_image", "input": {json.dumps(prompt)}}}')
                transcript.append(f"Result: {result}")

            elif action == "web_search":
                query = action_data.get("input", "")
                if self._search:
                    result = self._search.summarize_query(query)
                else:
                    result = "Search service unavailable."
                transcript.append(f'Action: {{"action": "web_search", "input": {json.dumps(query)}}}')
                transcript.append(f"Results: {result[:800]}")

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

        # Step limit reached — summarize
        summary_prompt = (
            f"{_CLOUD_REACT_SYSTEM}\n\n"
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
