"""
edith_app.core.neural_router
============================
LLM-first autonomous reasoning engine for EDITH.

Architecture:
  1. Build a rich context block (history + RAG + task state + pending state)
  2. Feed it to the LLM with the full TOOL_MANIFEST
  3. LLM picks a tool → ToolDispatcher executes it
  4. Result fed back → loop until LLM issues "reply"

The router is now the PRIMARY entry point for ALL requests (not a fallback).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from edith_app.config import AppConfig
from edith_app.core.tool_dispatcher import TOOL_MANIFEST, ToolDispatcher

logger = logging.getLogger("edith.neural_router")

# ── System persona prompt ──────────────────────────────────────────────────────
_PERSONA = """\
You are EDITH — local chief-of-staff AI: J.A.R.V.I.S. execution, Friday's composure and wit, EDITH loyalty.
You are NOT a chatbot. You reason, plan, use tools, and remember context across turns.

Core behaviour:
- Read intent, not keywords: infer goals, implicatures, and emotional subtext (stress, hurry, playfulness).
- Resolve references ("that", "the same", "undo it", "like before") from conversation + pending state.
- For yes/no/confirm: bind to the most recent pending action (WhatsApp draft, organize, purchase, etc.).
- Prefer a concrete tool call over vague prose. If unsure, pick the safest tool that advances the user's goal.
- Emotional intelligence: if the user is venting or low, one line of grounded empathy, then one actionable offer
  (task, break, automation, or listen). No therapy cosplay, no motivational poster tone.
- save_fact for durable preferences; search_memory for "what did I say / prefer / store".
- search_web only when fresh world facts are needed.
- Tone: crisp, warm, intelligent, occasional dry humor — never corporate, never sycophantic, never robotic.

MULTI-STEP EXECUTION (critical):
- If the user asks for MULTIPLE things in one message, execute them one at a time as separate tool calls.
- After each tool call, you will see its Result. READ the result and use it to decide the next action.
- Example flow for "list my tasks and open a YouTube video for the first one":
    Step 1: {"action": "list_tasks"}
    → Result: "- [pending] <Task A>\n- [pending] <Task B>"
    Step 2: {"action": "play_youtube", "query": "<Task A> tutorial"}
    Step 3: {"action": "reply", "input": "Your first pending task is <Task A>. I've opened a YouTube tutorial for it."}
- NEVER repeat a tool you already called with the same arguments.
- NEVER give up and say you cannot do something. Try the best available tool.
- When ALL parts of the request are done, call the 'reply' action to summarize.

Semantic domain knowledge (for task filtering):
  Networking: OSI, TCP/IP, TCP, UDP, OSPF, EIGRP, BGP, VLANs, STP, VTP, CDP, EtherChannel
  Monitoring/DevOps: Prometheus, Grafana, Docker, Kubernetes, Terraform, Ansible
  Cybersecurity: Burp Suite, Metasploit, Nmap, Wireshark, SIEM, Threat Hunting, OSINT
  Programming: Python, JavaScript, Kotlin, Java, React, API, SQL
  AI/ML: LLMs, RAG, Embeddings, Transformers, Fine-tuning, Vector DB

Context resolution:
  "those tasks" → refer to the last task list shown
  "undo that" → call undo_organize
  "the networking ones" → filter_tasks domain=networking mode=include
  "yes" after organize preview → call organize_folder with preview=false
