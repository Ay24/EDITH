from __future__ import annotations

import collections
import json
import re
import subprocess
import urllib.parse
import webbrowser
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from edith_app.core.agent_loop import AgentLoop
from edith_app.core.session_memory import SessionMemory
from edith_app.core.task_queue import TaskQueue
from edith_app.core.tool_registry import ToolRegistry
from edith_app.config import AppConfig
from edith_app.models import AssistantSnapshot, ChatMessage, CommandResult
from edith_app.services.agent_service import AgentService
from edith_app.services.audio_service import AudioService
from edith_app.services.connectivity_service import ConnectivityService
from edith_app.services.knowledge_service import KnowledgeService
from edith_app.services.logging_service import get_logger, RunLogger
from edith_app.services.media_service import MediaService
from edith_app.services.memory_service import MemoryService
from edith_app.services.notes_service import NotesService
from edith_app.services.app_control_service import AppControlService
from edith_app.services.browser_control_service import BrowserControlService, BrowserPurchasePlan
from edith_app.services.desktop_automation_service import DesktopAutomationService
from edith_app.services.self_improve_service import SelfImproveService
from edith_app.services.system_service import SystemService
from edith_app.services.vision_service import VisionService
from edith_app.services.voice_service import VoiceService
from edith_app.services.whatsapp_service import WhatsAppService
from edith_app.services.rag_service import RagService
from edith_app.core.neural_router import NeuralRouter
from edith_app.core.semantic_classifier import SemanticClassifier
from edith_app.core.tool_dispatcher import ToolDispatcher

try:
    import phonenumbers
except ImportError:
    phonenumbers = None


