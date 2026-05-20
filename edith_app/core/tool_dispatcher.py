"""
edith_app.core.tool_dispatcher
================================
Bridges LLM tool-call decisions to EDITH's Python service layer.
Every capability is a registered tool. The NeuralRouter calls
dispatch(action, params) and gets a string result back.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import webbrowser
from datetime import datetime
from typing import Any, Callable

from edith_app.core.semantic_classifier import SemanticClassifier

logger = logging.getLogger("edith.tool_dispatcher")

# ── Compact tool manifest for the LLM system prompt ───────────────────────────
TOOL_MANIFEST = """\
You have the following tools. Output exactly ONE JSON per turn — no prose, no markdown.

SYSTEM
  {"action":"open_app","name":"<app_or_website_or_folder>"}
  {"action":"lock_pc"}
  {"action":"sleep_pc"}
  {"action":"check_updates"}
  {"action":"get_time"}
  {"action":"get_date"}
  {"action":"system_status"}

AUDIO / DISPLAY
  {"action":"set_volume","level":<0-100>}
  {"action":"adjust_volume","direction":"up|down"}
  {"action":"mute"}
  {"action":"unmute"}
  {"action":"set_brightness","level":<0-100>}
  {"action":"wifi","enabled":true|false}
  {"action":"bluetooth","enabled":true|false}

MEDIA
  {"action":"play_youtube","query":"<search terms>"}
  {"action":"open_youtube"}
  {"action":"open_spotify"}
  {"action":"play_spotify","query":"<search terms>"}

FILES
  {"action":"search_files","query":"<name>"}
  {"action":"move_file","item":"<name>","destination":"<path>"}
  {"action":"organize_folder","target":"desktop|downloads|<path>","by_context":false,"preview":true}
  {"action":"undo_organize"}
  {"action":"analyze_folder","target":"desktop|downloads|<path>","by_context":false}

WHATSAPP
  {"action":"whatsapp_open"}
  {"action":"whatsapp_send","contact":"<name>","message":"<text>"}
  {"action":"whatsapp_call","contact":"<name>","video":false}
  {"action":"whatsapp_read"}
  {"action":"list_contacts"}

TASKS
  {"action":"list_tasks"}
  {"action":"filter_tasks","domain":"networking|monitoring_devops|cybersecurity|programming|ai_ml","mode":"include|exclude"}
  {"action":"group_tasks"}
  {"action":"add_task","title":"<title>"}
  {"action":"complete_task","title":"<title>"}

KNOWLEDGE / MEMORY / COWORK
  {"action":"search_memory","query":"<question>"}
  {"action":"search_web","query":"<terms>"}
  {"action":"save_note","text":"<content>"}
  {"action":"save_fact","fact":"<fact>"}
  {"action":"summarize_topic","topic":"<topic>"}
  {"action":"brainstorm","topic":"<topic>"}
  {"action":"cowork_task","goal":"<goal>","mode":"cowork|workspace|coding|edit|browser"}

TERMINAL
  {"action":"reply","input":"<final message to user>"}
