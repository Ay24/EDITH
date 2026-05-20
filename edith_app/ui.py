from __future__ import annotations

import json
import queue
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from math import sin, cos, pi
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable

from edith_app.assistant import EdithAssistant
from edith_app.services.logging_service import get_logger
from edith_app.models import CommandResult

class EdithDesktopUI:
    def __init__(self, assistant: EdithAssistant, root: tk.Tk | None = None) -> None:
        self.assistant = assistant
        self.logger = get_logger("edith.ui", assistant.config.runtime_log_path)
        
        # Use centralized root passed from app.py
        self.root = root if root else tk.Tk()
        self.root.title("EDITH ORBIT — Local Voice Agent")
        
        # Frameless Transparent HUD
        self.root.overrideredirect(True)
        self._target_alpha = max(0.94, min(1.0, assistant.config.ui_alpha))
        self.root.attributes("-alpha", 0.0)
        self.root.attributes("-topmost", True)
        
        # Center HUD on screen
        w, h = 1260, 820
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self._base_x = (sw - w) // 2
        self._base_y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{self._base_x}+{self._base_y + 18}")
        self.root.minsize(980, 680)
        
        self._colors = {
            "bg": "#000001",
            "panel": "#0A0612",
            "card": "#120A1E",
            "hero": "#1A0F2E",
            "glass": "#2A1848",
            "surface": "#0E0818",
            "entry": "#1E1234",
            "line": "#4A2D7A",
            "text": "#F5EEFF",
            "muted": "#B8A0D8",
            "accent": "#C77DFF",
            "accent_soft": "#E8B4FF",
            "success": "#5FFFB0",
            "warn": "#FFD166",
            "error": "#FF6B8A",
        }
        self.root.configure(bg=self._colors["bg"])
        self.root.wm_attributes("-transparentcolor", self._colors["bg"])

        # State Variables
        self.input_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.health_var = tk.StringVar(value="Warming up...")
        self.mode_var = tk.StringVar()
        self.situation_var = tk.StringVar(value="All systems nominal.")
        self.quick_var = tk.StringVar(value="EDITH is ready.")
        self.entity_var = tk.StringVar(value="No active scan.")
        self.cowork_var = tk.StringVar(value="No active tasks.")
        self.preflight_var = tk.StringVar(value="Diagnostics nominal.")
        self.voice_var = tk.StringVar(value="Voice offline")
        
        self.chat_log: tk.Text | None = None
        self.command_entry: tk.Entry | None = None
        self.voice_enabled = False
        self.voice_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.voice_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.processing = False
        self._command_idle = threading.Event()
        self._command_idle.set()
        self.immersive_window: tk.Toplevel | None = None
        self.voice_state = "idle"
        self.voice_state_label_var = tk.StringVar(value="ORBIT · IDLE")
        self.partial_var = tk.StringVar(value="")
        self.loading_var = tk.StringVar(value="")
        self._waveform_levels: deque[float] = deque(maxlen=36)
        self._stream_token_buffer: deque[str] = deque()
        self._stream_flush_scheduled = False
        self._max_chat_lines = max(200, assistant.config.ui_max_chat_lines)
        
        # 3D Graphics State
        self._animation_tick = 0
        self._rotation_angle = 0.0
        self.voice_canvas: tk.Canvas | None = None
        self._ring_steps = 40

        # Motion System State
        self._ui_motion_frame_ms = 16  # ~60 FPS
        self._intro_started_at = time.perf_counter()
        self._intro_complete = False
        self._hover_states: dict[tk.Widget, dict[str, Any]] = {}
        self._motion_last_tick = time.perf_counter()
        self._action_buttons: list[tk.Button] = []
        self._execute_button: tk.Button | None = None
        
        # Drag Logic State
        self._drag_data = {"x": 0, "y": 0}
        self._drag_active = False
        self._drag_last_screen_x = 0.0
        self._drag_last_screen_y = 0.0
        self._drag_last_t = time.perf_counter()
        self._window_px = float(self._base_x)
        self._window_py = float(self._base_y + 18)
        self._window_vx = 0.0
        self._window_vy = 0.0
        self._window_bounds_margin = 8
        self._window_soft_overscroll = 64.0
        self._drag_region_widgets: list[tk.Widget] = []
        self._after_ids: set[str] = set()
        self._closed = False

        self._build_theme()
        self._build_layout()
        self._initialize()
        
        # Background loops — voice queue polled at 16ms in ultra-latency mode
        poll_ms = max(8, int(getattr(assistant.config, "ui_voice_poll_ms", 16)))
        self._voice_poll_ms = poll_ms
        self._schedule(poll_ms, self._process_voice_queue)
        self._schedule(self._ui_motion_frame_ms, self._animate_sphere)
        self._schedule(self._ui_motion_frame_ms, self._motion_tick)
        
        # Restore Taskbar presence for frameless window
        self._schedule(520, self._set_appwindow)
        self.root.protocol("WM_DELETE_WINDOW", self._shutdown)
        
        # Smart Hotkey Integration
        try:
            import keyboard
            keyboard.add_hotkey('ctrl+shift+space', lambda: self.root.after(0, self._toggle_wake_mode))
            self.logger.info("Global hotkey ctrl+shift+space registered for voice wake.")
        except ImportError:
            self.logger.warning("Keyboard module not installed; global hotkeys disabled.")
        except Exception as e:
            self.logger.warning(f"Could not bind global hotkey: {e}")

        # Final Reveal (root was withdrawn in app.py)
        self.root.deiconify()
        self.root.focus_force()

    def run(self) -> None:
        self.root.mainloop()

    def _schedule(self, delay_ms: int, callback: Callable[[], None]) -> str | None:
        if self._closed:
            return None
        after_id: str | None = None

        def _run() -> None:
            if after_id is not None:
                self._after_ids.discard(after_id)
            if not self._closed:
                callback()

        after_id = self.root.after(delay_ms, _run)
        self._after_ids.add(after_id)
        return after_id

    def _cancel_after_jobs(self) -> None:
        for after_id in list(self._after_ids):
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
            self._after_ids.discard(after_id)

    # ── Frameless Chassis Logic ───────────────────────────────────────────────

    def _set_appwindow(self) -> None:
        """Forces the borderless window to appear in the Windows Taskbar and Alt+Tab."""
        try:
            from ctypes import windll
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            hwnd = windll.user32.GetParent(self.root.winfo_id())
            style = windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = style & ~WS_EX_TOOLWINDOW
            style = style | WS_EX_APPWINDOW
            windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            # Re-assert visibility to flush OS change
            self.root.withdraw()
            self.root.deiconify()
        except Exception as e:
            self.logger.warning(f"Could not force taskbar visibility: {e}")

    def _start_drag(self, event) -> None:
        self._drag_active = True
        self._drag_data["x"] = event.x_root - self.root.winfo_x()
        self._drag_data["y"] = event.y_root - self.root.winfo_y()
        self._drag_last_screen_x = float(event.x_root)
        self._drag_last_screen_y = float(event.y_root)
        self._drag_last_t = time.perf_counter()
        self._window_vx = 0.0
        self._window_vy = 0.0

    def _on_drag(self, event) -> None:
        if not self._drag_active:
            return
        now = time.perf_counter()
        dt = max(0.001, now - self._drag_last_t)
        new_x = float(event.x_root - self._drag_data["x"])
        new_y = float(event.y_root - self._drag_data["y"])

        self._window_vx = (float(event.x_root) - self._drag_last_screen_x) / dt
        self._window_vy = (float(event.y_root) - self._drag_last_screen_y) / dt
        self._drag_last_screen_x = float(event.x_root)
        self._drag_last_screen_y = float(event.y_root)
        self._drag_last_t = now

        self._window_px = new_x
        self._window_py = new_y
        self._apply_window_geometry(int(new_x), int(new_y))

    def _end_drag(self, _event) -> None:
        self._drag_active = False

    def _shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.voice_enabled = False
        self.stop_event.set()
        self._cancel_after_jobs()
        try:
            self.assistant.stop_voice_session()
        except Exception:
            pass
        self.root.destroy()

    # ── Theme & Layout ────────────────────────────────────────────────────────

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
        style.configure("Title.TLabel", background=self._colors["hero"], foreground=self._colors["text"], font=("Segoe UI Semibold", 22))
        style.configure("Sub.TLabel", background=self._colors["hero"], foreground=self._colors["muted"], font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=self._colors["card"], foreground=self._colors["accent"], font=("Segoe UI Semibold", 11))
        style.configure("CardBody.TLabel", background=self._colors["card"], foreground=self._colors["text"], font=("Segoe UI", 10))
        style.configure("Action.TButton", font=("Segoe UI Semibold", 10), padding=9)
        style.map(
            "Action.TButton",
            background=[("active", self._colors["accent"]), ("!active", self._colors["glass"])],
            foreground=[("active", self._colors["bg"]), ("!active", self._colors["text"])],
        )
        style.configure("Status.TLabel", background=self._colors["glass"], foreground=self._colors["accent_soft"], font=("Segoe UI", 10))
        style.configure("Meta.TLabel", background=self._colors["card"], foreground=self._colors["success"], font=("Segoe UI Semibold", 9))

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self.root, style="Panel.TFrame", width=320)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)

        main = ttk.Frame(self.root, style="Panel.TFrame")
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        # 1. Hero HUD
        hero = ttk.Frame(main, style="Hero.TFrame", padding=22)
        hero.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        hero.columnconfigure(0, weight=1)
        self._hero_frame = hero
        
        # Custom Tactical Controls [X] [^] [⛶]
        actions = tk.Frame(hero, bg=self._colors["hero"])
        actions.place(relx=1.0, rely=0.0, anchor="ne", x=10, y=-10)
        
        close_btn = tk.Button(
            actions,
            text="X",
            bg=self._colors["error"],
            fg="white",
            font=("Segoe UI Bold", 10),
            relief="flat",
            padx=10,
            pady=5,
            activebackground="#ff0000",
            command=self._shutdown,
        )
        close_btn.pack(side="right", padx=2)
        self._bind_smooth_hover(close_btn, self._colors["error"], "#f87171")
        
        self._saved_geom = None
        def toggle_fullscreen():
            if self._saved_geom is None:
                self._saved_geom = self.root.winfo_geometry()
                sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
                self.root.geometry(f"{sw}x{sh}+0+0")
                fullscreen_btn.config(bg=self._colors["success"])
            else:
                self.root.geometry(self._saved_geom)
                self._saved_geom = None
                fullscreen_btn.config(bg=self._colors["glass"])
        
        fullscreen_btn = tk.Button(actions, text="[]", bg=self._colors["glass"], fg="white",
                           font=("Segoe UI", 10), relief="flat", padx=8, pady=5,
                           command=toggle_fullscreen)
        fullscreen_btn.pack(side="right", padx=2)
        self._bind_smooth_hover(fullscreen_btn, self._colors["glass"], self._colors["accent"])

        def toggle_terminal():
            if getattr(self, "_terminal_window", None) is None:
                from edith_app.core.ui_terminal import TerminalWindow
                self._terminal_window = TerminalWindow(self.root)
            else:
                if self._terminal_window.toplevel.winfo_viewable():
                    self._terminal_window.hide()
                    term_btn.config(bg=self._colors["glass"])
                else:
                    self._terminal_window.show()
                    term_btn.config(bg=self._colors["success"])

        term_btn = tk.Button(actions, text=">_", bg=self._colors["glass"], fg="white",
                           font=("Consolas Bold", 10), relief="flat", padx=8, pady=5,
                           command=toggle_terminal)
        term_btn.pack(side="right", padx=2)
        self._bind_smooth_hover(term_btn, self._colors["glass"], self._colors["accent"])

        def toggle_top():
            is_top = self.root.attributes("-topmost")
            self.root.attributes("-topmost", not is_top)
            pin_btn.config(bg=self._colors["success"] if not is_top else self._colors["glass"])
        
        pin_btn = tk.Button(actions, text="PIN", bg=self._colors["glass"], fg="white",
                           font=("Segoe UI", 10), relief="flat", padx=8, pady=5,
                           command=toggle_top)
        pin_btn.pack(side="right", padx=2)
        self._bind_smooth_hover(pin_btn, self._colors["glass"], self._colors["accent"])


        ttk.Label(hero, text="EDITH ORBIT", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        hero_subtitle = ttk.Label(
            hero,
            text="Speak to automate everything  ·  100% local  ·  Ultra-low latency",
            style="Sub.TLabel",
        )
        hero_subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))
        
        btn_bar = tk.Frame(hero, bg=self._colors["hero"])
        btn_bar.grid(row=2, column=0, sticky="w", pady=(18, 0))
        self._action_buttons = [
            self._create_primary_button(btn_bar, "Talk", self._toggle_wake_mode),
            self._create_primary_button(btn_bar, "Tasks", self._open_task_dashboard),
            self._create_primary_button(btn_bar, "Cowork", lambda: self._preset("cowork sync")),
        ]
        self._action_buttons[0].pack(side="left", padx=(0, 10))
        self._action_buttons[1].pack(side="left", padx=(0, 10))
        self._action_buttons[2].pack(side="left")

        # Drag gestures should work from the full hero surface (excluding action buttons).
        self._bind_drag_region(hero)
        self._bind_drag_region(actions)
        self._bind_drag_region(btn_bar)
        self._bind_drag_region(hero_subtitle)

        # 2. Main Body (Chat + Cards)
        body = ttk.Frame(main, style="Panel.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        chat_card = ttk.Frame(body, style="Card.TFrame", padding=16)
        chat_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        chat_card.columnconfigure(0, weight=1)
        chat_card.rowconfigure(1, weight=1)
        # Depth Layering via border
        chat_card.configure(borderwidth=1, relief="ridge")
        
        ttk.Label(chat_card, text="Live transcript", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")

        self.chat_log = tk.Text(
            chat_card,
            bg=self._colors["surface"],
            fg=self._colors["text"],
            insertbackground=self._colors["text"],
            relief="flat",
            wrap="word",
            font=("Segoe UI", 12),
            padx=16, pady=16,
            spacing1=4, spacing2=2, spacing3=10,
            selectbackground="#1e4d73",
            selectforeground=self._colors["accent"],
        )
        self.chat_log.grid(row=1, column=0, sticky="nsew", pady=(10, 12))
        self.chat_log.configure(state="disabled")
        # Configure tags once here — not on every message
        self.chat_log.tag_configure("user_hdr", foreground=self._colors["accent"], font=("Segoe UI Bold", 12))
        self.chat_log.tag_configure("edith_hdr", foreground=self._colors["success"], font=("Segoe UI Bold", 12))
        self.chat_log.tag_configure("sys_hdr", foreground=self._colors["warn"], font=("Segoe UI Bold", 11))
        self.chat_log.tag_configure("ts", foreground=self._colors["muted"], font=("Segoe UI", 9))
        self.chat_log.tag_configure("body", foreground=self._colors["text"], font=("Segoe UI", 12))

        input_frame = ttk.Frame(chat_card, style="Card.TFrame")
        input_frame.grid(row=2, column=0, sticky="ew")
        input_frame.columnconfigure(0, weight=1)

        self.command_entry = tk.Entry(
            input_frame,
            textvariable=self.input_var,
            bg=self._colors["entry"],
            fg=self._colors["text"],
            insertbackground=self._colors["accent"],
            relief="flat",
            font=("Segoe UI", 13),
            highlightthickness=2,
            highlightbackground=self._colors["line"],
            highlightcolor=self._colors["accent"],
        )
        self.command_entry.grid(row=0, column=0, sticky="ew", ipady=14)
        self.command_entry.bind("<Return>", lambda event: self._submit())
        
        self._execute_button = self._create_primary_button(input_frame, "Execute", self._submit)
        self._execute_button.grid(row=0, column=1, padx=(12, 0))

        # 3. Right Panel (Perspective Cards)
        right = ttk.Frame(body, style="Panel.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self._build_sidebar(sidebar)
        self._build_cards(right)

        # 4. Footer Status
        footer = ttk.Frame(main, style="Glass.TFrame", padding=12)
        footer.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.health_var, style="Status.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _create_primary_button(self, parent: tk.Widget, text: str, command: Callable[[], None]) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=self._colors["glass"],
            fg=self._colors["text"],
            activebackground=self._colors["accent"],
            activeforeground=self._colors["bg"],
            relief="flat",
            font=("Segoe UI Semibold", 10),
            padx=12,
            pady=8,
            borderwidth=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self._bind_smooth_hover(button, self._colors["glass"], self._colors["accent"])
        return button

    def _bind_drag_region(self, widget: tk.Widget) -> None:
        if widget in self._drag_region_widgets:
            return
        widget.bind("<Button-1>", self._start_drag, add="+")
        widget.bind("<B1-Motion>", self._on_drag, add="+")
        widget.bind("<ButtonRelease-1>", self._end_drag, add="+")
        self._drag_region_widgets.append(widget)

    def _bind_smooth_hover(self, widget: tk.Widget, base_color: str, hover_color: str) -> None:
        self._hover_states[widget] = {
            "value": 0.0,
            "target": 0.0,
            "base": base_color,
            "hover": hover_color,
        }

        def _enter(_: Any) -> None:
            state = self._hover_states.get(widget)
            if state is not None:
                state["target"] = 1.0

        def _leave(_: Any) -> None:
            state = self._hover_states.get(widget)
            if state is not None:
                state["target"] = 0.0

        widget.bind("<Enter>", _enter, add="+")
        widget.bind("<Leave>", _leave, add="+")

    def _motion_tick(self) -> None:
        if self._closed:
            return
        now = time.perf_counter()
        dt = min(0.06, max(0.001, now - self._motion_last_tick))
        self._motion_last_tick = now

        self._tick_intro_motion(now)
        self._tick_hover_motion(dt)
        self._tick_entry_glow(now)
        self._tick_window_physics(dt)

        self._schedule(self._ui_motion_frame_ms, self._motion_tick)

    def _tick_intro_motion(self, now: float) -> None:
        if self._intro_complete:
            return
        t = (now - self._intro_started_at) / 0.45
        if t >= 1.0:
            self._intro_complete = True
            try:
                self.root.attributes("-alpha", self._target_alpha)
                w = self.root.winfo_width()
                h = self.root.winfo_height()
                self.root.geometry(f"{w}x{h}+{self._base_x}+{self._base_y}")
            except Exception:
                pass
            return

        eased = 1.0 - pow(1.0 - max(0.0, t), 3.0)
        alpha = self._target_alpha * eased
        y = self._base_y + int((1.0 - eased) * 18.0)
        try:
            w = max(980, self.root.winfo_width())
            h = max(680, self.root.winfo_height())
            self.root.attributes("-alpha", alpha)
            self.root.geometry(f"{w}x{h}+{self._base_x}+{y}")
        except Exception:
            pass

    def _tick_hover_motion(self, dt: float) -> None:
        stiffness = min(1.0, dt * 10.5)
        dead: list[tk.Widget] = []
        for widget, state in self._hover_states.items():
            try:
                value = float(state["value"])
                target = float(state["target"])
                value += (target - value) * stiffness
                state["value"] = value
                color = self._blend_color(str(state["base"]), str(state["hover"]), value)
                widget.configure(bg=color, activebackground=color)
            except tk.TclError:
                dead.append(widget)
            except Exception:
                continue
        for widget in dead:
            self._hover_states.pop(widget, None)

    def _tick_entry_glow(self, now: float) -> None:
        if not self.command_entry:
            return
            
        if not hasattr(self, '_current_glow_color'):
            self._current_glow_color = self._colors["line"]

        pulse = (sin(now * 3.0) + 1.0) * 0.5
        target_color = self._colors["line"]
        intensity = 0.0

        if self.voice_state == "listening":
            target_color = self._colors["accent_soft"]
            intensity = 0.55 + (0.35 * pulse)
        elif self.voice_state == "thinking":
            target_color = self._colors["warn"]
            intensity = 0.58 + (0.34 * pulse)
        elif self.voice_state == "speaking":
            target_color = self._colors["success"]
            intensity = 0.55 + (0.35 * pulse)

        ideal_color = self._blend_color(self._colors["line"], target_color, intensity) if intensity > 0 else self._colors["line"]
        self._current_glow_color = self._blend_color(self._current_glow_color, ideal_color, 0.15)

        try:
            self.command_entry.configure(highlightbackground=self._current_glow_color, highlightcolor=self._current_glow_color, insertbackground=self._colors["text"])
        except Exception:
            pass

    def _blend_color(self, c1: str, c2: str, t: float) -> str:
        t = max(0.0, min(1.0, t))
        r1, g1, b1 = self._hex_to_rgb(c1)
        r2, g2, b2 = self._hex_to_rgb(c2)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _hex_to_rgb(self, color: str) -> tuple[int, int, int]:
        raw = color.strip()
        if raw.startswith("#"):
            raw = raw[1:]
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        if len(raw) != 6:
            return (0, 0, 0)
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)

    def _tick_window_physics(self, dt: float) -> None:
        if self._drag_active:
            return

        self._window_px = float(self.root.winfo_x())
        self._window_py = float(self.root.winfo_y())

        moving = abs(self._window_vx) > 2.0 or abs(self._window_vy) > 2.0
        if moving:
            self._window_px += self._window_vx * dt
            self._window_py += self._window_vy * dt
            damping = pow(0.09, dt)
            self._window_vx *= damping
            self._window_vy *= damping

        min_x, max_x, min_y, max_y = self._window_bounds()

        over_x = 0.0
        over_y = 0.0
        if self._window_px < min_x:
            over_x = self._window_px - min_x
        elif self._window_px > max_x:
            over_x = self._window_px - max_x
        if self._window_py < min_y:
            over_y = self._window_py - min_y
        elif self._window_py > max_y:
            over_y = self._window_py - max_y

        if over_x != 0.0 or over_y != 0.0:
            spring_k = 26.0
            self._window_vx += (-over_x * spring_k) * dt
            self._window_vy += (-over_y * spring_k) * dt
            edge_damp = pow(0.3, dt)
            self._window_vx *= edge_damp
            self._window_vy *= edge_damp

        self._window_px = max(min_x - self._window_soft_overscroll, min(max_x + self._window_soft_overscroll, self._window_px))
        self._window_py = max(min_y - self._window_soft_overscroll, min(max_y + self._window_soft_overscroll, self._window_py))
        self._apply_window_geometry(int(round(self._window_px)), int(round(self._window_py)))

        # Subtle kinetic alpha response for premium motion feel.
        if self._intro_complete:
            speed = abs(self._window_vx) + abs(self._window_vy)
            dip = min(0.035, speed / 90000.0)
            target = max(0.93, self._target_alpha - dip)
            try:
                current_alpha = float(self.root.attributes("-alpha"))
                eased_alpha = current_alpha + (target - current_alpha) * min(1.0, dt * 12.0)
                self.root.attributes("-alpha", eased_alpha)
            except Exception:
                pass

    def _window_bounds(self) -> tuple[float, float, float, float]:
        sw = float(self.root.winfo_screenwidth())
        sh = float(self.root.winfo_screenheight())
        ww = float(max(980, self.root.winfo_width()))
        wh = float(max(680, self.root.winfo_height()))
        m = float(self._window_bounds_margin)
        min_x = m
        min_y = m
        max_x = max(m, sw - ww - m)
        max_y = max(m, sh - wh - m)
        return min_x, max_x, min_y, max_y

    def _apply_window_geometry(self, x: int, y: int) -> None:
        try:
            self.root.geometry(f"+{x}+{y}")
        except Exception:
            return

    def _build_sidebar(self, sidebar: ttk.Frame) -> None:
        # Isometric 3D Sphere Housing
        presence = ttk.Frame(sidebar, style="Card.TFrame", padding=18)
        presence.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        presence.configure(borderwidth=1, relief="ridge")
        ttk.Label(presence, text="ORBIT Core", style="CardTitle.TLabel").pack(anchor="w")
        
        self.voice_canvas = tk.Canvas(
            presence, width=280, height=240, bg=self._colors["card"],
            highlightthickness=0, borderwidth=0
        )
        self.voice_canvas.pack(pady=10)
        
        tk.Label(presence, textvariable=self.voice_state_label_var, bg=self._colors["card"],
                 fg=self._colors["accent_soft"], font=("Segoe UI Bold", 10)).pack()
        tk.Label(
            presence, textvariable=self.partial_var, bg=self._colors["card"],
            fg=self._colors["muted"], font=("Segoe UI", 9), wraplength=250, justify="center",
        ).pack(pady=(4, 0))
        
        # Intelligence Context
        mission = ttk.Frame(sidebar, style="Card.TFrame", padding=18)
        mission.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        mission.configure(borderwidth=1, relief="ridge")
        ttk.Label(mission, text="Cognitive Context", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(mission, textvariable=self.situation_var, style="CardBody.TLabel", 
                  wraplength=260, justify="left").pack(pady=10)
        tk.Label(mission, textvariable=self.mode_var, bg=self._colors["card"], 
                  fg=self._colors["success"], font=("Segoe UI Bold", 9)).pack(anchor="w")

    def _build_cards(self, parent: ttk.Frame) -> None:
        row = 0
        for title, var in [
            ("Insights", self.quick_var),
            ("Agent pipeline", self.cowork_var),
            ("System Health", self.entity_var)
        ]:
            card = ttk.Frame(parent, style="Card.TFrame", padding=14)
            card.grid(row=row, column=0, sticky="nsew", pady=(0, 10))
            card.configure(borderwidth=1, relief="ridge")
            ttk.Label(card, text=title, style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(card, textvariable=var, style="CardBody.TLabel", wraplength=310, justify="left").grid(row=1, column=0, sticky="w", pady=(6, 0))
            row += 1

    # ── Isometric 3D Engine ───────────────────────────────────────────────────

    def _animate_sphere(self) -> None:
        """Renders a rotating 3D Neural Sphere using isometric projection."""
        if not self.voice_canvas: return
        self.voice_canvas.delete("sphere")
        
        # State-driven dynamics with smooth interpolation
        if not hasattr(self, '_current_speed_mult'):
            self._current_speed_mult = 1.0
            
        target_mult = 1.0
        if self.processing: target_mult = 2.8
        elif self.voice_state == "listening": target_mult = 4.5
        
        self._current_speed_mult += (target_mult - self._current_speed_mult) * 0.1
        
        self._rotation_angle += 0.024 * self._current_speed_mult
        cx, cy = 140, 120
        radius = 85
        
        angle = self._rotation_angle
        
        # 3 Orthogonal Rings (X, Y, Z axes rotation simulation)
        self._draw_isometric_ring(cx, cy, radius, angle, 0.2, self._colors["accent"], 3)
        self._draw_isometric_ring(cx, cy, radius, angle + pi/2, 1.1, self._colors["accent_soft"], 2)
        self._draw_isometric_ring(cx, cy, radius, angle * 0.7, 0.6, self._colors["success"], 1)
        self._draw_waveform_bars(cx, cy + 72)

        # Central Core (Pulsing)
        pulse = (sin(time.time() * 4) + 1) * 6
        self.voice_canvas.create_oval(cx-18-pulse, cy-18-pulse, cx+18+pulse, cy+18+pulse, 
                                     fill=self._colors["accent"], stipple="gray25", tags="sphere")
        
        self._schedule(self._ui_motion_frame_ms, self._animate_sphere)

    def _draw_waveform_bars(self, cx: int, base_y: int) -> None:
        if not self.voice_canvas:
            return
        levels = list(self._waveform_levels)
        if not levels:
            return
        bar_w = 5
        gap = 2
        total_w = len(levels) * (bar_w + gap)
        start_x = cx - total_w // 2
        for i, level in enumerate(levels):
            h = int(min(42, max(3, level * 48)))
            x0 = start_x + i * (bar_w + gap)
            color = self._colors["accent"] if self.voice_state == "listening" else self._colors["accent_soft"]
            self.voice_canvas.create_rectangle(
                x0, base_y - h, x0 + bar_w, base_y,
                fill=color, outline="", tags="sphere",
            )

    def _draw_isometric_ring(self, cx, cy, radius, rotation, tilt, color, width) -> None:
        points = []
        steps = 28
        for i in range(steps + 1):
            phi = (i / steps) * 2 * pi
            # 2nd order isometric rotation
            x = radius * cos(phi)
            y = radius * sin(phi)
            
            # Spin + Tilt projection
            x_rot = x * cos(rotation)
            z_rot = x * sin(rotation)
            
            y_final = y * cos(tilt) - z_rot * sin(tilt)
            x_final = x_rot
            
            points.append(cx + x_final)
            points.append(cy + y_final)
            
        # Draw high-fidelity line with shadow trail
        self.voice_canvas.create_line(points, fill=color, width=width, smooth=True, tags="sphere", capstyle="round")

    # ── Data & Interaction ────────────────────────────────────────────────────

    def _initialize(self) -> None:
        self.assistant.set_suggestion_callback(self._on_suggestion)
        self.assistant.set_ui_callback(self._update_ui_state)
        self.assistant.set_stream_callback(self._on_stream_token)
        self._refresh_status()
        if self.assistant.config.open_task_dashboard_on_start:
            self.root.after(500, self._open_task_dashboard)
        if self.assistant.config.auto_listen:
            self.root.after(900, self._toggle_wake_mode)

    def _update_ui_state(self, key: str, value: Any) -> None:
        if key == "processing":
            self.processing = bool(value)
            self._set_voice_state("thinking" if value else ("listening" if self.voice_enabled else "idle"))
        elif key == "voice_state":
            self._set_voice_state(str(value))
        elif key == "wake":
            self.partial_var.set("Wake detected — listening…")
            self._set_voice_state("listening")

    def _on_suggestion(self, text: str) -> None:
        self.quick_var.set(text)

    def _on_stream_token(self, token: str) -> None:
        self.root.after(0, lambda: self._handle_stream_token(token))

    def _handle_stream_token(self, token: str) -> None:
        if not self.chat_log: return
        self._stream_token_buffer.append(token)
        if not self._stream_flush_scheduled:
            self._stream_flush_scheduled = True
            self.root.after(self.assistant.config.ui_stream_flush_ms, self._flush_stream_buffer)

    def _flush_stream_buffer(self) -> None:
        self._stream_flush_scheduled = False
        if not self.chat_log or not self._stream_token_buffer: return

        self.chat_log.configure(state="normal")
        if not getattr(self, "_is_streaming_reply", False):
            self._is_streaming_reply = True
            # Write header with timestamp matching _append_log format
            ts = datetime.now().strftime("%H:%M")
            self.chat_log.insert("end", f"[{ts}] ", "ts")
            self.chat_log.insert("end", "EDITH", "edith_hdr")
            self.chat_log.insert("end", "  ", "body")

        text_chunk = "".join(self._stream_token_buffer)
        self._stream_token_buffer.clear()

        self.chat_log.insert("end", text_chunk, "body")
        self.chat_log.see("end")
        self.chat_log.configure(state="disabled")


    def _submit(self) -> None:
        if self.processing:
            return
        cmd = self.input_var.get().strip()
        if not cmd: return
        self.input_var.set("")
        self._append_log("USER", cmd)
        self.processing = True
        self._command_idle.clear()
        self._set_voice_state("thinking")
        self._is_streaming_reply = False
        threading.Thread(target=self._execute, args=(cmd,), daemon=True).start()

    def _execute(self, cmd: str) -> None:
        try:
            res = self.assistant.handle(cmd)
            self.root.after(0, lambda: self._handle_result(res))
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._handle_execution_error(e))

    def _handle_execution_error(self, exc: Exception) -> None:
        self.processing = False
        self._command_idle.set()
        self._set_voice_state("listening" if self.voice_enabled else "idle")
        self._append_log("ERROR", f"Command failed: {exc}")

    def _handle_result(self, res: CommandResult | None) -> None:
        self.processing = False
        self._command_idle.set()
        if res is None:
            return

        # If reply was already streamed token-by-token to the chat log,
        # skip _append_log entirely to prevent the double-message.
        # The metadata sentinel is set synchronously BEFORE this callback fires,
        # so this check is race-free unlike checking _is_streaming_reply.
        already_streamed = res.metadata.get("streamed_reply") == "1"

        if already_streamed:
            # Just ensure the streamed text ends with a newline
            if self.chat_log:
                try:
                    self.chat_log.configure(state="normal")
                    # Only add newline if the last char isn't already one
                    last = self.chat_log.get("end-2c", "end-1c")
                    if last and last != "\n":
                        self.chat_log.insert("end", "\n")
                    self.chat_log.configure(state="disabled")
                except Exception:
                    pass
            self._is_streaming_reply = False
        else:
            self._append_log("EDITH", res.reply)
        
        # Check if the audio was already streamed 
        if res.metadata.get("streamed_audio") != "1":
            self._set_voice_state("speaking")
            self.assistant.speak(res.reply)
            self._schedule(1800, lambda: self._set_voice_state("listening" if self.voice_enabled else "idle"))
            
        self.entity_var.set(res.metadata.get("entities", "Neural scan complete."))
        self.cowork_var.set(self.assistant.task_manager.cowork_summary())

    def _append_log(self, author: str, text: str) -> None:
        if not self.chat_log: return
        self.chat_log.configure(state="normal")
        ts = datetime.now().strftime("%H:%M")
        if author == "USER":
            self.chat_log.insert("end", f"[{ts}] ", "ts")
            self.chat_log.insert("end", "YOU  ", "user_hdr")
        elif author == "EDITH":
            self.chat_log.insert("end", f"[{ts}] ", "ts")
            self.chat_log.insert("end", "EDITH", "edith_hdr")
        else:
            self.chat_log.insert("end", f"[{ts}] ", "ts")
            self.chat_log.insert("end", f"{author} ", "sys_hdr")
        self.chat_log.insert("end", f"  {text}\n", "body")
        self.chat_log.see("end")
        self.chat_log.configure(state="disabled")
        # Trim log to max lines
        line_count = int(self.chat_log.index("end-1c").split(".")[0])
        if line_count > self._max_chat_lines:
            self.chat_log.configure(state="normal")
            self.chat_log.delete("1.0", f"{line_count - self._max_chat_lines}.0")
            self.chat_log.configure(state="disabled")

    def _preset(self, cmd: str) -> None:
        self.input_var.set(cmd)
        self._submit()

    def _toggle_wake_mode(self) -> None:
        self.voice_enabled = not self.voice_enabled
        if self.voice_enabled:
            self.assistant.voice.on_partial = lambda t: self.voice_queue.put(("partial", t))
            self.assistant.voice.on_energy = lambda e: self.voice_queue.put(("energy", str(e)))
            self.assistant.start_voice_session()
            self.stop_event.clear()
            self._set_voice_state("listening")
            self.voice_var.set("Voice Listening")
            if self.voice_thread is None or not self.voice_thread.is_alive():
                self.voice_thread = threading.Thread(target=self._voice_loop, daemon=True)
                self.voice_thread.start()
        else:
            self.stop_event.set()
            self.assistant.stop_voice_session()
            self._set_voice_state("idle")
            self.voice_var.set("Voice Offline")

    def _open_task_dashboard(self) -> None:
        self.assistant.open_task_dashboard(self.root)

    def _refresh_status(self) -> None:
        try:
            import psutil
            cpu = int(psutil.cpu_percent(interval=None))
            ram = psutil.virtual_memory()
            ram_pct = int(ram.percent)
            health = f"CPU {cpu}%  ·  RAM {ram_pct}%"
        except Exception:
            health = "System metrics unavailable"
        next_task = self.assistant.task_manager.next_task()
        if next_task is not None:
            self.health_var.set(f"{health}  ·  Next: {next_task.title}")
            self.cowork_var.set(self.assistant.task_manager.cowork_summary())
        else:
            self.health_var.set(f"{health}  ·  All tasks clear")
        self.status_var.set(f"EDITH Core  ·  Active  ·  {datetime.now().strftime('%H:%M:%S')}")
        self._schedule(5000, self._refresh_status)

    def _process_voice_queue(self) -> None:
        try:
            while not self.voice_queue.empty():
                qtype, val = self.voice_queue.get_nowait()
                if qtype == "transcript":
                    self.input_var.set(val)
                elif qtype == "voice_command":
                    if not self.processing:
                        self.input_var.set(val)
                        self._submit()
                elif qtype == "voice_state":
                    self._set_voice_state(val)
                elif qtype == "partial":
                    self.partial_var.set(val[:120])
                elif qtype == "energy":
                    try:
                        self._waveform_levels.append(float(val))
                    except ValueError:
                        pass
                elif qtype == "system":
                    self._append_log("SYSTEM", str(val))
        except queue.Empty: pass
        self._schedule(self._voice_poll_ms, self._process_voice_queue)

    def _focus_command_entry(self) -> None:
        if self.command_entry: self.command_entry.focus_set()

    def _voice_loop(self) -> None:
        wake_word = self.assistant.config.wake_word.lower()
        while self.voice_enabled and not self.stop_event.is_set() and not self._closed:
            try:
                if not self._command_idle.wait(timeout=0.02):
                    continue
                
                is_speaking = self.assistant.audio.is_speaking
                if not is_speaking:
                    self.voice_queue.put(("voice_state", "listening"))
                    heard = self.assistant.listen_for_command().strip()
                else:
                    # Allow interrupt while speaking
                    heard = self.assistant.listen_for_interrupt().strip()
                    
                if not heard:
                    continue
                    
                lowered = heard.lower()
                
                if is_speaking:
                    # Check for explicit stop commands or wake word to interrupt
                    interrupt_words = {"stop", "cancel", "quiet", "shh", "edith", "jarvis", "friday", "stop talking"}
                    if any(w == lowered or lowered.startswith(w + " ") for w in interrupt_words):
                        self.assistant.audio.stop()
                        self.voice_queue.put(("system", "Voice interrupted by user."))
                        # If it was just "stop", don't process it as a new command
                        if lowered in {"stop", "cancel", "quiet", "shh", "stop talking"}:
                            continue
                    else:
                        # For other phrases during speech, we might want to ignore them to prevent self-interruption 
                        # from speaker echo, unless confidence is extremely high (handled by voice service).
                        # We'll let it pass through to the normal logic.
                        self.assistant.audio.stop()
                
                if (
                    self.assistant.config.require_wake_word
                    and not is_speaking
                    and not getattr(self.assistant.voice, "_command_armed", True)
                ):
                    if wake_word not in lowered and not any(
                        w in lowered for w in self.assistant.config.wake_keyword_list()
                    ):
                        continue
                    for kw in self.assistant.config.wake_keyword_list():
                        if kw in lowered:
                            heard = lowered.replace(kw, "", 1).strip()
                            break
                    else:
                        heard = lowered.replace(wake_word, "", 1).strip()
                    if not heard:
                        continue
                        
                confidence = self.assistant.voice.estimate_confidence(heard)
                if confidence < self.assistant.config.voice_confidence_threshold:
                    if not heard.lower().startswith(("message ", "send message", "text ", "call ", "video call ", "open ", "play ", "set ")):
                        self.voice_queue.put(("system", f"Low-confidence voice input ignored: {heard}"))
                        continue
                        
                self.partial_var.set("")
                self.voice_queue.put(("transcript", heard))
                self.voice_queue.put(("voice_command", heard))
                if (
                    self.assistant.config.wake_engine_enabled
                    and self.assistant.config.always_listen_wake
                ):
                    self.assistant.voice.disarm_command_window()
            except Exception as exc:
                self.voice_queue.put(("system", f"Voice loop recovered: {exc}"))
                time.sleep(0.12)

    def _set_voice_state(self, state: str) -> None:
        state = state.lower().strip()
        if state == "processing":
            state = "thinking"
        valid = {"idle", "listening", "thinking", "speaking"}
        if state not in valid:
            state = "idle"
        self.voice_state = state
        label = {
            "idle": "IDLE",
            "listening": "LISTENING",
            "thinking": "THINKING",
            "speaking": "SPEAKING",
        }[state]
        self.voice_state_label_var.set(f"ORBIT · {label}")
        self.loading_var.set("Thinking..." if state == "thinking" else ("Speaking..." if state == "speaking" else ""))

    def _toggle_immersive_mode(self) -> None: pass