class EdithAssistant:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.history: list[ChatMessage] = []
        self.logger = get_logger("edith.assistant", config.runtime_log_path)
        self.run_logger = RunLogger(str(config.project_root / "edith_runs"))
        self.agent = AgentService(config)
        self.audio = AudioService()
        self.voice = VoiceService(config)
        self.voice.set_agent(self.agent)
        self.voice.on_interrupt = self.audio.stop
        self.connectivity = ConnectivityService()
        self.knowledge = KnowledgeService(
            user_agent=f"{config.persona.name}/3.0 desktop assistant",
            lightweight_mode=config.lightweight_mode,
        )
        self.media = MediaService(config)
        self.memory = MemoryService(config.memory_path)
        self.session_memory = SessionMemory(config.session_memory_path)
        self.task_queue = TaskQueue(config.cowork_tasks_path)
        from edith_app.core.task_storage import TaskStorage
        from edith_app.core.task_engine import TaskEngine
        self.task_engine = TaskEngine(TaskStorage(config.tasks_path))
        self.notes = NotesService(config.notes_path)
        self.app_control = AppControlService()
        self.self_improve = SelfImproveService(
            project_root=str(config.project_root),
            telemetry_path=config.telemetry_path,
            overrides_path=config.self_improve_overrides_path,
            agent=self.agent,
        )
        self.vision = VisionService(config)
        self.system = SystemService(self.vision, config.organization_manifest_path)
        self.desktop_automation = DesktopAutomationService(self.system, config.automation_timing)
        self.browser_control = BrowserControlService(self.system)
        self.whatsapp = WhatsAppService(config.automation_timing)
        self.cowork = AgentLoop(
            self.agent,
            ToolRegistry(str(config.project_root)),
            self.session_memory,
        )
        self._pending_suggestion: str | None = None
        self._pending_message_contact: str | None = None
        self._pending_organization: tuple[str, bool] | None = None
        self._pending_whatsapp_draft: tuple[str, str] | None = None  # (contact, drafted_message)
        self._pending_whatsapp_call: tuple[str, bool] | None = None  # (contact, video)
        self._pending_browser_purchase: BrowserPurchasePlan | None = None
        self._pending_browser_summary_approved: bool = False
        self._suggestion_cooldown_turns = 0
        self._stream_callback: Any | None = None
        self._short_term_context: collections.deque[dict[str, str]] = collections.deque(maxlen=8)
        self.rag = RagService(config)
        self._handle_lock = threading.Lock()
        self._voice_session_active = False
        # Per-turn memory cache — reset on each handle() call to avoid stale reads
        self._turn_memory_cache: list | None = None

        # ── Build ToolDispatcher (wires all services to the LLM tool layer) ───
        def _pending_cb(kind: str, value: Any) -> None:
            if kind == "organization":
                self._pending_organization = value
            elif kind == "message_contact":
                self._pending_message_contact = value
            elif kind == "whatsapp_draft":
                self._pending_whatsapp_draft = value
            elif kind == "whatsapp_call":
                self._pending_whatsapp_call = value

        self._tool_dispatcher = ToolDispatcher({
            "system": self.system,
            "media": self.media,
            "audio": self.audio,
            "whatsapp": self.whatsapp,
            "task_queue": self.task_queue,
            "rag": self.rag,
            "notes": self.notes,
            "cowork": self.cowork,
            "agent": self.agent,
            "knowledge": self.knowledge,
            "connectivity": self.connectivity,
            "config": config,
            "context_history_fn": self._context_history,
            "pending_callback": _pending_cb,
        })

        self.neural_router = NeuralRouter(
            config, self.agent, self.rag, self.whatsapp,
            tool_dispatcher=self._tool_dispatcher,
        )
        self.neural_router._task_queue = self.task_queue
        # Use the module-level singleton — avoids creating 3 separate classifier instances
        from edith_app.core.semantic_classifier import _classifier as _sem_singleton
        self._semantic = _sem_singleton

        # Layer 0: pattern router — instantiated once, costs ~0ms per route
        from edith_app.core.router_utils import PatternRouter
        self._pattern_router = PatternRouter()

        from edith_app.core.jarvis_brain import JarvisBrain
        from edith_app.core.agent_orchestrator import AgentOrchestrator
        self.brain = JarvisBrain(config, self.task_queue, self.session_memory)
        self.orchestrator = AgentOrchestrator(
            {
                "system": self.system,
                "media": self.media,
                "memory": self.memory,
                "rag": self.rag,
                "cowork": self.cowork,
                "whatsapp": self.whatsapp,
            },
            self._pattern_router,
            self._tool_dispatcher,
        )
        self._brain_started = False

        # RAG cache: avoid redundant embedding calls for the same query
        self._rag_cache: dict[str, str] = {}
        self._rag_cache_max = 30

    def set_stream_callback(self, callback: Any) -> None:
        """Register a UI token callback for real-time streaming display."""
        self._stream_callback = callback

    def set_suggestion_callback(self, callback: Any) -> None:
        self._suggestion_callback = callback
        if not self._brain_started and callback is not None:
            try:
                self.brain.start(callback, task_manager=self.task_engine)
                self._brain_started = True
            except Exception:
                self.logger.debug("JarvisBrain start failed", exc_info=True)

    def set_ui_callback(self, callback: Any) -> None:
        self._ui_callback = callback

    def start_voice_session(self) -> None:
        self._voice_session_active = True
        self.voice.on_wake = self._on_voice_wake
        try:
            self.voice.start_session()
        except Exception:
            self.logger.debug("voice start_session failed", exc_info=True)

    def _on_voice_wake(self, source: str) -> None:
        self.logger.info("Wake detected: %s", source)
        if self._ui_callback:
            try:
                self._ui_callback("wake", source)
            except Exception:
                pass

    def stop_voice_session(self) -> None:
        self._voice_session_active = False
        try:
            self.voice.stop_session()
        except Exception:
            self.logger.debug("voice stop_session failed", exc_info=True)

    def open_task_dashboard(self, root: Any) -> None:
        try:
            from edith_app.ui_dashboard import TaskDashboardUI
            if not hasattr(self, '_dashboard_ui') or not self._dashboard_ui.is_open():
                self._dashboard_ui = TaskDashboardUI(root, self.task_queue)
            else:
                self._dashboard_ui.window.lift()
        except Exception as e:
            self.logger.error(f"Failed to open task dashboard: {e}")

    @property
    def task_manager(self) -> Any:
        # Provide an adapter for the UI's task_manager expectations
        class _TaskMgrAdapter:
            def __init__(self, tq):
                self.tq = tq
            def cowork_summary(self):
                return self.tq.summary()
            def next_task(self):
                return self.tq.next_task()
        return _TaskMgrAdapter(self.task_queue)

    def snapshot(self) -> AssistantSnapshot:
        return AssistantSnapshot(
            mode="Local Agent Command Center + Coworker Mode",
            ai_enabled=self.agent.enabled,
            voice_enabled=self.voice.enabled,
            audio_enabled=self.audio.system_audio_enabled,
        )

    def greet(self) -> str:
        remembered = self.memory.recent(limit=4, include_actions={"agent", "brainstorm", "plan", "think", "quick", "note"})
        greeting = (
            f"{self.config.persona.name} online. Local agent, voice controls, media automations, "
            "desktop routines, and coworker mode are ready."
        )
        if remembered:
            greeting += f" I restored {len(remembered)} recent conversation memories."
        self._remember("assistant", greeting)
        return greeting

    def speak(self, text: str) -> None:
        self.audio.speak(text)

    def stop_speaking(self) -> None:
        self.audio.stop()

    def listen_once(self) -> str:
        return self.voice.listen_once()

    def listen_for_command(self) -> str:
        return self.voice.listen_for_command(timeout=self.config.voice_command_timeout)

    def listen_for_interrupt(self) -> str:
        return self.voice.listen_for_interrupt()

    def handle(self, command: str) -> CommandResult:
        # Reset the per-turn memory cache so each new command gets a fresh read
        self._turn_memory_cache = None
        with self._handle_lock:
            result = self._handle_internal(command)
        # Log outside the lock — file I/O should not block the next command
        if hasattr(self, 'run_logger'):
            self.run_logger.log_interaction(command, result.reply, result.action)
        return result

    def _handle_internal(self, command: str) -> CommandResult:
        """
        LLM-first command handler.

        Layer 0a — Smalltalk fast-path (~0 ms, no LLM, no regex)
          Instantly returns canned replies for greetings/chitchat.

        Layer 0b — Pattern Router (~0 ms, no LLM)
          Catches deterministic commands via regex.

        Layer 1 — State Machine (hardcoded, ~0 ms)
          Resolves any pending confirmation flows.

        Layer 2 — LLM Tool-Calling Router
          Everything else is routed through NeuralRouter.
        """
        command = command.strip()
        lowered = command.lower().strip()
        self._remember("user", command)
        self.logger.info("handle: %s", lowered[:180])

        # ── Layer 0a: Smalltalk fast-path ──────────────────────────────────────────
        # Skip if any pending state exists (confirmations must still flow through)
        _no_pending = (
            not self._pending_whatsapp_draft
            and not self._pending_whatsapp_call
            and not self._pending_organization
            and not self._pending_message_contact
            and not self._pending_suggestion
            and not self._pending_browser_purchase
        )
        if _no_pending:
            smalltalk = self._smalltalk_reply(command)
            if smalltalk:
                r = CommandResult(smalltalk, action="system")
                self._remember("assistant", r.reply)
                return r

        # ── Layer 0a.5: Multi-agent orchestrator (classifier lanes) ───────────────
        if _no_pending:
            try:
                lane = self.brain.classify_intent(command)
                orch = self.orchestrator.route(command, lane)
                if orch and orch.handled and orch.reply:
                    r = CommandResult(orch.reply, action=orch.action)
                    self._remember("assistant", r.reply)
                    return r
            except Exception:
                self.logger.debug("Orchestrator route skipped", exc_info=True)

        # ── Layer 0b: Instant Pattern Router ─────────────────────────────────────
        if _no_pending:
            routed = self._pattern_router.route(lowered)
            if routed:
                try:
                    result_str = self._tool_dispatcher.dispatch(routed.action, routed.params)
                    # Strip [USER_PROMPT] prefix if present
                    clean = result_str.replace("[USER_PROMPT]", "").strip()
                    r = CommandResult(clean, action="system")
                    self._remember("assistant", r.reply)
                    return r
                except Exception as e:
                    self.logger.warning("Layer0 dispatch failed: %s", e)
                    # Fall through to LLM

            # ── Layer 0b.5: Message contact fast-path ─────────────────────────
            # Catches "message dhrishya", "text mom", etc. — sets pending state
            # so the next turn captures the message content. Zero LLM cost.
            contact_name = self._is_message_contact_only_command(lowered)
            if contact_name:
                self._pending_message_contact = contact_name
                reply = f"What would you like to say to {contact_name.title()}?"
                r = CommandResult(reply, action="message")
                self._remember("assistant", r.reply)
                return r

        # ── Layer 1a: WhatsApp draft confirmation ──────────────────────────────
        if self._pending_whatsapp_draft:
            contact, draft = self._pending_whatsapp_draft
            if lowered in {"yes", "yes send it", "send it", "go ahead", "confirm", "send"}:
                self._pending_whatsapp_draft = None
                res = self.whatsapp.send_message(contact, draft)
                result = CommandResult(res, action="message")
                self._remember("assistant", result.reply)
                return result
            if lowered in {"no", "cancel", "nope", "don't send", "discard"}:
                self._pending_whatsapp_draft = None
                result = CommandResult("Draft discarded.", action="message")
                self._remember("assistant", result.reply)
                return result
            self._pending_whatsapp_draft = None

        # ── Layer 1a.5: WhatsApp call confirmation ──────────────────────────────
        if self._pending_whatsapp_call:
            contact, video = self._pending_whatsapp_call
            if lowered in {"yes", "yes call", "call", "go ahead", "confirm"}:
                self._pending_whatsapp_call = None
                res = self.whatsapp.video_call(contact) if video else self.whatsapp.voice_call(contact)
                result = CommandResult(res, action="message")
                self._remember("assistant", result.reply)
                return result
            if lowered in {"no", "cancel", "nope", "don't call", "discard"}:
                self._pending_whatsapp_call = None
                result = CommandResult("Call cancelled.", action="message")
                self._remember("assistant", result.reply)
                return result
            self._pending_whatsapp_call = None

        # ── Layer 1b: Browser purchase confirmation ────────────────────────────
        if self._pending_browser_purchase:
            if lowered in {"approve summary", "summary approved", "yes summary", "looks good"}:
                self._pending_browser_summary_approved = True
                result = CommandResult(
                    "Summary approved. Say 'confirm place order' to execute.", action="browser"
                )
                self._remember("assistant", result.reply)
                return result
            if lowered in {"confirm place order", "place order", "confirm buy", "buy now", "yes place order"}:
                if not self._pending_browser_summary_approved:
                    summary = self.browser_control.summarize_purchase_plan(self._pending_browser_purchase)
                    result = CommandResult(
                        f"{summary}\n\nSay 'approve summary' first.", action="browser"
                    )
                    self._remember("assistant", result.reply)
                    return result
                plan = self._pending_browser_purchase
                self._pending_browser_purchase = None
                self._pending_browser_summary_approved = False
                result = CommandResult(self.browser_control.confirm_place_order(plan), action="browser")
                self._remember("assistant", result.reply)
                return result
            if lowered in {"cancel order", "cancel purchase", "no"}:
                self._pending_browser_purchase = None
                self._pending_browser_summary_approved = False
                result = CommandResult("Purchase cancelled.", action="browser")
                self._remember("assistant", result.reply)
                return result

        # ── Layer 1c: Organization confirmation ───────────────────────────────
        if self._pending_organization:
            target, by_context = self._pending_organization
            if lowered in {"yes", "yes do it", "do it", "go ahead", "apply", "confirm", "sure"}:
                self._pending_organization = None
                fn = self.system.organize_folder_by_context if by_context else self.system.organize_folder
                result = CommandResult(fn(target), action="files")
                self._remember("assistant", result.reply)
                return result
            if lowered in {"no", "nope", "cancel", "not that"}:
                self._pending_organization = None
                result = CommandResult("Okay, cancelled that.", action="files")
                self._remember("assistant", result.reply)
                return result
            # Any other input clears the pending state and falls through to LLM
            self._pending_organization = None

        # ── Layer 1d: Suggestion confirmation ─────────────────────────────────
        if self._pending_suggestion:
            if lowered in {"yes", "yes do it", "do it", "go ahead"}:
                replay = self._pending_suggestion
                self._pending_suggestion = None
                return self._handle_internal(replay)
            if lowered in {"no", "nope", "cancel", "not that"}:
                self._pending_suggestion = None
                self._suggestion_cooldown_turns = 2
                result = CommandResult("Understood. What would you like instead?", action="memory")
                self._remember("assistant", result.reply)
                return result
            self._pending_suggestion = None

        # ── Layer 1e: Pending message continuation ────────────────────────────
        if self._pending_message_contact:
            contact = self._pending_message_contact
            if lowered in {"cancel message", "cancel the message", "never mind"}:
                self._pending_message_contact = None
                result = CommandResult(f"Cancelled message for {contact}.", action="message")
                self._remember("assistant", result.reply)
                return result
            self._pending_message_contact = None
            return self._finalize_pending_message(contact, command)

        # ── Layer 1f: Explicit fact storage ───────────────────────────────────
        if self.rag.available and any(
            lowered.startswith(p) for p in ("remember that ", "my name is ", "my favorite ", "i like ", "i prefer ")
        ):
            fact = re.sub(r"^remember that ", "", lowered).strip()
            ok = self.rag.store_user_fact(fact)
            result = CommandResult(
                "Stored in long-term memory." if ok else "Could not write to memory right now.",
                action="memory",
            )
            self._remember("assistant", result.reply)
            return result

        # ── Layer 2: LLM-first intelligence ─────────────────────────────────────
        # Release the lock before entering the (potentially 30-second) LLM call
        # so the UI thread is not blocked from submitting new input or cancelling.
        self._handle_lock.release()
        try:
            reply_str = self._safe_agent_reply(command)
        finally:
            self._handle_lock.acquire()
        # Check sentinel added when tokens were already streamed to the UI
        if reply_str.endswith("\x00STREAMED"):
            reply_str = reply_str[:-9]  # strip sentinel
            result = CommandResult(reply_str, action="agent", metadata={"streamed_reply": "1"})
        else:
            result = CommandResult(reply_str, action="agent")
        self._remember("assistant", result.reply)
        return result

    def _safe_extract_entities(self, command: str) -> list[str]:
        try:
            return self.knowledge.extract_entities(command)
        except Exception:
            return []

    # ── ISSUE-7: RAG skip gate ────────────────────────────────────────────────

    # Minimum word count below which we skip the ChromaDB embedding call.
    # Greetings, confirmations, and single-word commands carry no semantic content.
    _RAG_MIN_WORDS = 4
    _RAG_INTENT_SIGNALS = frozenset({
        "remember", "recall", "what did", "who is", "tell me about",
        "what is", "how do", "explain", "find", "search", "note",
        "task", "project", "plan", "idea", "research", "summarize",
        "about me", "my name", "i like", "i prefer", "i am",
    })

    def _query_warrants_rag(self, lowered: str) -> bool:
        """Return True only when the query has enough semantic substance to benefit from RAG retrieval."""
        words = lowered.split()
        if len(words) < self._RAG_MIN_WORDS:
            return False
        # Allow short queries that contain explicit recall/knowledge signals
        if any(sig in lowered for sig in self._RAG_INTENT_SIGNALS):
            return True
        # For longer queries, always attempt RAG
        return len(words) >= 6

    # ── Layer 0a: Smalltalk fast-path ─────────────────────────────────────────
    # Core greeting tokens — any utterance composed ONLY of these (plus fillers)
    # is treated as smalltalk and never routed to the LLM.
    _SMALLTALK_CORE = frozenset({
        "hi", "hii", "hiii", "hey", "heyyy", "hello", "helo", "helo",
        "yo", "sup", "wassup", "whatsup", "howdy", "greetings",
        "good morning", "good afternoon", "good evening", "good night",
        "morning", "afternoon", "evening",
        "how are you", "how r u", "how are u", "hows it going", "how's it going",
        "how you doing", "how do you do", "what's up", "whats up",
        "nice to meet you", "pleased to meet you",
    })
    # Filler/suffix words that don't change the smalltalk nature of an utterance
    _SMALLTALK_FILLERS = frozenset({
        "edith", "there", "buddy", "bud", "mate", "pal", "friend", "bro",
        "dude", "darling", "dear", "love", "sir", "ma'am", "man",
        "again", "back", "there", "yo", "hey", "hi",
    })
    _SMALLTALK_REPLIES = [
        "Online. What are we doing?",
        "Here. Give me the objective.",
        "Listening. What's the play?",
        "Ready. One sentence — what do you need?",
        "Systems up. Your move.",
        "Standing by. What's first?",
    ]
    _smalltalk_reply_idx = 0

    def _smalltalk_reply(self, command: str) -> str | None:
        """
        Return an instant canned reply if *command* is pure smalltalk.
        Returns None if the command needs real processing.
        This runs in O(n) on the token count — zero LLM cost.
        """
        lowered = command.lower().strip()
        lowered = re.sub(r"\bu\b", "you", lowered)
        lowered = re.sub(r"\bur\b", "your", lowered)
        # Exact phrases (gratitude / capability) — JARVIS-adjacent tone
        normalized = re.sub(r"[^a-z0-9\s]", " ", lowered)
        normalized = " ".join(normalized.split())
        phrase_replies = {
            "thanks": "Anytime. What's next?",
            "thank you": "Always. Need anything else off your plate?",
            "ty": "You got it.",
            "thx": "You got it.",
            "what else can you do": "Apps, files, media, system, WhatsApp, tasks, research, and cowork flows. Pick one.",
            "who are you": "EDITH — your local copilot. I run this machine with you, not at you.",
            "who are u": "EDITH — your local copilot. I run this machine with you, not at you.",
            "can you play anything interesting for me": "Cinematic mix on YouTube, or deep focus on Spotify — say which.",
            "what are you doing": "Watching the board and waiting on your cue.",
            "im bored": "Let's fix that. Want music, a quick challenge, or should I automate something useful?",
            "i am bored": "Let's fix that. Want music, a quick challenge, or should I automate something useful?",
            "lets talk": "I'm here. Talk to me — what's on your mind?",
        }
        if normalized in phrase_replies:
            return phrase_replies[normalized]

        tokens = set(lowered.split())
        content_tokens = tokens - self._SMALLTALK_FILLERS
        # Check full phrase matches first
        for phrase in self._SMALLTALK_CORE:
            if lowered == phrase or lowered.startswith(phrase + " ") or lowered.endswith(" " + phrase):
                # Make sure none of the remaining tokens look like a real command
                remaining = lowered.replace(phrase, "").strip().split()
                non_filler = [t for t in remaining if t not in self._SMALLTALK_FILLERS]
                if not non_filler:
                    reply = self._SMALLTALK_REPLIES[
                        EdithAssistant._smalltalk_reply_idx % len(self._SMALLTALK_REPLIES)
                    ]
                    EdithAssistant._smalltalk_reply_idx += 1
                    return reply
        # Token-set fallback: if ALL tokens are core/filler words, it's smalltalk
        if content_tokens and content_tokens.issubset(self._SMALLTALK_CORE | self._SMALLTALK_FILLERS):
            reply = self._SMALLTALK_REPLIES[
                EdithAssistant._smalltalk_reply_idx % len(self._SMALLTALK_REPLIES)
            ]
            EdithAssistant._smalltalk_reply_idx += 1
            return reply
        return None

    def _is_message_contact_only_command(self, lowered: str) -> str | None:
        """
        Detect 'message <name>' or 'text <name>' commands that have no content yet.
        Returns the contact name string if matched, None otherwise.
        This triggers Layer 1e (pending message continuation) without hitting the LLM.
        """
        for prefix in ("message ", "text ", "whatsapp ", "msg "):
            if lowered.startswith(prefix):
                remainder = lowered[len(prefix):].strip()
                # Reject if it looks like a full send command (has 'saying', 'that', quotes)
                full_send_signals = ("saying ", "that ", "tell ", " saying", " that")
                if any(s in remainder for s in full_send_signals):
                    return None
                # Reject URL-like or very short (1 char) remainders
                if len(remainder) < 2 or "." in remainder:
                    return None
                # Check against known contacts
                known = {k.lower() for k in self._config.whatsapp_display_names}
                known.update({k.lower() for k in self._config.contacts})
                # Fuzzy: check if any known contact name is contained in remainder
                for contact in known:
                    if contact in remainder or remainder in contact:
                        return contact
                # Unknown contact — still treat as contact-only command
                # The WhatsApp service will handle resolution
                return remainder
        return None


    def _capture_and_describe_screen(self) -> str:
        try:
            from PIL import ImageGrab
            import tempfile
            import os
            fd, path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            img = ImageGrab.grab()
            img.save(path)
            prompt = "What is currently visible on the user's screen? Be concise but detailed about any code, text, or applications."
            description = self.vision.describe_image(Path(path), prompt=prompt)
            try:
                os.remove(path)
            except Exception:
                pass
            return description
        except ImportError:
            self.logger.warning("Pillow not installed. Cannot grab screen.")
            return ""
        except Exception as e:
            self.logger.warning(f"Screen capture failed: {e}")
            return ""

    def _safe_agent_reply(self, command: str) -> str:
        """Stream LLM tokens to the UI and TTS engine simultaneously."""
        try:
            lowered = command.lower().strip()
            word_count = len(lowered.split())
            prefer_fast = word_count <= 7

            vision_context = ""
            vision_triggers = ["screen", "look at", "see this", "what am i looking at"]
            if any(trig in lowered for trig in vision_triggers) and self.vision.enabled:
                self.logger.info("Live Screen Vision triggered.")
                desc = self._capture_and_describe_screen()
                if desc:
                    vision_context = f"[Live Screen Context: {desc}]\n\n"

            speech_buffer: list[str] = []
            audio_active = self.audio.tts_enabled
            self._voice_state_sent = False
            _token_emitted = False  # track if we actually streamed anything to UI

            if audio_active:
                self.audio.clear_queue()

            def _on_token(token: str) -> None:
                nonlocal _token_emitted
                _token_emitted = True
                # Push token to UI
                if self._stream_callback:
                    self._stream_callback(token)
                
                # Update UI state to speaking on first token if TTS is enabled
                if getattr(self, "_voice_state_sent", False) is False and audio_active:
                    if hasattr(self, "_ui_callback") and self._ui_callback:
                        self._ui_callback("voice_state", "speaking")
                    self._voice_state_sent = True

                # Stream TTS in small clauses (ultra-latency) instead of waiting for full sentences.
                if audio_active:
                    speech_buffer.append(token)
                    text_so_far = "".join(speech_buffer)
                    min_chars = max(8, int(getattr(self.config, "tts_chunk_min_chars", 14)))
                    clause_end = (
                        text_so_far.endswith((". ", "? ", "! ", ".\n", "?\n", "!\n", ", ", "; ", ": "))
                        or (len(text_so_far.strip()) >= min_chars and text_so_far.rstrip().endswith((" ", "\n")))
                    )
                    if clause_end:
                        sentence = text_so_far.strip()
                        if sentence:
                            self.audio.speak_queued(sentence)
                        speech_buffer.clear()

            context_kwargs = self._build_dynamic_context()
            specialist_instruction = (
                "You are EDITH in live conversation: J.A.R.V.I.S. precision, Friday's warmth and dry wit. "
                "Short complete sentences for voice. Infer intent; be decisive; one line of empathy if they're strained."
            )

            # Construct pending context
            pending_parts = []
            if self._pending_organization:
                target, by_context = self._pending_organization
                pending_parts.append(f"User is deciding whether to organize {target} (by_context={by_context}).")
            if self._pending_whatsapp_draft:
                contact, draft = self._pending_whatsapp_draft
                pending_parts.append(f"User has a pending WhatsApp draft for {contact}: '{draft}'.")
            if self._pending_whatsapp_call:
                contact, video = self._pending_whatsapp_call
                call_type = "video" if video else "voice"
                pending_parts.append(f"User has a pending WhatsApp {call_type} call for {contact}.")
            if self._pending_browser_purchase:
                pending_parts.append("User is in a browser purchase checkout flow.")
            if self._pending_suggestion:
                pending_parts.append(f"I just suggested they might want to '{self._pending_suggestion}'.")
            if self._pending_message_contact:
                pending_parts.append(f"Waiting for message content to send to {self._pending_message_contact}.")
            
            pending_context = " ".join(pending_parts)
            
            # Construct RAG context — with caching to avoid repeat embedding calls
            rag_facts = []
            voice_turn = bool(self._voice_session_active)
            skip_rag_voice = voice_turn and getattr(self.config, "skip_rag_on_voice", True)
            if self.rag.available and not skip_rag_voice and self._query_warrants_rag(lowered):
                try:
                    cache_key = lowered[:80]
                    if cache_key in self._rag_cache:
                        rag_context = self._rag_cache[cache_key]
                    else:
                        memory_hits = self.rag.get_user_memory(command, limit=3)
                        for hit in memory_hits:
                            rag_facts.append(hit.text if hasattr(hit, "text") else str(hit))
                        rag_context = "\n".join(rag_facts) if rag_facts else ""
                        # Store in cache; evict oldest if full
                        if len(self._rag_cache) >= self._rag_cache_max:
                            self._rag_cache.pop(next(iter(self._rag_cache)))
                        self._rag_cache[cache_key] = rag_context
                except Exception as exc:
                    self.logger.debug("Failed to fetch rag memory: %s", exc)
                    rag_context = ""
            else:
                rag_context = ""

            # JARVIS Neural Brain Integration
            # Instead of a basic LLM generation, we give the prompt to the autonomous tool loop.
            reply = self.neural_router.process(
                user_prompt=command,
                vision_context=vision_context,
                on_token=_on_token,
                history=list(self._short_term_context),
                pending_context=pending_context,
                rag_context=rag_context,
                voice_fast=voice_turn and getattr(self.config, "ultra_latency", True),
            )

            # Flush any remaining partial sentence
            if audio_active and speech_buffer:
                tail = "".join(speech_buffer).strip()
                if tail:
                    self.audio.speak_queued(tail)

            sanitized = self._sanitize_model_output(reply)
            # If tokens were streamed to the UI, mark it so _handle_result
            # does NOT call _append_log a second time (prevents double message).
            if _token_emitted:
                return sanitized + "\x00STREAMED"
            return sanitized
        except Exception:
            self.logger.exception("safe agent reply failed")
            return "I hit a temporary model issue, but I am still here. Please try that once more."

    def _try_model_tool_intent(self, command: str) -> CommandResult | None:
        model_ready, _ = self.agent.runtime_status()
        if not model_ready:
            return None
        prompt = (
            "Map the user request to one assistant action.\n"
            "Return only JSON in this schema:\n"
            '{"action":"...", "target":"", "query":"", "value":0, "by_context":false, "confidence":0.0}\n'
            "Allowed actions: open_target, web_search, youtube_play, spotify_play, find_file, "
            "analyze_folder, organize_folder, set_volume, set_brightness, wifi_on, wifi_off, "
            "bluetooth_on, bluetooth_off, focus_mode, cowork_mode, none.\n"
            "Confidence should be between 0.0 and 1.0.\n"
            f"User request: {command}"
        )
        raw = self.agent.parse_intent(prompt, self._context_history(), prefer_fast=True)
        parsed = self._extract_json_object(raw)
        if parsed is None:
            return None
        action = str(parsed.get("action", "")).strip().lower()
        target = str(parsed.get("target", "")).strip()
        query = str(parsed.get("query", "")).strip()
        by_context = bool(parsed.get("by_context", False))
        value = parsed.get("value", None)
        confidence = parsed.get("confidence", 0.0)
        try:
            confidence_value = float(confidence)
        except Exception:
            confidence_value = 0.0
        if confidence_value < 0.55:
            return None

        try:
            if action == "open_target" and target:
                return CommandResult(self.system.open_target(target), action="system")
            if action == "web_search":
                q = query or target
                if q:
                    return CommandResult(self._online_or_local(self.system.search_web(q), "search the web"), action="browser")
            if action == "youtube_play":
                q = query or target
                if q:
                    return CommandResult(self.media.search_youtube(q), action="youtube")
            if action == "spotify_play":
                q = query or target
                if q:
                    return CommandResult(self.media.play_spotify(q), action="spotify")
            if action == "find_file":
                q = query or target
                if q:
                    return CommandResult(self._search_files(q), action="files")
            if action == "analyze_folder":
                t = target or "desktop"
                if by_context:
                    return CommandResult(self.system.analyze_folder_context(t), action="files")
                return CommandResult(self.system.folder_clutter_report(t), action="files")
            if action == "organize_folder":
                t = target or "desktop"
                return CommandResult(self._queue_organization(t, by_context=by_context), action="files")
            if action == "set_volume" and value is not None:
                return CommandResult(self.audio.set_volume(int(value)), action="audio")
            if action == "set_brightness" and value is not None:
                return CommandResult(self.system.set_brightness(int(value)), action="system")
            if action == "wifi_on":
                return CommandResult(self.system.wifi(True), action="system")
            if action == "wifi_off":
                return CommandResult(self.system.wifi(False), action="system")
            if action == "bluetooth_on":
                return CommandResult(self.system.bluetooth(True), action="system")
            if action == "bluetooth_off":
                return CommandResult(self.system.bluetooth(False), action="system")
            if action == "focus_mode":
                return CommandResult(self._run_focus_mode(), action="routine")
            if action == "cowork_mode":
                return CommandResult("Cowork mode is ready. Say: cowork on <goal> to begin.", action="cowork")
        except Exception:
            self.logger.exception("model intent execution failed for action=%s", action)
            return None
        return None

    def _extract_json_object(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        cleaned = text.strip()
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        snippet = cleaned[start : end + 1]
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    def _sanitize_model_output(self, text: str) -> str:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return text
        cleaned = re.sub(r"^(user|assistant|system)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(user|assistant|system)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "").strip()
        return cleaned

    def _is_very_short_ambiguous(self, lowered: str) -> bool:
        if not lowered:
            return False
        if any(ch.isdigit() for ch in lowered):
            return False
        if len(lowered.split()) > 2:
            return False
        known_prefixes = (
            "open ",
            "play ",
            "set ",
            "turn ",
            "run ",
            "export ",
            "search ",
            "find ",
            "send ",
            "message ",
            "call ",
            "wifi",
            "bluetooth",
            "preflight",
            "debug",
            "self improve",
            "undo",
            "revert",
            "cancel",
            "resume",
            "organize",
            "organise",
            "analyze",
        )
        if lowered.startswith(known_prefixes):
            return False
        whitelist = {"hi", "hii", "hiii", "hay", "hey", "hello", "thanks", "thank you", "youtube", "spotify", "google"}
        if lowered in whitelist:
            return False
        return True

    def _should_try_model_intent(self, lowered: str) -> bool:
        words = lowered.split()
        if len(words) < 3:
            return False
        if len(words) > 30:
            return False
        guidance_tokens = {
            "open",
            "play",
            "search",
            "find",
            "organize",
            "analyse",
            "analyze",
            "check",
            "set",
            "turn",
            "please",
            "could",
            "can",
            "help",
            "whatsapp",
            "message",
            "text",
            "call",
        }
        return any(token in guidance_tokens for token in words)

    def _should_try_model_intent_first(self, lowered: str) -> bool:
        if not lowered:
            return False
        if self._is_pending_tasks_query(lowered):
            return False
        words = lowered.split()
        if len(words) < 3:
            return False
        if len(words) > 30:
            return False
        direct_prefixes = (
            "show tasks",
            "task list",
            "next task",
            "complete task",
            "clear done tasks",
            "run preflight",
            "export debug bundle",
            "self improve",
            "set volume",
            "set brightness",
            "focus mode",
            "cowork mode",
            "analyze desktop",
            "analyze downloads",
            "organize desktop",
            "organize downloads",
            "open youtube",
            "open spotify",
            "open google",
            "open stack",
            "open whatsapp",
            "whatsapp ",
            "whatsapp read",
            "read chat",
            "open settings",
            "wifi ",
            "bluetooth ",
            "message ",
            "send message to",
            "call ",
        )
        if lowered.startswith(direct_prefixes):
            return False
        natural_markers = {
            "could",
            "can",
            "please",
            "help",
            "find",
            "search",
            "open",
            "play",
            "organize",
            "analyse",
            "analyze",
            "set",
            "turn",
            "show",
            "tell",
        }
        return any(token in natural_markers for token in words)

    def _try_handle_compound_command(self, command: str) -> str | None:
        lowered = command.lower().strip()
        if len(lowered) < 12:
            return None
        if " and " not in lowered and " then " not in lowered:
            return None
        action_markers = ("open ", "search ", "search for ", "play ", "go to ")
        if sum(1 for marker in action_markers if marker in lowered) < 2:
            return None

        parts = re.split(r"\s+(?:and then|then|and)\s+", command, flags=re.IGNORECASE)
        parts = [part.strip(" ,.") for part in parts if part.strip(" ,.")]
        if len(parts) < 2:
            return None

        context: dict[str, Any] = {"site": None}
        replies: list[str] = []
        handled_steps = 0
        for part in parts[:5]:
            step_reply = self._execute_compound_step(part, context)
            if step_reply is None:
                continue
            handled_steps += 1
            replies.append(step_reply)
        if handled_steps < 2:
            return None
        return " ".join(replies)

    def _execute_compound_step(self, step: str, context: dict[str, Any]) -> str | None:
        lowered = step.lower().strip()
        if lowered.startswith("open "):
            target = step[5:].strip()
            if not target:
                return None
            context["site"] = self._infer_site(target)
            return self.system.open_target(target)
        if lowered.startswith("go to "):
            target = step[6:].strip()
            if not target:
                return None
            context["site"] = self._infer_site(target)
            return self.system.open_target(target)
        if lowered.startswith("play "):
            query = re.sub(r"^play\s+", "", step, flags=re.IGNORECASE).strip()
            if "on youtube" in lowered:
                context["site"] = "youtube"
                query = re.sub(r"\s+on youtube$", "", query, flags=re.IGNORECASE).strip()
                return self.media.search_youtube(query or "music")
            if "on spotify" in lowered:
                context["site"] = "spotify"
                query = re.sub(r"\s+on spotify$", "", query, flags=re.IGNORECASE).strip()
                return self.media.play_spotify(query or "music")
            active = context.get("site")
            if active == "youtube":
                return self.media.search_youtube(query or "music")
            if active == "spotify":
                return self.media.play_spotify(query or "music")
            return self.media.search_youtube(query or "music")
        if lowered.startswith("search for ") or lowered.startswith("search "):
            query = re.sub(r"^search(?:\s+for)?\s+", "", step, flags=re.IGNORECASE).strip()
            if not query:
                return None
            active = context.get("site")
            if "youtube" in lowered or active == "youtube":
                context["site"] = "youtube"
                return self.media.search_youtube(query)
            if "spotify" in lowered or active == "spotify":
                context["site"] = "spotify"
                return self.media.search_spotify(query)
            if "amazon" in lowered or active == "amazon":
                context["site"] = "amazon"
                encoded = urllib.parse.quote_plus(query)
                webbrowser.open(f"https://www.amazon.in/s?k={encoded}")
                return f"Searching Amazon for {query}."
            return self._search_files_or_web(query)
        return None

    def _try_handle_in_app_action(self, command: str) -> str | None:
        lowered = command.lower().strip()
        if not lowered:
            return None
        if not (
            lowered.startswith(("open ", "start ", "join ", "schedule ", "mute", "unmute", "end ", "leave ", "raise "))
            or " in teams" in lowered
            or " in zoom" in lowered
            or "new meeting" in lowered
            or "start meeting" in lowered
        ):
            return None
        if not self.app_control.can_handle(command):
            return None
        reply = self.app_control.execute(command)
        if not reply:
            return None
        # Allow normal routing to continue when the app-action parser couldn't map a shortcut.
        if reply.lower().startswith("i know ") and "don't have a shortcut" in reply.lower():
            return None
        return reply

    def _try_handle_dynamic_desktop_task(self, command: str) -> str | None:
        if not self.desktop_automation.can_handle(command):
            return None
        try:
            reply = self.desktop_automation.execute(
                command,
                parse_with_model=self._parse_dynamic_desktop_task_with_model,
            )
            return reply or None
        except Exception:
            self.logger.exception("dynamic desktop task failed")
            return None

    def _parse_dynamic_desktop_task_with_model(self, command: str) -> dict[str, Any] | None:
        model_ready, _ = self.agent.runtime_status()
        if not model_ready:
            return None
        prompt = (
            "Extract desktop file automation intent as JSON only.\n"
            "Schema:\n"
            '{"app":"","filename":"","extension":"","content":"","target_dir":"","use_gui":true,"confidence":0.0}\n'
            "Rules:\n"
            "- app: app name if user requested one (notepad, wps, file explorer, vscode).\n"
            "- filename: base file name without extension when possible.\n"
            "- extension: preferred extension (e.g. .txt, .py, .md).\n"
            "- content: exact text user asked to type/write.\n"
            "- target_dir: desktop/downloads/documents or explicit path.\n"
            "- confidence: 0.0 to 1.0.\n"
            f"User request: {command}"
        )
        raw = self.agent.parse_intent(prompt, self._context_history(), prefer_fast=True)
        parsed = self._extract_json_object(raw)
        if parsed is None:
            return None
        return parsed

    def _try_handle_browser_control_task(self, command: str) -> str | None:
        if not self.browser_control.can_handle(command):
            return None
        try:
            reply, purchase_plan = self.browser_control.execute(command)
        except Exception:
            self.logger.exception("browser control task failed")
            return None
        if purchase_plan is not None:
            self._pending_browser_purchase = purchase_plan
            self._pending_browser_summary_approved = False
        return reply or None

    def _infer_site(self, target: str) -> str | None:
        lowered = target.lower().strip()
        if "youtube" in lowered:
            return "youtube"
        if "spotify" in lowered:
            return "spotify"
        if "amazon" in lowered:
            return "amazon"
        if lowered in {"chrome", "google chrome"}:
            return "browser"
        return None

    def _remember(self, source: str, text: str) -> None:
        self.history.append(ChatMessage(source=source, text=text))

    def _capabilities(self) -> str:
        return (
            "I can act as a multi-model local open-source desktop assistant with Ollama, work fully locally for chat, "
            "voice control, memory, notes, files, and system actions, brainstorm ideas, build plans, think through "
            "problems with you, launch YouTube and Spotify automations, open common Windows tools, search files and "
            "folders, organize desktops and folders, move files into place, control Wi-Fi and brightness, check for "
            "updates, search Google, summarize Wikipedia, adjust system volume, analyze the workspace like a coding "
            "teammate, inspect files, run compile checks, keep session-level coworker memory, and run a safe "
            "self-improvement cycle that tunes runtime reliability without retraining models."
        )

    def _strip_words(self, text: str, words: list[str]) -> str:
        cleaned = text
        for word in words:
            cleaned = cleaned.replace(word, "")
        return cleaned.strip()

    def _google(self, query: str) -> str:
        if not query:
            webbrowser.open("https://www.google.com/")
            return "Opening Google."
        encoded = urllib.parse.quote_plus(query)
        webbrowser.open(f"https://www.google.com/search?q={encoded}")
        return f"Searching Google for {query}."

    def _online_or_local(self, online_reply: str, capability: str) -> str:
        if self.connectivity.is_online():
            return online_reply
        return (
            f"Internet is offline, so I can't {capability} right now. "
            "I can still help with local apps, files, notes, memory, and offline chat."
        )

    def _summarize_topic(self, topic: str) -> str:
        if not self.connectivity.is_online():
            return (
                f"Internet is offline, so I can't reach Wikipedia for {topic} right now. "
                "I can still search your local files or notes if you want."
            )
        return self.knowledge.summarize_topic(topic)

    def _resume_cowork_summary(self) -> str:
        items = self.session_memory.recent(limit=3)
        if not items:
            return "We do not have a coworker session yet. Say something like: cowork on improving startup performance."
        lines = []
        for item in items:
            lines.append(f"- {item.goal}: {item.summary}")
        queue_summary = self.task_queue.summary()
        return "Recent cowork context:\n" + "\n".join(lines) + "\n\n" + queue_summary

    def _extract_note(self, command: str) -> str:
        note = command
        for pattern in [r"^save note\s*", r"^take note\s*", r"^note this\s*"]:
            note = re.sub(pattern, "", note, flags=re.IGNORECASE)
        return note.strip() or "Empty note requested."

    def _contact_status(self, name: str) -> str:
        if not name:
            return "Tell me who the message is for."
        number = self.config.contacts.get(name.lower())
        if not number:
            return f"I don't know a saved contact called {name}."
        if phonenumbers is None:
            return f"Contact {name} is saved, but phonenumbers is not installed yet."
        parsed = phonenumbers.parse(number, "IN")
        formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        return f"Contact {name} is ready at {formatted}."

    def _send_whatsapp_message(self, command: str) -> str:
        contact_pattern = self._contact_name_pattern()
        match = re.match(
            rf"(?:send message to|message|text)\s+(.+?)\s+(?:saying|that|telling them)\s+(.+)",
            command,
            flags=re.IGNORECASE,
        )
        if not match and contact_pattern:
            match = re.match(
                rf"({contact_pattern})\s+(?:saying|that|telling them)\s+(.+)",
                command,
                flags=re.IGNORECASE,
            )
        if not match:
            return "Say it like: message primary_contact saying I am on the way."
        name = match.group(1).strip()
        message = match.group(2).strip()
        if not name or not message:
            return "I need both a contact name and a message."

        resolved_name = self._resolve_whatsapp_name(name)
        if self._looks_incomplete_message(message):
            self._pending_message_contact = resolved_name
            return f"I caught {resolved_name}. Continue your message and I'll send it."
        return self.whatsapp.send_message(resolved_name, message)

    def _start_whatsapp_call(self, command: str, video: bool) -> str:
        patterns = [
            r"(?:call|voice call|ring)\s+(.+?)\s+(?:on whatsapp|in whatsapp|through whatsapp)$",
            r"(?:call|voice call|ring)\s+(.+)$",
            r"(?:video call)\s+(.+?)\s+(?:on whatsapp|in whatsapp|through whatsapp)$",
            r"(?:video call)\s+(.+)$",
        ]
        name = ""
        for pattern in patterns:
            match = re.match(pattern, command, flags=re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                break
        if not name:
            return "Tell me who to call on WhatsApp."
        resolved_name = self._resolve_whatsapp_name(name)
        if video:
            return self.whatsapp.video_call(resolved_name)
        return self.whatsapp.voice_call(resolved_name)

    def _start_pending_message(self, command: str) -> str:
        match = re.match(r"(?:send message to|message|text)\s+(.+)", command, flags=re.IGNORECASE)
        if not match:
            return "Tell me who the message is for."
        name = match.group(1).strip()
        resolved_name = self._resolve_whatsapp_name(name)
        self._pending_message_contact = resolved_name
        return f"What should I send to {resolved_name}?"

    def _finalize_pending_message(self, contact: str, message: str) -> CommandResult:
        cleaned = message.strip()
        if not cleaned:
            return CommandResult(f"I didn't catch the message for {contact}.", action="message")
        reply = self.whatsapp.send_message(contact, cleaned)
        return CommandResult(reply, action="message")

    def _resolve_contact_name(self, spoken_name: str) -> str | None:
        lowered = spoken_name.lower().strip()
        for saved_name in self.config.contacts:
            if saved_name.lower() == lowered:
                return saved_name
        return None

    def _resolve_whatsapp_name(self, spoken_name: str) -> str:
        lowered = spoken_name.lower().strip()
        configured = self.config.whatsapp_display_names.get(lowered)
        if configured:
            return configured
        resolved_contact = self._resolve_contact_name(spoken_name)
        if resolved_contact is not None:
            configured = self.config.whatsapp_display_names.get(resolved_contact.lower())
            if configured:
                return configured
            return resolved_contact
        return spoken_name.strip()

    def _contact_name_pattern(self) -> str:
        names = sorted(self.config.contacts.keys(), key=len, reverse=True)
        return "|".join(re.escape(name) for name in names)

    def _search_files(self, query: str) -> str:
        matches = self.system.search_files(query)
        if not matches:
            return f"I couldn't find files or folders matching {query}."
        formatted = "\n".join(matches[:8])
        return f"I found these matches for {query}:\n{formatted}"

    def _search_files_in_folder(self, query: str, folder: str) -> str:
        matches = self.system.search_within_folder(query, folder, limit=8)
        if not matches:
            return f"I couldn't find {query} inside {folder}."
        formatted = "\n".join(matches[:8])
        return f"I found these matches for {query} inside {folder}:\n{formatted}"

    def _search_files_or_web(self, query: str) -> str:
        matches = self.system.search_files(query)
        if matches:
            formatted = "\n".join(matches[:6])
            return f"I found these local matches for {query}:\n{formatted}"
        return self.system.search_web(query)

    def _contextualize_prompt(self, command: str) -> str:
        relevant = self.memory.relevant(command, limit=3)
        if not relevant:
            return command
        memory_lines = [
            f"- Earlier request: {item.command} | Edith replied: {item.reply}"
            for item in relevant
        ]
        return (
            "Use this remembered context if it helps, but do not override the user's current intent.\n"
            "Remembered context:\n"
            + "\n".join(memory_lines)
            + f"\nCurrent user request: {command}"
        )

    def _context_history(self) -> list[ChatMessage]:
        history = list(self.history[-10:])
        # Use per-turn cache to avoid repeated JSONL reads within the same handle() turn
        if self._turn_memory_cache is None:
            self._turn_memory_cache = self.memory.recent(limit=4, include_actions={"agent", "brainstorm", "plan", "think", "quick", "note"})
        remembered_messages: list[ChatMessage] = []
        for item in self._turn_memory_cache:
            remembered_messages.append(ChatMessage(source="assistant", text=f"Remembered user request: {item.command}"))
            remembered_messages.append(ChatMessage(source="assistant", text=f"Remembered reply: {item.reply}"))
        return (remembered_messages + history)[-14:]

    def _build_dynamic_context(self) -> dict[str, str]:
        """Build a runtime context dict injected into every LLM call."""
        # Use per-turn cache to avoid repeated JSONL reads within the same handle() turn
        if self._turn_memory_cache is None:
            self._turn_memory_cache = self.memory.recent(limit=3)
        memory_lines = [f"- {item.command}: {item.reply}" for item in self._turn_memory_cache]
        memory_context = "\n".join(memory_lines) if memory_lines else "No recent long-term memories."
        last_topic = "None"
        if self.history:
            last_topic = self.history[-1].text[:60]
        last_action = "None"
        if len(self.history) >= 2:
            last_action = self.history[-2].text[:60]
        current_task = "None"
        pending = self.task_queue.next_task()
        if pending:
            current_task = pending.title
        return {
            "recent_memory": memory_context,
            "last_topic": last_topic,
            "last_action": last_action,
            "current_task": current_task,
            "recent_turns": self._short_term_context_block(),
        }

    def _queue_organization(self, target: str, by_context: bool) -> str:
        preview = self.system.preview_organization(target, by_context=by_context)
        self._pending_organization = (target, by_context)
        mode = "context" if by_context else "file-type"
        return (
            f"{preview}\n\n"
            f"Preview ready ({mode}). Say 'yes' to apply this organization, or 'no' to cancel."
        )

    def preflight_report(self) -> str:
        model_ready, model_status = self.agent.runtime_status()
        voice_ready = self.voice.enabled
        audio_ready = self.audio.system_audio_enabled
        online = self.connectivity.is_online()
        return (
            "Preflight status:\n"
            f"- Model runtime: {'READY' if model_ready else 'DEGRADED'} ({model_status})\n"
            f"- Voice recognition: {'READY' if voice_ready else 'UNAVAILABLE'}\n"
            f"- System audio control: {'READY' if audio_ready else 'LIMITED'}\n"
            f"- Internet: {'ONLINE' if online else 'OFFLINE'}\n"
            f"- Command timeout: {self.config.command_timeout_seconds}s"
        )

    def export_debug_bundle(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = Path(self.config.data_dir)
        bundle_dir = root / "debug"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = bundle_dir / f"edith_debug_{timestamp}.zip"

        snapshot = {
            "timestamp": timestamp,
            "model_status": self.agent.runtime_status()[1],
            "voice_enabled": self.voice.enabled,
            "audio_enabled": self.audio.system_audio_enabled,
            "online": self.connectivity.is_online(),
            "models": {
                "main": self.config.ollama_model,
                "planner": self.config.planner_model,
                "creative": self.config.creative_model,
                "fast": self.config.fast_model,
            },
            "recent_history": [
                {"source": item.source, "text": item.text, "timestamp": item.timestamp.isoformat()}
                for item in self.history[-20:]
            ],
        }

        snapshot_path = root / f"debug_snapshot_{timestamp}.json"
        snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

        include_paths = [
            snapshot_path,
            Path(self.config.memory_path),
            Path(self.config.session_memory_path),
            Path(self.config.notes_path),
            Path(self.config.telemetry_path),
        ]
        try:
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                for path in include_paths:
                    if path.exists() and path.is_file():
                        zipf.write(path, arcname=path.name)
            return f"Debug bundle exported to {bundle_path}."
        except Exception as exc:
            return f"I couldn't export the debug bundle: {exc}"
        finally:
            try:
                if snapshot_path.exists():
                    snapshot_path.unlink()
            except Exception:
                pass

    def _handle_bluetooth_command(self, lowered: str) -> str:
        if lowered in {"bluetooth off", "turn off bluetooth", "disable bluetooth"}:
            return self.system.bluetooth(False)
        if lowered in {"bluetooth on", "turn on bluetooth", "enable bluetooth"}:
            return self.system.bluetooth(True)
        return self.system.bluetooth_settings()

    def _extract_number(self, text: str, default: int = 50) -> int:
        numbers = re.findall(r"\d+", text)
        if not numbers:
            return default
        return int(numbers[0])

    def _is_volume_up_command(self, text: str) -> bool:
        phrases = (
            "increase volume",
            "turn up the volume",
            "turn the volume up",
            "volume up",
            "raise the volume",
            "make it louder",
            "make the sound louder",
            "boost the volume",
        )
        return any(phrase in text for phrase in phrases)

    def _is_volume_down_command(self, text: str) -> bool:
        phrases = (
            "decrease volume",
            "turn down the volume",
            "turn the volume down",
            "volume down",
            "lower the volume",
            "make it quieter",
            "make the sound quieter",
            "reduce the volume",
        )
        return any(phrase in text for phrase in phrases)

    def _is_set_volume_command(self, text: str) -> bool:
        phrases = (
            "set volume to",
            "volume to",
            "make the volume",
            "change the volume to",
        )
        return any(phrase in text for phrase in phrases) and any(char.isdigit() for char in text)

    def _is_brightness_command(self, text: str) -> bool:
        phrases = (
            "set brightness",
            "brightness to",
            "make the screen brighter",
            "make screen brighter",
            "increase brightness",
            "raise brightness",
            "make the screen dimmer",
            "make screen dimmer",
            "decrease brightness",
            "lower brightness",
            "turn brightness up",
            "turn brightness down",
        )
        return any(phrase in text for phrase in phrases)

    def _is_open_item_in_folder_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        return lowered.startswith("open ") and " in " in lowered and not lowered.startswith("open folder ")

    def _parse_open_item_in_folder(self, text: str) -> tuple[str, str]:
        cleaned = re.sub(r"^open\s+", "", text, flags=re.IGNORECASE).strip()
        item_name, folder_name = re.split(r"\s+in\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
        return item_name.strip(), folder_name.strip()

    def _is_find_item_in_folder_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        return lowered.startswith("find ") and " in " in lowered and " on my system" not in lowered and " in my system" not in lowered

    def _parse_find_item_in_folder(self, text: str) -> tuple[str, str]:
        cleaned = re.sub(r"^find\s+", "", text, flags=re.IGNORECASE).strip()
        item_name, folder_name = re.split(r"\s+in\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
        return item_name.strip(), folder_name.strip()

    def _is_move_item_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        return lowered.startswith("move ") and " to " in lowered

    def _parse_move_item_command(self, text: str) -> tuple[str, str]:
        cleaned = re.sub(r"^move\s+", "", text, flags=re.IGNORECASE).strip()
        item_name, folder_name = re.split(r"\s+to\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
        return item_name.strip(), folder_name.strip()

    def _is_analyze_target_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        if lowered.startswith(("analyze workspace", "analyze this project", "analyze desktop", "analyze downloads")):
            return False
        return lowered.startswith("analyze ") and ("folder " in lowered or "\\" in text or ":/" in lowered or ":\\\\" in lowered or lowered.endswith(("desktop", "downloads", "documents", "pictures", "music", "videos")))

    def _parse_analyze_target_command(self, text: str) -> tuple[str, bool]:
        cleaned = re.sub(r"^analyze\s+", "", text, flags=re.IGNORECASE).strip()
        by_context = False
        cleaned = re.sub(r"^folder\s+", "", cleaned, flags=re.IGNORECASE).strip()
        if re.search(r"\s+by context$", cleaned, flags=re.IGNORECASE):
            by_context = True
            cleaned = re.sub(r"\s+by context$", "", cleaned, flags=re.IGNORECASE).strip()
        elif re.search(r"\s+context$", cleaned, flags=re.IGNORECASE):
            by_context = True
            cleaned = re.sub(r"\s+context$", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned, by_context

    def _is_organize_target_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        if lowered.startswith(("organize desktop", "organize downloads", "organize folder ", "organize folder by context ", "smart organize folder ", "preview organize ")):
            return False
        return lowered.startswith(("organize ", "smart organize ", "clean ", "declutter ")) and ("\\" in text or ":/" in lowered or ":\\\\" in lowered or any(lowered.endswith(name) for name in ("desktop", "downloads", "documents", "pictures", "music", "videos")))

    def _is_preview_organize_target_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        if lowered.startswith(("preview organize desktop", "preview organize downloads", "preview organize folder ", "preview desktop")):
            return False
        return lowered.startswith("preview organize ") and ("\\" in text or ":/" in lowered or ":\\\\" in lowered or any(lowered.endswith(name) for name in ("desktop", "downloads", "documents", "pictures", "music", "videos")))

    def _parse_organize_target_command(self, text: str, prefix: str | None = None) -> tuple[str, bool]:
        cleaned = text.strip()
        if prefix == "preview":
            cleaned = re.sub(r"^preview\s+organize\s+", "", cleaned, flags=re.IGNORECASE).strip()
        else:
            cleaned = re.sub(r"^(?:smart\s+organize|organize|clean|declutter)\s+", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^folder\s+", "", cleaned, flags=re.IGNORECASE).strip()
        by_context = False
        if re.search(r"\s+by context$", cleaned, flags=re.IGNORECASE):
            by_context = True
            cleaned = re.sub(r"\s+by context$", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned, by_context

    def _should_store(self, action: str) -> bool:
        return action not in {"system", "updates", "audio", "clock", "status", "files", "cowork"}

    def _should_store_interaction(self, command: str, result: CommandResult) -> bool:
        lowered = command.lower().strip()
        reply = result.reply.lower().strip()

        if not self._should_store(result.action):
            return False
        if len(lowered) < 8:
            return False
        if self._looks_incomplete(lowered) or self._looks_incomplete_message(lowered):
            return False
        if result.action in {"memory", "help"}:
            return False

        failure_markers = (
            "i couldn't",
            "i could not",
            "i can't",
            "i cannot",
            "unavailable",
            "didn't catch",
            "did not catch",
            "tell me ",
            "need both",
            "need a",
            "not recognized",
            "not available",
            "still warming up",
            "starting up",
            "try again",
            "error",
            "offline",
            "no speech captured",
            "no update information",
            "i don't know a saved contact",
        )
        if any(marker in reply for marker in failure_markers):
            return False

        command_noise = (
            "brain stor",
            "set volume",
            "set volume to",
            "check for upda",
        )
        if lowered in command_noise:
            return False

        return True

    def _should_suggest(self, command: str) -> bool:
        lowered = command.lower().strip()
        if not lowered:
            return False
        if self._is_pending_tasks_query(lowered):
            return False
        if self._is_profile_query(lowered):
            return False
        if self._suggestion_cooldown_turns > 0:
            return False
        if len(lowered) < 18:
            return False
        if self._looks_incomplete(lowered):
            return False
        if self._is_message_related(lowered):
            return False
        prefixes = (
            "open ",
            "find file ",
            "find folder ",
            "open folder ",
            "message ",
            "text ",
            "send message to",
            "set brightness",
            "wifi ",
            "bluetooth ",
            "increase volume",
            "decrease volume",
            "check updates",
            "update apps",
            "lock pc",
            "sleep pc",
        )
        return not lowered.startswith(prefixes)

    def _is_pending_tasks_query(self, lowered: str) -> bool:
        text = " ".join(lowered.strip().split())
        if text in {
            "show tasks",
            "show cowork tasks",
            "list tasks",
            "task list",
            "pending tasks",
            "remaining tasks",
            "what are my pending tasks",
            "what are my remaining tasks",
            "task dashboard",
            "what is next",
            "what's next",
            "whats next",
            "next task",
            "next cowork task",
        }:
            return True
        pending_like = re.search(r"\bpend\w*\s+tas\w*\b", text) is not None
        remaining_like = ("remaining" in text and "task" in text)
        if pending_like or remaining_like:
            return True
        if text.startswith("what are my pending tas") or text.startswith("whata re my pending task"):
            return True
        return False

    def _try_semantic_task_command(self, command: str, lowered: str) -> "CommandResult | None":
        """
        Handles natural-language task queries with semantic domain understanding.

        Detects commands like:
          - "show only networking tasks"
          - "list the monitoring ones"
          - "what pending tasks are not related to networking"
          - "sort out the cybersecurity tasks"
        """
        # Must reference tasks in some way
        task_signals = (
            "task", "pending", "remaining", "queue", "list",
            "from", "ones", "those", "the ones",
        )
        if not any(sig in lowered for sig in task_signals):
            return None

        filter_intent = self._semantic.detect_task_filter_intent(command)
        if filter_intent is None:
            # Check for "group tasks" or "categorize tasks" type requests
            group_signals = ("group", "categorize", "sort", "organise", "organize", "by category", "by domain")
            if any(sig in lowered for sig in group_signals) and "task" in lowered:
                return self._build_grouped_task_reply()
            return None

        tasks = self.task_queue.list()
        if not tasks:
            return CommandResult("Cowork queue is currently empty.", action="cowork")

        titles = [t.title for t in tasks]
        domain = filter_intent["domain"]
        label = filter_intent["label"]
        mode = filter_intent["mode"]

        if mode == "include":
            matched = [t for t in titles if self._semantic.classify(t).domain == domain]
            if not matched:
                return CommandResult(
                    f"No {label} tasks found in the queue. All current tasks:\n"
                    + "\n".join(f"- {t}" for t in titles),
                    action="cowork",
                )
            reply = f"{label} tasks in your queue:\n" + "\n".join(f"- {t}" for t in matched)
        else:  # exclude
            non_matched = [t for t in titles if self._semantic.classify(t).domain != domain]
            if not non_matched:
                return CommandResult(
                    f"Every task in the queue is classified as {label}. Nothing to show outside that domain.",
                    action="cowork",
                )
            reply = f"Tasks not related to {label}:\n" + "\n".join(f"- {t}" for t in non_matched)

        return CommandResult(reply, action="cowork")

    def _build_grouped_task_reply(self) -> CommandResult:
        """Group all pending tasks by their semantic domain."""
        tasks = self.task_queue.list()
        if not tasks:
            return CommandResult("Cowork queue is currently empty.", action="cowork")
        groups = self._semantic.group_by_domain([t.title for t in tasks])
        if not groups:
            return CommandResult(self.task_queue.summary(), action="cowork")
        lines = ["Tasks grouped by domain:"]
        for group_label, group_tasks in groups.items():
            lines.append(f"\n{group_label}:")
            for title in group_tasks:
                lines.append(f"  - {title}")
        return CommandResult("\n".join(lines), action="cowork")

    def _is_profile_query(self, lowered: str) -> bool:
        text = " ".join(lowered.strip().split())
        patterns = (
            "what do you know about me",
            "so what you know about me",
            "what you know about me",
            "what do u know about me",
            "what do you remember about me",
            "what do you remember",
            "tell me about me",
        )
        return any(pat in text for pat in patterns)

    def _profile_summary(self) -> str:
        remembered = self.memory.recent(limit=8, include_actions={"note", "memory", "cowork", "files", "message"})
        if not remembered:
            return "I only know what you've told me in this assistant. Right now I don't have saved personal facts to report."
        recent_commands = [item.command for item in remembered if item.command.strip()]
        if not recent_commands:
            return "I only know what you've told me in this assistant. I don't have clear saved personal facts yet."
        compact = "; ".join(recent_commands[:4])
        return (
            "I only know what you've shared in this local session and memory. "
            f"Recent items I can reference: {compact}."
        )

    def _looks_incomplete(self, text: str) -> bool:
        incomplete_endings = (
            " a",
            " an",
            " the",
            " this is a",
            " saying",
            " send",
            " message",
            " text",
            " open",
            " search",
        )
        return any(text.endswith(ending) for ending in incomplete_endings)

    def _is_whatsapp_send_command(self, text: str) -> bool:
        starters = ("send message to ", "message ", "text ")
        if text.startswith(starters) and any(word in text for word in (" saying ", " that ", " telling them ")):
            return True
        return self._starts_with_contact(text) and any(word in text for word in (" saying ", " that ", " telling them "))

    def _is_whatsapp_call_command(self, text: str) -> bool:
        return (
            (text.startswith("call ") or text.startswith("voice call ") or text.startswith("ring "))
            and "video call" not in text
        )

    def _is_whatsapp_video_call_command(self, text: str) -> bool:
        return text.startswith("video call ")

    def _is_message_contact_only_command(self, text: str) -> bool:
        starters = ("send message to ", "message ", "text ")
        return text.startswith(starters) and not any(word in text for word in (" saying ", " that ", " telling them "))

    def _is_message_related(self, text: str) -> bool:
        if self._is_whatsapp_send_command(text) or self._is_message_contact_only_command(text):
            return True
        if " saying " in text or " telling them " in text:
            return any(name in text for name in self.config.contacts)
        return False

    def _starts_with_contact(self, text: str) -> bool:
        lowered = text.lower().strip()
        return any(lowered.startswith(f"{name} ") or lowered == name for name in self.config.contacts)

    def _looks_incomplete_message(self, text: str) -> bool:
        cleaned = text.lower().strip()
        if len(cleaned) < 10:
            return True
        incomplete_endings = (" a", " an", " the", " this is a", " this is", " that this is a")
        return any(cleaned.endswith(ending) for ending in incomplete_endings)

    def _polish_reply(self, text: str, action: str) -> str:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return text
        if action in {"audio", "system", "files", "clock", "updates", "status", "message"}:
            return cleaned
        if action in {"agent", "quick"}:
            sentences = re.split(r"(?<=[.!?])\s+", cleaned)
            return " ".join(sentences[:3]).strip()
        if action == "cowork":
            return cleaned
        if action in {"plan", "brainstorm", "think"}:
            lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
            if len(lines) <= 5:
                return "\n".join(lines)
            return "\n".join(lines[:5])
        return cleaned

    def _run_focus_mode(self) -> str:
        actions = [
            self.media.open_spotify(),
            self.media.playlist_for_vibe("deep focus ambient"),
        ]
        return "Focus mode activated. " + " ".join(actions)

    def _run_research_mode(self) -> str:
        actions = [
            self._google("latest breakthroughs in artificial intelligence"),
            self.media.open_site("https://en.wikipedia.org/wiki/Artificial_intelligence", "Wikipedia"),
            self.system.open_app("notepad"),
        ]
        return "Research mode activated. " + " ".join(actions)

    def _run_coding_mode(self) -> str:
        actions = [
            self.media.playlist_for_vibe("programming synthwave"),
            self.media.open_site("https://github.com/", "GitHub"),
            self.media.open_site("https://stackoverflow.com/", "Stack Overflow"),
        ]
        return "Coding mode activated. " + " ".join(actions)

    def _run_cinematic_mode(self) -> str:
        actions = [
            self.media.launch_youtube_mix("epic cinematic soundtrack"),
            self.media.search_spotify("cinematic orchestral playlist"),
        ]
        return "Cinematic mode activated. " + " ".join(actions)

    # ── Short-term context ring buffer ────────────────────────────────────────

    def _update_short_term_context(self, user_input: str, assistant_reply: str) -> None:
        """Push the latest turn into the short-term ring buffer (maxlen=8)."""
        self._short_term_context.append({"user": user_input, "edith": assistant_reply})

    def _short_term_context_block(self) -> str:
        """Return a formatted string of the last N turns for prompt injection."""
        if not self._short_term_context:
            return "No recent conversation turns."
        lines = []
        for i, turn in enumerate(self._short_term_context, 1):
            lines.append(f"- Turn {i}: User: \"{turn['user'][:80]}\" → EDITH: \"{turn['edith'][:120]}\"")
        return "\n".join(lines)

    # ── JARVIS persona voice filter ───────────────────────────────────────────

    _JARVIS_FILLER_OPENERS = re.compile(
        r"^(?:certainly[!,.]?\s*|absolutely[!,.]?\s*|of course[!,.]?\s*|sure thing[!,.]?\s*"
        r"|sure[!,.]?\s*|great question[!,.]?\s*|that['']s a great question[!,.]?\s*"
        r"|i['']d be happy to[!,.]?\s*|happy to help[!,.]?\s*|let me help you[!,.]?\s*"
        r"|of course[,!]?\s*|understood[,!]?\s*|noted[,!]?\s*|roger that[,!]?\s*"
        r"|right away[,!]?\s*|on it[,!]?\s*|got it[,!]?\s*)",
        re.IGNORECASE,
    )

    def _strip_jarvis_filler(self, text: str) -> str:
        """Remove generic verbal filler that breaks the JARVIS persona."""
        cleaned = self._JARVIS_FILLER_OPENERS.sub("", text).strip()
        # Capitalise first letter after stripping
        if cleaned and not cleaned[0].isupper():
            cleaned = cleaned[0].upper() + cleaned[1:]
        # Remove "As an AI / as a large language model" hedging
        cleaned = re.sub(
            r"\b(?:as an AI|as an artificial intelligence|as a language model|as a large language model)\b",
            "as your assistant",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned or text

    def _apply_persona_voice(self, text: str, action: str, command: str = "") -> str:
        """Apply JARVIS-style persona filter to any LLM output."""
        if not text:
            return text
        if action in {"audio", "system", "files", "clock", "updates", "status", "message", "cowork"}:
            return text
        return self._strip_jarvis_filler(text)

    # ── WhatsApp style-clone draft reply ─────────────────────────────────────

    def _draft_whatsapp_reply(self, contact: str) -> CommandResult:
        """Read the current WhatsApp chat, analyse the user's style, draft a reply."""
        resolved = self._resolve_whatsapp_name(contact)
        try:
            chat_text = self.whatsapp.read_current_chat()
        except Exception:
            chat_text = ""
        if not chat_text:
            return CommandResult(
                f"I couldn't read the current WhatsApp chat. Open the conversation with {resolved} first.",
                action="message",
            )
        prompt = (
            f"You are analysing a WhatsApp chat. The user's name is the owner of this phone.\n"
            f"Read the following chat history and draft a natural reply that matches the user's "
            f"writing style (tone, length, punctuation, emoji usage).\n\n"
            f"Chat:\n{chat_text[:3000]}\n\n"
            f"Return ONLY the draft message text, nothing else."
        )
        try:
            draft = self.agent.quick_think(prompt, self._context_history())
            draft = draft.strip().strip('"').strip("'")
        except Exception:
            return CommandResult("I couldn't generate a draft reply right now.", action="message")

        self._pending_whatsapp_draft = (resolved, draft)
        return CommandResult(
            f"Draft ready for {resolved}:\n\n\"{draft}\"\n\nSay 'yes' to send or 'no' to discard.",
            action="message",
        )

    # ── RAG quality filter ────────────────────────────────────────────────────

    def _is_worthy_of_rag(self, command: str, reply: str) -> bool:
        """Return True if this interaction is worth storing in the RAG knowledge base."""
        if len(command.split()) < 6 or len(reply.split()) < 8:
            return False
        noise_markers = (
            "i hit a temporary model issue",
            "please try that once more",
            "i couldn't",
            "i can't",
            "i cannot",
            "tell me what",
            "no speech captured",
        )
        reply_lower = reply.lower()
        if any(m in reply_lower for m in noise_markers):
            return False
        command_noise_prefixes = (
            "set volume", "check updates", "lock pc", "sleep pc",
            "wifi on", "wifi off", "bluetooth",
        )
        lowered_cmd = command.lower().strip()
        if any(lowered_cmd.startswith(p) for p in command_noise_prefixes):
            return False
        return True
