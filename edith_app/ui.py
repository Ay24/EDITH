from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from math import sin
from tkinter import ttk

from edith_app.assistant import EdithAssistant


class EdithDesktopUI:
    def __init__(self, assistant: EdithAssistant) -> None:
        self.assistant = assistant
        self.root = tk.Tk()
        self.root.title("Edith Neural Console")
        self.root.geometry("1200x780")
        self.root.minsize(980, 680)
        self.root.configure(bg="#08101b")

        self.input_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.mode_var = tk.StringVar()
        self.quick_var = tk.StringVar(value="Try: think with me about building a startup")
        self.entity_var = tk.StringVar(value="Detected entities will appear here.")
        self.voice_var = tk.StringVar(value="Voice mode offline")
        self.chat_log: tk.Text | None = None
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

        self._build_theme()
        self._build_layout()
        self._initialize()
        self.root.after(80, self._process_voice_queue)
        self.root.after(80, self._animate_orbs)
        self.root.protocol("WM_DELETE_WINDOW", self._shutdown)

    def run(self) -> None:
        self.root.mainloop()

    def _build_theme(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("Panel.TFrame", background="#07121b")
        style.configure("Card.TFrame", background="#0e2230")
        style.configure("Hero.TFrame", background="#0b2a3d")
        style.configure("Glass.TFrame", background="#133649")
        style.configure("Title.TLabel", background="#0b2a3d", foreground="#dffcff", font=("Segoe UI Semibold", 22))
        style.configure("Sub.TLabel", background="#0b2a3d", foreground="#7fd3da", font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background="#0e2230", foreground="#dffcff", font=("Segoe UI Semibold", 11))
        style.configure("CardBody.TLabel", background="#0e2230", foreground="#8fdde3", font=("Segoe UI", 10))
        style.configure("Action.TButton", font=("Segoe UI Semibold", 10), padding=8)
        style.configure("Status.TLabel", background="#133649", foreground="#d9ffff", font=("Segoe UI", 10))

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

        hero = ttk.Frame(main, style="Hero.TFrame", padding=20)
        hero.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        hero.columnconfigure(0, weight=1)
        hero.columnconfigure(1, weight=0)
        ttk.Label(hero, text="Edith Neural Console", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            hero,
            text="Always-listening voice, multi-model local AI, system control, and media automation in one desktop surface.",
            style="Sub.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(hero, text="Toggle Voice Mode", style="Action.TButton", command=self._toggle_wake_mode).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )
        ttk.Button(hero, text="Immersive Mode", style="Action.TButton", command=self._toggle_immersive_mode).grid(
            row=0, column=2, rowspan=2, sticky="e", padx=(10, 0)
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
            bg="#06131d",
            fg="#d9ffff",
            insertbackground="#d9ffff",
            relief="flat",
            wrap="word",
            font=("Consolas", 11),
            padx=14,
            pady=14,
        )
        self.chat_log.grid(row=1, column=0, sticky="nsew", pady=(10, 12))

        input_row = ttk.Frame(chat_card, style="Card.TFrame")
        input_row.grid(row=2, column=0, sticky="ew")
        input_row.columnconfigure(0, weight=1)

        entry = tk.Entry(
            input_row,
            textvariable=self.input_var,
            bg="#0f2430",
            fg="#d9ffff",
            insertbackground="#d9ffff",
            relief="flat",
            font=("Segoe UI", 11),
        )
        entry.grid(row=0, column=0, sticky="ew", ipady=11)
        entry.bind("<Return>", lambda event: self._submit())

        ttk.Button(input_row, text="Execute", style="Action.TButton", command=self._submit).grid(row=0, column=1, padx=(10, 0))
        ttk.Button(input_row, text="Listen", style="Action.TButton", command=self._listen_once).grid(row=0, column=2, padx=(10, 0))
        ttk.Button(input_row, text="Silence", style="Action.TButton", command=self.assistant.stop_speaking).grid(row=0, column=3, padx=(10, 0))

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
        ttk.Label(footer, textvariable=self.mode_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(footer, textvariable=self.voice_var, style="Status.TLabel").grid(row=0, column=2, sticky="e")

    def _build_sidebar(self, sidebar: ttk.Frame) -> None:
        intro = ttk.Frame(sidebar, style="Hero.TFrame", padding=16)
        intro.grid(row=0, column=0, sticky="ew", padx=14, pady=14)
        ttk.Label(intro, text="Mission Profile", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            intro,
            text="Routines, continuous listening, and multi-model thinking for a more Jarvis-like flow.",
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
        ttk.Label(snapshot, text="Multi-model routing, Windows utilities, and automation routines.", style="CardBody.TLabel").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )

        quick = ttk.Frame(parent, style="Card.TFrame", padding=14)
        quick.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        quick.columnconfigure(0, weight=1)
        ttk.Label(quick, text="Quick Prompt", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(quick, textvariable=self.quick_var, style="CardBody.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))

        nlp = ttk.Frame(parent, style="Card.TFrame", padding=14)
        nlp.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        nlp.columnconfigure(0, weight=1)
        ttk.Label(nlp, text="NLP Signals", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(nlp, textvariable=self.entity_var, style="CardBody.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))

        voice = ttk.Frame(parent, style="Card.TFrame", padding=14)
        voice.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        voice.columnconfigure(1, weight=1)
        ttk.Label(voice, text="Voice Presence", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.voice_canvas = tk.Canvas(
            voice,
            width=150,
            height=150,
            bg="#0e2230",
            highlightthickness=0,
            relief="flat",
        )
        self.voice_canvas.grid(row=1, column=0, padx=(0, 14), pady=(10, 0))
        self.voice_glow = self.voice_canvas.create_oval(20, 20, 130, 130, fill="#12394f", outline="")
        self.voice_orb = self.voice_canvas.create_oval(38, 38, 112, 112, fill="#39d0ff", outline="")
        ttk.Label(voice, textvariable=self.voice_state_label_var, style="CardBody.TLabel").grid(row=1, column=1, sticky="nw", pady=(18, 0))
        ttk.Label(voice, textvariable=self.loading_var, style="CardBody.TLabel").grid(row=2, column=1, sticky="nw", pady=(8, 0))

        ideas = ttk.Frame(parent, style="Card.TFrame", padding=14)
        ideas.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ideas.columnconfigure(0, weight=1)
        ttk.Label(ideas, text="Suggested Commands", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            ideas,
            text=(
                "start focus mode\n"
                "plan a daily automation workflow\n"
                "brainstorm a better desktop assistant\n"
                "think with me about launching a product\n"
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

    def _initialize(self) -> None:
        snapshot = self.assistant.snapshot()
        self.mode_var.set(
            f"Mode: {snapshot.mode} | Multi-model agent {'ready' if snapshot.ai_enabled else 'offline'}"
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
        self._append("system", "You can ask me to plan, brainstorm, search files, control apps, and run desktop routines.")
        if self.assistant.config.auto_listen:
            self.root.after(400, self._toggle_wake_mode)

    def _append(self, source: str, text: str) -> None:
        if self.chat_log is None:
            return
        label = {"system": "SYSTEM", "user": "YOU", "assistant": "EDITH", "error": "ERROR"}.get(source, source.upper())
        self.chat_log.insert("end", f"[{label}] {text}\n\n")
        self.chat_log.see("end")

    def _preset(self, command: str) -> None:
        self.input_var.set(command)
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
        self.assistant.stop_speaking()
        self.input_var.set("")
        self.quick_var.set(f"Last command: {command}")
        self._append("user", command)
        self.processing = True
        self._set_voice_state("processing")

        try:
            result = self.assistant.handle(command)
        except Exception as exc:
            self.processing = False
            self._set_voice_state("idle")
            self._append("error", str(exc))
            return

        entities = result.metadata.get("entities", "No named entities detected.")
        self.entity_var.set(entities)
        self._append("assistant", result.reply)
        self.assistant.speak(result.reply)
        self.processing = False
        self._set_voice_state("speaking")

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

    def _process_voice_queue(self) -> None:
        while not self.voice_queue.empty():
            kind, payload = self.voice_queue.get()
            if kind == "voice_command":
                self.voice_var.set("Voice: command received")
                self.input_var.set(payload)
                self._submit()
                if self.voice_enabled:
                    if self.assistant.config.require_wake_word:
                        self.voice_var.set(f"Voice: listening for '{self.assistant.config.wake_word}'")
                    else:
                        self.voice_var.set("Voice: continuous listening active")
                    if not self.assistant.audio.is_speaking:
                        self._set_voice_state("listening")
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
            orb_color = "#64f7d0"
            glow_color = "#1b5c58"
        elif state == "processing":
            inner = 28 + int((1 - pulse) * 14)
            outer = 10 + int(pulse * 16)
            orb_color = "#ffd166"
            glow_color = "#66511c"
            dots = "." * ((self._animation_tick // 4) % 4)
            self.loading_var.set(f"Processing{dots}")
        else:
            inner = 37
            outer = 20
            orb_color = "#39d0ff"
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

    def _shutdown(self) -> None:
        self.voice_enabled = False
        self.stop_event.set()
        self.assistant.stop_speaking()
        if self.immersive_window is not None and self.immersive_window.winfo_exists():
            self.immersive_window.destroy()
        self.root.destroy()
