from __future__ import annotations

import json
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from math import sin
from pathlib import Path
from tkinter import ttk

from edith_app.assistant import EdithAssistant


class EdithDesktopUI:
    def __init__(self, assistant: EdithAssistant) -> None:
        self.assistant = assistant
        self.root = tk.Tk()
        self.root.title("Edith Neural Console")
        self.root.geometry("1200x780")
        self.root.minsize(980, 680)
        self._colors = {
            "bg": "#071018",
            "panel": "#0c1824",
            "card": "#102333",
            "hero": "#0d2c3d",
            "glass": "#15384b",
            "surface": "#081723",
            "entry": "#122838",
            "line": "#204359",
            "text": "#e6fdff",
            "muted": "#8dcad3",
            "accent": "#54d8ff",
            "accent_soft": "#9aefff",
            "success": "#79f1ca",
            "warn": "#ffd166",
            "error": "#ff8f8f",
        }
        self.root.configure(bg=self._colors["bg"])

        self.input_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.health_var = tk.StringVar(value="Runtime health loading...")
        self.mode_var = tk.StringVar()
        self.quick_var = tk.StringVar(value="Try: cowork on improving startup performance")
        self.entity_var = tk.StringVar(value="Detected entities and cowork insights will appear here.")
        self.cowork_var = tk.StringVar(value="Cowork queue and edit proposals will appear here.")
        self.preflight_var = tk.StringVar(value="Run preflight to verify model, voice, and runtime readiness.")
        self.voice_var = tk.StringVar(value="Voice mode offline")
        self.chat_log: tk.Text | None = None
        self.command_entry: tk.Entry | None = None
        self.voice_enabled = False
        self.voice_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.voice_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.processing = False
        self.immersive_window: tk.Toplevel | None = None
        self.voice_state = "idle"
        self.voice_state_label_var = tk.StringVar(value="Idle")
        self.loading_var = tk.StringVar(value="")
        self._animation_tick = 0
        self.voice_canvas: tk.Canvas | None = None
        self.voice_orb = None
        self.voice_glow = None
        self.immersive_canvas: tk.Canvas | None = None
        self.immersive_orb = None
        self.immersive_glow = None
        self._queued_voice_state = "idle"
        self.command_history: list[str] = []
        self.command_history_index: int = -1
        self._deferred_command: str | None = None
        self._request_seq = 0
        self._active_request_id: int | None = None
        self._timed_out_requests: set[int] = set()
        self._pending_voice_command: str | None = None
        self._pending_voice_confidence: float | None = None
        self._telemetry_path = Path(self.assistant.config.telemetry_path)

        self._build_theme()
        self._build_layout()
        self._initialize()
        self.root.after(80, self._process_voice_queue)
        self.root.after(80, self._animate_orbs)
        self.root.protocol("WM_DELETE_WINDOW", self._shutdown)
        self.root.bind("<Control-l>", lambda event: self._focus_command_entry())
        self.root.bind("<Control-Return>", lambda event: self._submit())

    def run(self) -> None:
        self.root.mainloop()

    def _build_theme(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("Panel.TFrame", background=self._colors["bg"])
        style.configure("Card.TFrame", background=self._colors["card"])
        style.configure("Hero.TFrame", background=self._colors["hero"])
        style.configure("Glass.TFrame", background=self._colors["glass"])
        style.configure("Title.TLabel", background=self._colors["hero"], foreground=self._colors["text"], font=("Segoe UI Semibold", 24))
        style.configure("Sub.TLabel", background=self._colors["hero"], foreground=self._colors["muted"], font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=self._colors["card"], foreground=self._colors["text"], font=("Segoe UI Semibold", 11))
        style.configure("CardBody.TLabel", background=self._colors["card"], foreground=self._colors["muted"], font=("Segoe UI", 10))
        style.configure("Action.TButton", font=("Segoe UI Semibold", 10), padding=9)
        style.map(
            "Action.TButton",
            background=[("active", self._colors["glass"])],
            foreground=[("active", self._colors["text"])],
        )
        style.configure("Status.TLabel", background=self._colors["glass"], foreground=self._colors["text"], font=("Segoe UI", 10))
        style.configure("Meta.TLabel", background=self._colors["card"], foreground=self._colors["accent_soft"], font=("Segoe UI Semibold", 9))

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self.root, style="Panel.TFrame", width=290)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)

        main = ttk.Frame(self.root, style="Panel.TFrame")
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        main.rowconfigure(2, weight=0)

        hero = ttk.Frame(main, style="Hero.TFrame", padding=22)
        hero.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        hero.columnconfigure(0, weight=1)
        hero.columnconfigure(1, weight=0)
        ttk.Label(hero, text="Edith Neural Console", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            hero,
            text="Always-listening voice, multi-model local AI, coworker mode, system control, and media automation in one desktop surface.",
            style="Sub.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(
            hero,
            text="LOCAL-FIRST  •  VOICE-NATIVE  •  COWORKER MODE",
            style="Meta.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Button(hero, text="Toggle Voice Mode", style="Action.TButton", command=self._toggle_wake_mode).grid(
            row=0, column=1, rowspan=3, sticky="e"
        )
        ttk.Button(hero, text="Immersive Mode", style="Action.TButton", command=self._toggle_immersive_mode).grid(
            row=0, column=2, rowspan=3, sticky="e", padx=(10, 0)
        )

        body = ttk.Frame(main, style="Panel.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        chat_card = ttk.Frame(body, style="Card.TFrame", padding=14)
        chat_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        chat_card.columnconfigure(0, weight=1)
        chat_card.rowconfigure(1, weight=1)
        ttk.Label(chat_card, text="Conversation", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")

        self.chat_log = tk.Text(
            chat_card,
            bg=self._colors["surface"],
            fg=self._colors["text"],
            insertbackground=self._colors["text"],
            relief="flat",
            wrap="word",
            font=("Consolas", 11),
            padx=14,
            pady=14,
            spacing1=3,
            spacing2=3,
            spacing3=8,
            selectbackground="#214a63",
            selectforeground=self._colors["text"],
        )
        self.chat_log.grid(row=1, column=0, sticky="nsew", pady=(10, 12))
        chat_scroll = ttk.Scrollbar(chat_card, orient="vertical", command=self.chat_log.yview)
        chat_scroll.grid(row=1, column=1, sticky="ns", pady=(10, 12))
        self.chat_log.configure(yscrollcommand=chat_scroll.set)

        input_row = ttk.Frame(chat_card, style="Card.TFrame")
        input_row.grid(row=2, column=0, sticky="ew")
        input_row.columnconfigure(0, weight=1)

        entry = tk.Entry(
            input_row,
            textvariable=self.input_var,
            bg=self._colors["entry"],
            fg=self._colors["text"],
            insertbackground=self._colors["text"],
            relief="flat",
            font=("Segoe UI", 11),
            highlightthickness=1,
            highlightbackground=self._colors["line"],
            highlightcolor=self._colors["accent"],
        )
        self.command_entry = entry
        entry.grid(row=0, column=0, sticky="ew", ipady=11)
        entry.bind("<Return>", lambda event: self._submit())
        entry.bind("<Up>", self._history_up)
        entry.bind("<Down>", self._history_down)

        ttk.Button(input_row, text="Execute", style="Action.TButton", command=self._submit).grid(row=0, column=1, padx=(10, 0))
        ttk.Button(input_row, text="Listen", style="Action.TButton", command=self._listen_once).grid(row=0, column=2, padx=(10, 0))
        ttk.Button(input_row, text="Silence", style="Action.TButton", command=self.assistant.stop_speaking).grid(row=0, column=3, padx=(10, 0))
        ttk.Label(
            chat_card,
            text="Type or speak. Enter runs a command, Up/Down recalls history, Ctrl+L focuses the command bar.",
            style="CardBody.TLabel",
        ).grid(row=3, column=0, sticky="w", pady=(10, 0))

        right = ttk.Frame(body, style="Panel.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self._build_sidebar(sidebar)
        self._build_cards(right)

        footer = ttk.Frame(main, style="Glass.TFrame", padding=12)
        footer.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=1)
        footer.columnconfigure(2, weight=1)
        footer.rowconfigure(1, weight=0)
        ttk.Label(footer, textvariable=self.mode_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(footer, textvariable=self.voice_var, style="Status.TLabel").grid(row=0, column=2, sticky="e")
        ttk.Label(footer, textvariable=self.health_var, style="Status.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def _build_sidebar(self, sidebar: ttk.Frame) -> None:
        intro = ttk.Frame(sidebar, style="Hero.TFrame", padding=16)
        intro.grid(row=0, column=0, sticky="ew", padx=14, pady=14)
        ttk.Label(intro, text="Mission Profile", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            intro,
            text="Routines, coworker analysis, continuous listening, and multi-model thinking for a more Jarvis-like flow.",
            style="Sub.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        controls = ttk.Frame(sidebar, style="Panel.TFrame")
        controls.grid(row=1, column=0, sticky="ew", padx=14)
        controls.columnconfigure(0, weight=1)

        actions = [
            ("Focus Mode", "start focus mode"),
            ("Research Mode", "start research mode"),
            ("Coding Mode", "start coding mode"),
            ("Cinematic Mode", "start cinematic mode"),
            ("Brainstorm", "brainstorm how to automate my workflow"),
            ("Think With Me", "think with me about building a personal AI system"),
            ("Cowork Mode", "cowork on improving the startup performance of this project"),
            ("Analyze Workspace", "analyze workspace for bottlenecks"),
            ("Self Improve", "self improve"),
            ("Apply Improve", "self improve apply"),
            ("Run Preflight", "run preflight"),
            ("Export Debug", "export debug bundle"),
            ("Coding Task", "coding task improve the startup flow and verify the result"),
            ("Show Tasks", "show tasks"),
            ("Analyze Desktop", "analyze desktop"),
            ("Organize Desktop", "organize desktop"),
            ("Smart Organize", "organize desktop by context"),
            ("Preview Organize", "preview organize desktop by context"),
            ("Undo Organize", "undo last organization"),
            ("Check Updates", "check updates"),
            ("Open WhatsApp", "open whatsapp"),
            ("Wi-Fi On", "wifi on"),
            ("Open YouTube", "open youtube"),
            ("Open Spotify", "open spotify"),
            ("Open Settings", "open settings"),
        ]
        for row, (label, command) in enumerate(actions):
            ttk.Button(controls, text=label, style="Action.TButton", command=lambda value=command: self._preset(value)).grid(
                row=row,
                column=0,
                sticky="ew",
                pady=(0, 8),
            )

    def _build_cards(self, parent: ttk.Frame) -> None:
        snapshot = ttk.Frame(parent, style="Card.TFrame", padding=14)
        snapshot.grid(row=0, column=0, sticky="ew")
        snapshot.columnconfigure(0, weight=1)
        ttk.Label(snapshot, text="Assistant State", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(snapshot, text="Multi-model routing, Windows utilities, coworker loops, and automation routines.", style="CardBody.TLabel").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )

        preflight = ttk.Frame(parent, style="Card.TFrame", padding=14)
        preflight.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        preflight.columnconfigure(0, weight=1)
        ttk.Label(preflight, text="Preflight", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(preflight, textvariable=self.preflight_var, style="CardBody.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))

        quick = ttk.Frame(parent, style="Card.TFrame", padding=14)
        quick.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        quick.columnconfigure(0, weight=1)
        ttk.Label(quick, text="Quick Prompt", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(quick, textvariable=self.quick_var, style="CardBody.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))

        nlp = ttk.Frame(parent, style="Card.TFrame", padding=14)
        nlp.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        nlp.columnconfigure(0, weight=1)
        ttk.Label(nlp, text="NLP Signals", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(nlp, textvariable=self.entity_var, style="CardBody.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))

        voice = ttk.Frame(parent, style="Card.TFrame", padding=14)
        voice.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        voice.columnconfigure(1, weight=1)
        ttk.Label(voice, text="Voice Presence", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.voice_canvas = tk.Canvas(
            voice,
            width=150,
            height=150,
            bg=self._colors["card"],
            highlightthickness=0,
            relief="flat",
        )
        self.voice_canvas.grid(row=1, column=0, padx=(0, 14), pady=(10, 0))
        self.voice_glow = self.voice_canvas.create_oval(20, 20, 130, 130, fill="#12394f", outline="")
        self.voice_orb = self.voice_canvas.create_oval(38, 38, 112, 112, fill=self._colors["accent"], outline="")
        ttk.Label(voice, textvariable=self.voice_state_label_var, style="CardBody.TLabel").grid(row=1, column=1, sticky="nw", pady=(18, 0))
        ttk.Label(voice, textvariable=self.loading_var, style="CardBody.TLabel").grid(row=2, column=1, sticky="nw", pady=(8, 0))

        ideas = ttk.Frame(parent, style="Card.TFrame", padding=14)
        ideas.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        ideas.columnconfigure(0, weight=1)
        ttk.Label(ideas, text="Suggested Commands", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            ideas,
            text=(
                "start focus mode\n"
                "plan a daily automation workflow\n"
                "brainstorm a better desktop assistant\n"
                "think with me about launching a product\n"
                "cowork on fixing the startup bottleneck\n"
                "analyze workspace for voice issues\n"
                "browser task compare local voice engines for Windows\n"
                "self improve status\n"
                "self improve\n"
                "self improve apply\n"
                "propose skill for smart browser automation\n"
                "analyze desktop\n"
                "analyze desktop by context\n"
                "preview organize desktop by context\n"
                "organize desktop\n"
                "organize folder by context pictures\n"
                "analyze downloads by context\n"
                "undo last organization\n"
                "move screenshot.png to pictures\n"
                "find file invoice\n"
                "check updates\n"
                "set brightness to 60\n"
                "play interstellar soundtrack on youtube\n"
                "spotify playlist deep focus\n"
                "open calculator\n"
                "save note review the architecture tonight"
            ),
            style="CardBody.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        cowork = ttk.Frame(parent, style="Card.TFrame", padding=14)
        cowork.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        cowork.columnconfigure(0, weight=1)
        ttk.Label(cowork, text="Cowork Queue", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(cowork, textvariable=self.cowork_var, style="CardBody.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))

    def _initialize(self) -> None:
        snapshot = self.assistant.snapshot()
        self.mode_var.set(
            f"Mode: {snapshot.mode} | Multi-model coworker {'ready' if snapshot.ai_enabled else 'offline'}"
        )
        self.status_var.set(
            f"Voice {'ready' if snapshot.voice_enabled else 'offline'} | Audio {'ready' if snapshot.audio_enabled else 'limited'} | "
            f"{'Lightweight mode' if self.assistant.config.lightweight_mode else 'Full mode'}"
        )
        mode_label = "wake word required" if self.assistant.config.require_wake_word else "direct command mode"
        self.voice_var.set(f"Voice: {mode_label} | idle")
        self._set_voice_state("idle")
        self._append("system", self.assistant.greet())
        if self.assistant.config.require_wake_word:
            self._append("system", f"Voice mode is configured for the wake word '{self.assistant.config.wake_word}'.")
        else:
            self._append("system", "Voice mode is configured for direct commands. You can simply speak and I will act.")
        self._append("system", "You can ask me to plan, brainstorm, cowork on tasks, inspect this workspace, search files, control apps, and run desktop routines.")
        self.cowork_var.set(self.assistant.task_queue.summary())
        self.preflight_var.set(self.assistant.preflight_report())
        model_ready, detail = self.assistant.agent.runtime_status()
        self.health_var.set(f"Runtime health: {'READY' if model_ready else 'DEGRADED'} ({detail})")
        if self.chat_log is not None:
            self.chat_log.tag_configure("system", foreground=self._colors["accent_soft"])
            self.chat_log.tag_configure("user", foreground=self._colors["text"])
            self.chat_log.tag_configure("assistant", foreground=self._colors["success"])
            self.chat_log.tag_configure("error", foreground=self._colors["error"])
            self.chat_log.tag_configure("label", foreground=self._colors["muted"], font=("Segoe UI Semibold", 9))
        self.root.after(200, self._focus_command_entry)
        self.root.after(1200, self._refresh_runtime_health)
        if self.assistant.config.auto_listen:
            self.root.after(400, self._toggle_wake_mode)

    def _append(self, source: str, text: str) -> None:
        if self.chat_log is None:
            return
        label = {"system": "SYSTEM", "user": "YOU", "assistant": "EDITH", "error": "ERROR"}.get(source, source.upper())
        self.chat_log.insert("end", f"[{label}] ", ("label", source))
        self.chat_log.insert("end", f"{text}\n\n", (source,))
        self.chat_log.see("end")

    def _preset(self, command: str) -> None:
        self.input_var.set(command)
        self._focus_command_entry()
        self._submit()

    def _listen_once(self) -> None:
        self.voice_var.set("Listening for one command...")
        self._set_voice_state("listening")
        spoken = self.assistant.listen_for_command()
        if not spoken:
            self.voice_var.set("Voice: no speech captured")
            self._set_voice_state("idle")
            self._append("error", "Voice capture did not return a command.")
            return
        self.voice_var.set("Voice: command captured")
        self._set_voice_state("processing")
        self.input_var.set(spoken)
        self._submit()

    def _submit(self) -> None:
        command = self.input_var.get().strip()
        if not command:
            return
        if self.processing:
            self._deferred_command = command
            self.input_var.set("")
            self.quick_var.set(f"Queued command: {command}")
            self._append("system", f"Queued while busy: {command}")
            return
        self.assistant.stop_speaking()
        self.input_var.set("")
        if not self.command_history or self.command_history[-1] != command:
            self.command_history.append(command)
        self.command_history_index = len(self.command_history)
        self.quick_var.set(f"Last command: {command}")
        self._append("user", command)
        self.processing = True
        self._set_voice_state("processing")
        self._request_seq += 1
        request_id = self._request_seq
        self._active_request_id = request_id
        started_at = time.monotonic()
        worker = threading.Thread(
            target=self._run_command_worker,
            args=(request_id, command, started_at),
            daemon=True,
        )
        worker.start()
        self.root.after(
            max(1000, int(self.assistant.config.command_timeout_seconds * 1000)),
            lambda rid=request_id, cmd=command, started=started_at: self._on_command_timeout(rid, cmd, started),
        )

    def _run_command_worker(self, request_id: int, command: str, started_at: float) -> None:
        try:
            result = self.assistant.handle(command)
            self.voice_queue.put(("command_result", (request_id, command, started_at, result, None)))
        except Exception as exc:
            self.voice_queue.put(("command_result", (request_id, command, started_at, None, str(exc))))

    def _on_command_timeout(self, request_id: int, command: str, started_at: float) -> None:
        if self._active_request_id != request_id or not self.processing:
            return
        self._timed_out_requests.add(request_id)
        self.processing = False
        self._set_voice_state("idle")
        self.health_var.set("Runtime health: DEGRADED (command timeout - safe mode active)")
        self._append(
            "error",
            "Command timed out. I kept the session alive in safe mode. You can continue with local/system commands.",
        )
        self._log_command_metric(
            command=command,
            status="timeout",
            latency_ms=int((time.monotonic() - started_at) * 1000),
            error="command timeout",
        )
        self._run_deferred_command()

    def _apply_command_result(self, result) -> None:
        entities = result.metadata.get("entities")
        plan = result.metadata.get("plan")
        verified = result.metadata.get("verified")
        edit_brief = result.metadata.get("edit_brief")
        if plan or verified:
            info_parts = []
            if plan:
                info_parts.append(f"Plan ready. {plan.splitlines()[0]}")
            if verified:
                info_parts.append(f"Verified: {verified.splitlines()[0]}")
            self.entity_var.set(" ".join(info_parts))
        else:
            self.entity_var.set(entities or "No named entities detected.")
        if result.action == "cowork":
            panels = []
            if plan:
                panels.append(f"Plan: {plan.splitlines()[0]}")
            if edit_brief:
                panels.append(f"Edit: {edit_brief.splitlines()[0]}")
            queue_summary = self.assistant.task_queue.summary()
            self.cowork_var.set((queue_summary + ("\n\n" + "\n".join(panels) if panels else "")).strip())
        self._append("assistant", result.reply)
        self.assistant.speak(result.reply)
        self._set_voice_state("speaking")
        self._focus_command_entry()

    def _toggle_wake_mode(self) -> None:
        if self.voice_enabled:
            self.voice_enabled = False
            self.stop_event.set()
            self.voice_var.set("Voice: stopped")
            self._set_voice_state("idle")
            self._append("system", "Continuous voice mode disabled.")
            return

        self.voice_enabled = True
        self.stop_event.clear()
        if self.assistant.config.require_wake_word:
            self.voice_var.set(f"Voice: listening for '{self.assistant.config.wake_word}'")
            self._set_voice_state("listening")
            self._append("system", f"Continuous voice mode enabled. Say '{self.assistant.config.wake_word}' before a command.")
        else:
            self.voice_var.set("Voice: continuous listening active")
            self._set_voice_state("listening")
            self._append("system", "Continuous voice mode enabled. Speak commands naturally and I will respond.")
        self.voice_thread = threading.Thread(target=self._wake_loop, daemon=True)
        self.voice_thread.start()

    def _wake_loop(self) -> None:
        wake_word = self.assistant.config.wake_word.lower()
        interrupt_phrases = {
            "stop",
            "stop speaking",
            "edith stop",
            "quiet",
            "be quiet",
            "cancel",
        }
        while not self.stop_event.is_set():
            try:
                if self.assistant.audio.is_speaking:
                    self._queue_voice_state("speaking")
                    heard = self.assistant.listen_for_interrupt().strip()
                    if heard in interrupt_phrases:
                        self.assistant.stop_speaking()
                        self.voice_queue.put(("system", "Speech interrupted."))
                        self._queue_voice_state("listening")
                    elif heard:
                        self.assistant.stop_speaking()
                        self.voice_queue.put(("system", f"Interrupted by: {heard}"))
                        self.voice_queue.put(("voice_command", heard))
                    else:
                        time.sleep(0.05)
                    continue
                self._queue_voice_state("listening")
                heard = self.assistant.listen_for_command().strip()
                if not heard:
                    continue
                lowered = heard.lower()
                if self.assistant.config.require_wake_word:
                    if wake_word not in lowered:
                        continue
                    cleaned = lowered.replace(wake_word, "", 1).strip()
                    if cleaned:
                        self.voice_queue.put(("system", f"Wake word detected from: {heard}"))
                        self.voice_queue.put(("voice_command", cleaned))
                    else:
                        self._queue_voice_state("processing")
                        command = self.assistant.listen_for_command()
                        if command:
                            self.voice_queue.put(("voice_command", command))
                        else:
                            self.voice_queue.put(("error", "Wake word heard, but no follow-up command was captured."))
                            self._queue_voice_state("listening")
                else:
                    self.voice_queue.put(("voice_command", heard))
            except Exception as exc:
                self.voice_queue.put(("error", f"Voice loop recovered from an error: {exc}"))
                self._queue_voice_state("idle")
                time.sleep(0.4)

    def _process_voice_queue(self) -> None:
        while not self.voice_queue.empty():
            try:
                kind, payload = self.voice_queue.get()
                if kind == "voice_command":
                    spoken = str(payload).strip()
                    if self._pending_voice_command:
                        if self._is_affirmative(spoken):
                            confirmed = self._pending_voice_command
                            self._pending_voice_command = None
                            self._pending_voice_confidence = None
                            self.voice_var.set("Voice: command confirmed")
                            self.input_var.set(confirmed)
                            self._submit()
                            continue
                        if self._is_negative(spoken):
                            self._pending_voice_command = None
                            self._pending_voice_confidence = None
                            self._append("system", "Voice command cancelled.")
                            continue
                    confidence = self.assistant.voice.estimate_confidence(spoken)
                    if confidence < self.assistant.config.voice_confidence_threshold:
                        self._pending_voice_command = spoken
                        self._pending_voice_confidence = confidence
                        self._append(
                            "system",
                            f"Low confidence ({confidence:.2f}) for '{spoken}'. Say yes to run or no to cancel.",
                        )
                        continue
                    self.voice_var.set("Voice: command received")
                    self.input_var.set(spoken)
                    self._submit()
                    if self.voice_enabled:
                        if self.assistant.config.require_wake_word:
                            self.voice_var.set(f"Voice: listening for '{self.assistant.config.wake_word}'")
                        else:
                            self.voice_var.set("Voice: continuous listening active")
                        if not self.assistant.audio.is_speaking and not self.processing:
                            self._set_voice_state("listening")
                elif kind == "command_result":
                    request_id, command, started_at, result, error = payload
                    if request_id in self._timed_out_requests:
                        self._timed_out_requests.discard(request_id)
                        continue
                    if self._active_request_id != request_id:
                        continue
                    self.processing = False
                    self._active_request_id = None
                    latency_ms = int((time.monotonic() - started_at) * 1000)
                    if error:
                        self._set_voice_state("idle")
                        self._append("error", error)
                        self.health_var.set("Runtime health: DEGRADED (last command failed)")
                        self._log_command_metric(command=command, status="error", latency_ms=latency_ms, error=error)
                    else:
                        self._apply_command_result(result)
                        self.health_var.set("Runtime health: READY")
                        self._log_command_metric(command=command, status="ok", latency_ms=latency_ms)
                    self.root.after(50, self._run_deferred_command)
                elif kind == "voice_state":
                    self._queued_voice_state = payload
                    voice_text = {
                        "idle": "Voice: idle",
                        "listening": "Voice: continuous listening active" if self.voice_enabled else "Voice: idle",
                        "processing": "Voice: processing command",
                        "speaking": "Voice: speaking",
                    }.get(payload, payload)
                    self.voice_var.set(voice_text)
                    self._set_voice_state(payload if payload in {"idle", "listening", "processing", "speaking"} else "idle")
                else:
                    self._append(kind, payload)
            except Exception as exc:
                self._append("error", f"UI queue recovered from an error: {exc}")
        self.root.after(80, self._process_voice_queue)

    def _queue_voice_state(self, state: str) -> None:
        if state == self._queued_voice_state:
            return
        self._queued_voice_state = state
        self.voice_queue.put(("voice_state", state))

    def _toggle_immersive_mode(self) -> None:
        if self.immersive_window is not None and self.immersive_window.winfo_exists():
            self.immersive_window.destroy()
            self.immersive_window = None
            self.immersive_canvas = None
            self.immersive_orb = None
            self.immersive_glow = None
            return

        window = tk.Toplevel(self.root)
        window.title("Edith Immersive Mode")
        window.geometry("520x520")
        window.configure(bg="#050b12")
        window.attributes("-topmost", True)
        self.immersive_window = window

        frame = tk.Frame(window, bg="#050b12")
        frame.pack(fill="both", expand=True)

        title = tk.Label(
            frame,
            text="EDITH",
            bg="#050b12",
            fg="#d9ffff",
            font=("Segoe UI Semibold", 26),
        )
        title.pack(pady=(24, 8))

        state = tk.Label(
            frame,
            textvariable=self.voice_state_label_var,
            bg="#050b12",
            fg="#7fd3da",
            font=("Segoe UI", 12),
        )
        state.pack()

        loading = tk.Label(
            frame,
            textvariable=self.loading_var,
            bg="#050b12",
            fg="#7fd3da",
            font=("Segoe UI", 11),
        )
        loading.pack(pady=(6, 0))

        canvas = tk.Canvas(
            frame,
            width=340,
            height=340,
            bg="#050b12",
            highlightthickness=0,
            relief="flat",
        )
        canvas.pack(pady=26)
        self.immersive_canvas = canvas
        self.immersive_glow = canvas.create_oval(40, 40, 300, 300, fill="#0f3248", outline="")
        self.immersive_orb = canvas.create_oval(95, 95, 245, 245, fill="#39d0ff", outline="")

        ttk.Button(frame, text="Close", style="Action.TButton", command=self._toggle_immersive_mode).pack(pady=(0, 24))
        window.protocol("WM_DELETE_WINDOW", self._toggle_immersive_mode)

    def _set_voice_state(self, state: str) -> None:
        self.voice_state = state
        label_map = {
            "idle": "Idle",
            "listening": "Listening",
            "processing": "Thinking",
            "speaking": "Speaking",
        }
        self.voice_state_label_var.set(f"State: {label_map.get(state, 'Idle')}")
        if state == "processing":
            self.loading_var.set("Processing")
        else:
            self.loading_var.set("")

    def _animate_orbs(self) -> None:
        self._animation_tick += 1
        pulse = (sin(self._animation_tick / 5.0) + 1.0) / 2.0
        state = self.voice_state

        if state == "listening":
            inner = 34 + int(pulse * 10)
            outer = 18 + int(pulse * 8)
            orb_color = "#3ee6ff"
            glow_color = "#114862"
        elif state == "speaking":
            inner = 30 + int(pulse * 18)
            outer = 12 + int(pulse * 14)
            orb_color = self._colors["success"]
            glow_color = "#1b5c58"
        elif state == "processing":
            inner = 28 + int((1 - pulse) * 14)
            outer = 10 + int(pulse * 16)
            orb_color = self._colors["warn"]
            glow_color = "#66511c"
            dots = "." * ((self._animation_tick // 4) % 4)
            self.loading_var.set(f"Processing{dots}")
        else:
            inner = 37
            outer = 20
            orb_color = self._colors["accent"]
            glow_color = "#12394f"
            if not self.processing:
                self.loading_var.set("")

        self._draw_orb(self.voice_canvas, self.voice_glow, self.voice_orb, 75, outer, inner, glow_color, orb_color)
        self._draw_orb(self.immersive_canvas, self.immersive_glow, self.immersive_orb, 170, outer * 2, inner * 2, glow_color, orb_color)

        if self.voice_enabled and not self.assistant.audio.is_speaking and not self.processing and self.voice_state != "listening":
            self._set_voice_state("listening")
        if not self.voice_enabled and not self.assistant.audio.is_speaking and not self.processing and self.voice_state != "idle":
            self._set_voice_state("idle")

        self.root.after(80, self._animate_orbs)

    def _draw_orb(
        self,
        canvas: tk.Canvas | None,
        glow_item,
        orb_item,
        center: int,
        glow_radius: int,
        orb_radius: int,
        glow_color: str,
        orb_color: str,
    ) -> None:
        if canvas is None or glow_item is None or orb_item is None:
            return
        canvas.coords(
            glow_item,
            center - glow_radius,
            center - glow_radius,
            center + glow_radius,
            center + glow_radius,
        )
        canvas.coords(
            orb_item,
            center - orb_radius,
            center - orb_radius,
            center + orb_radius,
            center + orb_radius,
        )
        canvas.itemconfigure(glow_item, fill=glow_color)
        canvas.itemconfigure(orb_item, fill=orb_color)

    def _is_affirmative(self, text: str) -> bool:
        lowered = text.lower().strip()
        return lowered in {"yes", "yeah", "yep", "do it", "go ahead", "confirm"}

    def _is_negative(self, text: str) -> bool:
        lowered = text.lower().strip()
        return lowered in {"no", "nope", "cancel", "stop", "not that"}

    def _refresh_runtime_health(self) -> None:
        try:
            model_ready, detail = self.assistant.agent.runtime_status()
            if model_ready:
                self.health_var.set(f"Runtime health: READY ({detail})")
            else:
                self.health_var.set(f"Runtime health: DEGRADED ({detail})")
        except Exception:
            self.health_var.set("Runtime health: DEGRADED (health probe failed)")
        self.root.after(2500, self._refresh_runtime_health)

    def _log_command_metric(self, command: str, status: str, latency_ms: int, error: str = "") -> None:
        try:
            self._telemetry_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "timestamp": datetime.now().isoformat(),
                "status": status,
                "latency_ms": latency_ms,
                "command": command,
            }
            if error:
                payload["error"] = error
            with self._telemetry_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        except Exception:
            pass

    def _shutdown(self) -> None:
        self.voice_enabled = False
        self.stop_event.set()
        self.assistant.stop_speaking()
        if self.immersive_window is not None and self.immersive_window.winfo_exists():
            self.immersive_window.destroy()
        self.root.destroy()

    def _focus_command_entry(self) -> None:
        if self.command_entry is None:
            return
        try:
            self.command_entry.focus_set()
            self.command_entry.icursor("end")
        except Exception:
            pass

    def _history_up(self, event=None):
        if not self.command_history:
            return "break"
        if self.command_history_index <= 0:
            self.command_history_index = 0
        else:
            self.command_history_index -= 1
        self.input_var.set(self.command_history[self.command_history_index])
        self._focus_command_entry()
        return "break"

    def _history_down(self, event=None):
        if not self.command_history:
            return "break"
        if self.command_history_index >= len(self.command_history) - 1:
            self.command_history_index = len(self.command_history)
            self.input_var.set("")
        else:
            self.command_history_index += 1
            self.input_var.set(self.command_history[self.command_history_index])
        self._focus_command_entry()
        return "break"

    def _run_deferred_command(self) -> None:
        if self.processing or not self._deferred_command:
            return
        command = self._deferred_command
        self._deferred_command = None
        self.input_var.set(command)
        self._submit()