"""


class ToolDispatcher:
    """
    Executes tool calls issued by the NeuralRouter's LLM.
    Constructed once by EdithAssistant and passed to NeuralRouter.
    """

    def __init__(self, services: dict[str, Any]) -> None:
        self._sys = services.get("system")
        self._media = services.get("media")
        self._audio = services.get("audio")
        self._wa = services.get("whatsapp")
        self._tasks = services.get("task_queue")
        self._rag = services.get("rag")
        self._notes = services.get("notes")
        self._cowork = services.get("cowork")
        self._agent = services.get("agent")
        self._knowledge = services.get("knowledge")
        self._conn = services.get("connectivity")
        self._cfg = services.get("config")
        self._ctx_fn: Callable = services.get("context_history_fn", lambda: [])
        # Callback for signalling pending state back to EdithAssistant
        self._pending_cb: Callable[[str, Any], None] | None = services.get("pending_callback")
        # Use the module-level singleton — avoids creating a third SemanticClassifier instance
        from edith_app.core.semantic_classifier import _classifier as _sem_singleton
        self._semantic = _sem_singleton

    # ── Public dispatch entry ──────────────────────────────────────────────────

    def dispatch(self, action: str, params: dict[str, Any]) -> str:
        handler = _HANDLERS.get(action)
        if handler is None:
            return f"Unknown tool '{action}'. Use 'reply' to respond directly."
        try:
            return handler(self, **{k: v for k, v in params.items() if k != "action"})
        except Exception as exc:
            logger.warning("Tool %s(%s) failed: %s", action, params, exc)
            return f"Tool '{action}' encountered an error: {exc}"

    # ── System ─────────────────────────────────────────────────────────────────

    def _open_app(self, name: str = "", **_) -> str:
        return self._sys.open_target(name) if name else "[USER_PROMPT] Which app, website, or folder do you want to open?"

    def _check_intent_gate(self, keywords: list[str]) -> str | None:
        """Returns error string if gated, None if allowed. Handles both ChatMessage objects and dicts."""
        try:
            history = self._ctx_fn()
            if not history:
                return "Error: Cannot infer user intent. Use 'reply' instead."
            last_user = ""
            for m in reversed(history):
                # Support both ChatMessage objects and plain dicts
                source = getattr(m, "source", None) or (m.get("source") if isinstance(m, dict) else None)
                text = getattr(m, "text", None) or (m.get("text") if isinstance(m, dict) else "")
                if source == "user" and text:
                    last_user = text.lower()
                    break
            if not last_user or not any(k in last_user for k in keywords):
                return "Error: User did not explicitly request this action. Use 'reply' instead."
        except Exception:
            return "Error: Validation failed. Use 'reply'."
        return None

    def _lock_pc(self, **_) -> str:
        err = self._check_intent_gate(["lock", "secure", "screen"])
        if err: return err
        return self._sys.lock_pc()

    def _sleep_pc(self, **_) -> str:
        err = self._check_intent_gate(["sleep", "hibernate"])
        if err: return err
        return self._sys.sleep_pc()

    def _check_updates(self, **_) -> str:
        return self._sys.check_updates()

    def _get_time(self, **_) -> str:
        return f"The time is {datetime.now().strftime('%I:%M %p')}."

    def _get_date(self, **_) -> str:
        return f"Today is {datetime.now().strftime('%A, %d %B %Y')}."

    def _system_status(self, **_) -> str:
        ok, status = self._agent.runtime_status()
        online = self._conn.is_online() if self._conn else False
        return (
            f"Model: {'READY' if ok else 'DEGRADED'} ({status}). "
            f"Internet: {'ONLINE' if online else 'OFFLINE'}."
        )

    # ── Audio / display ────────────────────────────────────────────────────────

    def _set_volume(self, level: int = 50, **_) -> str:
        return self._audio.set_volume(int(level))

    def _adjust_volume(self, direction: str = "up", **_) -> str:
        return self._audio.adjust_volume(0.1 if direction == "up" else -0.1)

    def _mute(self, **_) -> str:
        return self._audio.mute()

    def _unmute(self, **_) -> str:
        return self._audio.unmute()

    def _set_brightness(self, level: int = 60, **_) -> str:
        return self._sys.set_brightness(int(level))

    def _wifi(self, enabled: bool = True, **_) -> str:
        return self._sys.wifi(bool(enabled))

    def _bluetooth(self, enabled: bool = True, **_) -> str:
        if enabled is None:
            return self._sys.bluetooth_settings()
        return self._sys.bluetooth(bool(enabled))

    # ── Media ──────────────────────────────────────────────────────────────────

    def _play_youtube(self, query: str = "", **_) -> str:
        return self._media.search_youtube(query) if query else self._media.open_youtube_home()

    def _open_youtube(self, **_) -> str:
        return self._media.open_youtube_home()

    def _open_spotify(self, **_) -> str:
        return self._media.open_spotify()

    def _play_spotify(self, query: str = "", **_) -> str:
        return self._media.play_spotify(query) if query else self._media.open_spotify()

    # ── Files ──────────────────────────────────────────────────────────────────

    def _search_files(self, query: str = "", **_) -> str:
        if not query:
            return "[USER_PROMPT] Specify a filename to search for."
        matches = self._sys.search_files(query)
        return ("Found:\n" + "\n".join(matches[:8])) if matches else f"No files matching '{query}'."

    def _move_file(self, item: str = "", destination: str = "", **_) -> str:
        if not item or not destination:
            return "[USER_PROMPT] I need both a source file and a destination."
        return self._sys.move_item(item, destination)

    def _organize_folder(self, target: str = "desktop", by_context: bool = False, preview: bool = True, **_) -> str:
        if preview:
            result = self._sys.preview_organization(target, by_context=by_context)
            if self._pending_cb:
                self._pending_cb("organization", (target, bool(by_context)))
            return result
        fn = self._sys.organize_folder_by_context if by_context else self._sys.organize_folder
        return fn(target)

    def _undo_organize(self, **_) -> str:
        return self._sys.undo_last_organization()

    def _analyze_folder(self, target: str = "desktop", by_context: bool = False, **_) -> str:
        if by_context:
            return self._sys.analyze_folder_context(target)
        return self._sys.folder_clutter_report(target)

    # ── WhatsApp ───────────────────────────────────────────────────────────────

    def _whatsapp_open(self, **_) -> str:
        return self._wa.open_app()

    def _whatsapp_send(self, contact: str = "", message: str = "", **_) -> str:
        if not contact:
            return "[USER_PROMPT] Which contact should I message?"
        resolved = self._resolve_contact(contact)
        if not message:
            if self._pending_cb:
                self._pending_cb("message_contact", resolved)
            return f"[USER_PROMPT] What should I send to {resolved}?"
        if self._pending_cb:
            self._pending_cb("whatsapp_draft", (resolved, message))
        return f"[USER_PROMPT] I have drafted a message to {resolved}:\n\n\"{message}\"\n\nShall I send it?"

    def _whatsapp_call(self, contact: str = "", video: bool = False, **_) -> str:
        if not contact:
            return "[USER_PROMPT] Who should I call?"
        resolved = self._resolve_contact(contact)
        if self._pending_cb:
            self._pending_cb("whatsapp_call", (resolved, video))
        return f"[USER_PROMPT] Ready to call {resolved} (video={video}). Shall I start the call?"

    def _whatsapp_read(self, **_) -> str:
        return self._wa.read_current_chat()

    def _list_contacts(self, **_) -> str:
        names = self._cfg.whatsapp_display_names if self._cfg else {}
        return json.dumps(names, indent=2) if names else "No contacts saved."

    # ── Tasks ──────────────────────────────────────────────────────────────────

    def _list_tasks(self, **_) -> str:
        return self._tasks.summary()

    def _filter_tasks(self, domain: str = "", mode: str = "include", **_) -> str:
        tasks = self._tasks.list()
        if not tasks:
            return "Task queue is empty."
        titles = [t.title for t in tasks]
        if not domain:
            return "Tasks:\n" + "\n".join(f"- {t}" for t in titles)
        label = domain.replace("_", " ").title()
        # Batch-classify all titles in one call instead of N individual calls
        classified = self._semantic.classify_many(titles)
        if mode == "include":
            matched = [c.title for c in classified if c.domain == domain]
            return (f"{label} tasks:\n" + "\n".join(f"- {t}" for t in matched)) if matched else f"No {label} tasks found."
        others = [c.title for c in classified if c.domain != domain]
        return (f"Tasks outside {label}:\n" + "\n".join(f"- {t}" for t in others)) if others else f"All tasks are {label}."

    def _group_tasks(self, **_) -> str:
        tasks = self._tasks.list()
        if not tasks:
            return "Task queue is empty."
        groups = self._semantic.group_by_domain([t.title for t in tasks])
        lines = ["Tasks by domain:"]
        for label, items in groups.items():
            lines.append(f"\n{label}:")
            lines.extend(f"  - {i}" for i in items)
        return "\n".join(lines)

    def _add_task(self, title: str = "", **_) -> str:
        if not title:
            return "[USER_PROMPT] What should the task be called?"
        t = self._tasks.add(title)
        return f"Added: {t.title}."

    def _complete_task(self, title: str = "", **_) -> str:
        if not title:
            return "[USER_PROMPT] Which task should I mark as complete?"
        # Fuzzy match
        for task in self._tasks.list():
            if title.lower() in task.title.lower() or task.title.lower() in title.lower():
                done = self._tasks.complete(task.title)
                return f"Marked done: {done.title}." if done else "Could not mark that task."
        t = self._tasks.complete(title)
        return f"Marked done: {t.title}." if t else f"No task matching '{title}'."

    # ── Knowledge & memory ─────────────────────────────────────────────────────

    def _search_memory(self, query: str = "", **_) -> str:
        if not query:
            return "[USER_PROMPT] What should I search for in memory?"
        try:
            return self._rag.ask_docs(query) or "Nothing relevant found."
        except Exception:
            return "Memory search unavailable."

    def _search_web(self, query: str = "", **_) -> str:
        if not query:
            return "What should I search for?"
        if self._conn and not self._conn.is_online():
            return "Internet is offline."
        encoded = urllib.parse.quote_plus(query)
        webbrowser.open(f"https://www.google.com/search?q={encoded}")
        return f"Searching the web for: {query}."

    def _save_note(self, text: str = "", **_) -> str:
        return self._notes.save(text) if text else "What should I save?"

    def _save_fact(self, fact: str = "", **_) -> str:
        if not fact:
            return "What fact should I remember?"
        ok = self._rag.store_user_fact(fact)
        return "Stored in long-term memory." if ok else "Could not write to memory right now."

    def _summarize_topic(self, topic: str = "", **_) -> str:
        if not topic:
            return "What topic should I summarise?"
        if self._conn and not self._conn.is_online():
            return f"Internet is offline — can't fetch info on {topic} right now."
        return self._knowledge.summarize_topic(topic)

    def _brainstorm(self, topic: str = "", **_) -> str:
        if not topic:
            return "What topic should I brainstorm on?"
        run = self._cowork.run(topic, self._ctx_fn(), mode="brainstorm")
        return run.reply

    def _cowork_task(self, goal: str = "", mode: str = "cowork", **_) -> str:
        if not goal:
            return "What goal should we cowork on?"
        valid_modes = {"cowork", "workspace", "coding", "edit", "browser"}
        if mode not in valid_modes:
            mode = "cowork"
        run = self._cowork.run(goal, self._ctx_fn(), mode=mode)
        return run.reply

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _resolve_contact(self, name: str) -> str:
        if not self._cfg:
            return name
        lowered = name.lower().strip()
        display = self._cfg.whatsapp_display_names.get(lowered)
        if display:
            return display
        for saved in self._cfg.contacts:
            if saved.lower() == lowered:
                d = self._cfg.whatsapp_display_names.get(saved.lower())
                return d if d else saved
        return name.strip()


# ── Handler dispatch table ─────────────────────────────────────────────────────
_HANDLERS: dict[str, Callable] = {
    "open_app":        ToolDispatcher._open_app,
    "lock_pc":         ToolDispatcher._lock_pc,
    "sleep_pc":        ToolDispatcher._sleep_pc,
    "check_updates":   ToolDispatcher._check_updates,
    "get_time":        ToolDispatcher._get_time,
    "get_date":        ToolDispatcher._get_date,
    "system_status":   ToolDispatcher._system_status,
    "set_volume":      ToolDispatcher._set_volume,
    "adjust_volume":   ToolDispatcher._adjust_volume,
    "mute":            ToolDispatcher._mute,
    "unmute":          ToolDispatcher._unmute,
    "set_brightness":  ToolDispatcher._set_brightness,
    "wifi":            ToolDispatcher._wifi,
    "bluetooth":       ToolDispatcher._bluetooth,
    "play_youtube":    ToolDispatcher._play_youtube,
    "open_youtube":    ToolDispatcher._open_youtube,
    "open_spotify":    ToolDispatcher._open_spotify,
    "play_spotify":    ToolDispatcher._play_spotify,
    "search_files":    ToolDispatcher._search_files,
    "move_file":       ToolDispatcher._move_file,
    "organize_folder": ToolDispatcher._organize_folder,
    "undo_organize":   ToolDispatcher._undo_organize,
    "analyze_folder":  ToolDispatcher._analyze_folder,
    "whatsapp_open":   ToolDispatcher._whatsapp_open,
    "whatsapp_send":   ToolDispatcher._whatsapp_send,
    "whatsapp_call":   ToolDispatcher._whatsapp_call,
    "whatsapp_read":   ToolDispatcher._whatsapp_read,
    "list_contacts":   ToolDispatcher._list_contacts,
    "list_tasks":      ToolDispatcher._list_tasks,
    "filter_tasks":    ToolDispatcher._filter_tasks,
    "group_tasks":     ToolDispatcher._group_tasks,
    "add_task":        ToolDispatcher._add_task,
    "complete_task":   ToolDispatcher._complete_task,
    "search_memory":   ToolDispatcher._search_memory,
    "search_web":      ToolDispatcher._search_web,
    "save_note":       ToolDispatcher._save_note,
    "save_fact":       ToolDispatcher._save_fact,
    "summarize_topic": ToolDispatcher._summarize_topic,
    "brainstorm":      ToolDispatcher._brainstorm,
    "cowork_task":     ToolDispatcher._cowork_task,
    # Aliases that models commonly produce
    "search_tasks":    ToolDispatcher._filter_tasks,
    "powershell":      lambda self, input="", **_: f"Direct shell disabled. Use 'open_app' instead.",
}