"""


class NeuralRouter:
    """
    Primary intelligence router for EDITH.
    Routes all non-state-machine commands through LLM + ToolDispatcher.
    """

    def __init__(
        self,
        config: AppConfig,
        agent_service: Any,
        rag_service: Any,
        whatsapp_service: Any = None,
        tool_dispatcher: ToolDispatcher | None = None,
    ) -> None:
        self._config = config
        self._agent = agent_service
        self._rag = rag_service
        self._whatsapp = whatsapp_service
        self._dispatcher = tool_dispatcher
        # Injected by assistant after construction
        self._task_queue: Any | None = None

    def set_dispatcher(self, dispatcher: ToolDispatcher) -> None:
        self._dispatcher = dispatcher

    def process(
        self,
        user_prompt: str,
        vision_context: str = "",
        on_token: Callable[[str], None] | None = None,
        history: list[dict[str, str]] | None = None,
        pending_context: str = "",
        rag_context: str = "",
        *,
        voice_fast: bool = False,
        max_steps: int | None = None,
    ) -> str:
        """
        Full LLM-first ReAct loop.
        Returns a final reply string.
        """
        transcript: list[str] = []

        # ── 1. Inject conversation history ─────────────────────────────────────
        if history:
            for msg in history[-4:]:
                role = "User" if msg.get("role") == "user" else "EDITH"
                content = (msg.get("content") or "").strip()[:300]
                if content:
                    transcript.append(f"{role}: {content}")


        # ── 2. Inject vision if present ────────────────────────────────────────
        if vision_context:
            transcript.append(f"[Vision] {vision_context.strip()}")

        # ── 3. Build context header ────────────────────────────────────────────
        context_parts = []
        if pending_context:
            context_parts.append(f"[Pending State] {pending_context}")
        if rag_context:
            context_parts.append(f"[Memory] {rag_context}")
        if self._task_queue:
            try:
                pending = [t.title for t in self._task_queue.list() if t.status == "pending"]
                if pending:
                    context_parts.append(f"[Task Queue] {', '.join(pending[:12])}")
            except Exception:
                pass

        context_block = "\n".join(context_parts)
        transcript.append(f"User: {user_prompt}")

        # ── 4. ReAct loop ───────────────────────────────────────────────────────
        if max_steps is None:
            if voice_fast:
                max_steps = max(1, int(getattr(self._config, "neural_max_steps_voice", 2)))
            else:
                max_steps = max(1, int(getattr(self._config, "neural_max_steps", 4)))
        max_steps = max(1, min(max_steps, 8))
        contacts_hint = f"Known contacts: {list(self._config.whatsapp_display_names.keys())}"
        action_name_counts: dict[str, int] = {}  # Count per action name to detect true loops
        previous_action_str = None

        # Build the static prefix once — persona + tools + contacts + context never change mid-loop
        static_prefix = (
            f"{_PERSONA}\n\n"
            f"{TOOL_MANIFEST}\n\n"
            f"{contacts_hint}\n"
            f"{context_block}\n\n"
        )

        for step in range(max_steps):
            history_block = "\n".join(transcript)
            step_hint = (
                f"Step {step + 1} of max {max_steps}. "
                + (f"Actions taken so far: {list(action_name_counts.keys())}. " if action_name_counts else "")
                + "If a tool result is shown above, USE it to decide your next action. "
                + "When all parts of the user's request are done, use the 'reply' action."
            )
            # Only the per-step parts (hint + transcript) are built fresh each iteration
            react_prompt = (
                static_prefix
                + f"[{step_hint}]\n\n"
                + f"Conversation:\n{chr(10).join(transcript)}\n\n"
                + "Next JSON action:"
            )

            raw = self._agent.quick_think(react_prompt, history=[])
            raw = (raw or "").strip()
            logger.debug("NeuralRouter step=%d raw=%s", step, raw[:240])

            action_data = self._parse_action_data(raw)
            action = action_data.get("action")

            # Model returned raw prose — if it looks like a final answer, use it
            if action is None:
                cleaned = self._clean_reply(raw)
                if cleaned and len(cleaned) > 8:  # Has substance
                    if on_token:
                        on_token(cleaned)
                    return cleaned
                # Otherwise skip this step and let the model try again
                logger.debug("NeuralRouter step=%d: got prose with no substance, retrying", step)
                continue

            logger.info("NeuralRouter action=%s params=%s", action, {k: v for k, v in action_data.items() if k != "action"})

            # Anti-loop: track how many times each action name has been called.
            # Allow up to 2 of the same action (e.g. list then list again is OK once).
            # Only block on 3+ repeats of the same action name.
            action_name_counts[action] = action_name_counts.get(action, 0) + 1
            if action_name_counts[action] >= 3:
                logger.warning("NeuralRouter anti-loop: '%s' called %d times", action, action_name_counts[action])
                # Force a summary reply instead of a dead-end error message
                break
            previous_action_str = json.dumps(action_data, sort_keys=True)

            # Terminal action
            if action == "reply":
                reply = self._clean_reply(action_data.get("input", ""))
                if on_token:
                    on_token(reply)
                return reply

            # Dispatch to tool
            if self._dispatcher:
                result = self._dispatcher.dispatch(action, action_data)
            else:
                result = self._legacy_dispatch(action, action_data)

            # ── Tool Short-Circuit ──────────────────────────────────────────────────
            # If the tool explicitly needs to ask the user a question or confirm an
            # action, we bypass the ReAct loop entirely to prevent hallucination.
            if isinstance(result, str) and result.startswith("[USER_PROMPT]"):
                reply = result.replace("[USER_PROMPT]", "").strip()
                if on_token:
                    on_token(reply)
                return reply

            transcript.append(f'Tool[{action}]: {json.dumps({k: v for k, v in action_data.items() if k != "action"})}')
            transcript.append(f"Result: {str(result)[:800]}")

        # ── 5. Exceeded step limit or loop detected — force summary reply ──────────
        summary_prompt = (
            f"{_PERSONA}\n\n"
            f"Conversation:\n" + "\n".join(transcript) +
            "\n\nSummarise what you did and tell the user. Be concise.\n"
            '{"action": "reply", "input": "<your message>"}'
        )
        raw = self._agent.quick_think(summary_prompt, history=[])
        final = self._parse_action_data((raw or "").strip())
        reply = self._clean_reply(final.get("input") or raw or "Task complete.")
        if on_token:
            on_token(reply)
        return reply

    # ── Parse helpers ──────────────────────────────────────────────────────────

    def _parse_action_data(self, text: str) -> dict:
        """Robustly extract JSON action from model output."""
        # Strip markdown fences and replace smart quotes with straight quotes
        text = re.sub(r"```(?:json)?", "", text).strip()
        text = text.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")
        # Try direct parse first
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and "action" in obj:
                return obj
        except Exception:
            pass

        # Try wrapping in braces if the model forgot them (naked JSON keys)
        if '"action"' in text and not text.strip().startswith('{'):
            try:
                # Find the extent of the key-value pairs. Usually the model outputs something like:
                # "action": "reply", "input": "..."
                # We'll just wrap the whole thing and hope it parses.
                # Sometimes there's trailing conversational text, so let's try to grab up to the last quote.
                last_quote = text.rfind('"')
                if last_quote != -1:
                    wrapped = "{" + text[:last_quote+1] + "}"
                    obj = json.loads(wrapped)
                    if isinstance(obj, dict) and "action" in obj:
                        return obj
            except Exception:
                pass
        # Find first {...} block
        match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
        if not match:
            return {}
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        return {}

    def _clean_reply(self, text: str) -> str:
        if not text:
            return ""
        # Strip JSON artifacts that leaked into reply text (even malformed ones)
        text = re.sub(r'^\s*\{[^}]+\}\s*', "", text).strip()
        # Strip naked JSON strings
        text = re.sub(r'^\s*"action"\s*:\s*"[^"]+"\s*(?:,\s*"[^"]+"\s*:\s*(?:"[^"]*"|\[[^\]]*\]|true|false|\d+))*\s*', "", text).strip()
        # Strip filler openers
        text = re.sub(
            r"^(?:certainly[!,.]?\s*|absolutely[!,.]?\s*|of course[!,.]?\s*|"
            r"sure thing[!,.]?\s*|sure[!,.]?\s*|got it[!,.]?\s*|on it[!,.]?\s*)",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        if text and not text[0].isupper():
            text = text[0].upper() + text[1:]
        return text

    # ── Legacy dispatch (when no ToolDispatcher injected) ─────────────────────

    def _legacy_dispatch(self, action: str, data: dict) -> str:
        """Minimal fallback for the few actions that existed before ToolDispatcher."""
        if action == "search_memory":
            return self._search_memory(data.get("input", ""))
        if action == "powershell":
            return self._safe_powershell(data.get("input", ""))
        if action == "whatsapp_send":
            contact = self._resolve_whatsapp_name(data.get("contact", ""))
            if self._whatsapp:
                return self._whatsapp.send_message(contact, data.get("message", ""))
        if action == "whatsapp_call":
            contact = self._resolve_whatsapp_name(data.get("contact", ""))
            if self._whatsapp:
                video = bool(data.get("video", False))
                return self._whatsapp.video_call(contact) if video else self._whatsapp.voice_call(contact)
        if action == "whatsapp_read":
            return self._whatsapp.read_current_chat() if self._whatsapp else "WhatsApp unavailable."
        if action == "list_contacts":
            return json.dumps(self._config.whatsapp_display_names)
        return f"Action '{action}' not available in legacy mode."

    def _search_memory(self, query: str) -> str:
        if not isinstance(query, str):
            query = str(query)
        try:
            if hasattr(self._rag, "ask_docs"):
                return self._rag.ask_docs(query) or "No relevant memory found."
        except Exception as exc:
            logger.warning("Memory search failed: %s", exc)
        return "Memory offline."

    def _safe_powershell(self, command: str) -> str:
        import subprocess
        if not command:
            return "No command provided."
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

    def _resolve_whatsapp_name(self, name: str) -> str:
        lowered = name.lower().strip()
        configured = self._config.whatsapp_display_names.get(lowered)
        if configured:
            return configured
        for saved in self._config.contacts:
            if saved.lower() == lowered:
                d = self._config.whatsapp_display_names.get(saved.lower())
                return d if d else saved
        return name.strip()
