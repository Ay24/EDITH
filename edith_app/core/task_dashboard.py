"""
task_dashboard.py  —  Standalone Tkinter dashboard window for the EDITH task system.
Opened as a Toplevel so it doesn't block the main console.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from edith_app.core.task_engine import TaskEngine, Task

COLORS = {
    "bg":      "#050b12",
    "panel":   "#0a1826",
    "card":    "#0d2338",
    "surface": "#05121e",
    "entry":   "#102a40",
    "line":    "#1e4d73",
    "text":    "#dcf9ff",
    "muted":   "#7ba8b2",
    "accent":  "#00e5ff",
    "success": "#00ffa3",
    "warn":    "#ffea00",
    "error":   "#ff5c5c",
    "high":    "#ff5c5c",
    "medium":  "#ffea00",
    "low":     "#00ffa3",
}


class TaskDashboard:
    """Full-featured task dashboard as a floating Toplevel window."""

    def __init__(self, parent: tk.Tk, engine: "TaskEngine", on_speak: Callable[[str], None] | None = None) -> None:
        self._engine = engine
        self._on_speak = on_speak
        self._win = tk.Toplevel(parent)
        self._win.title("EDITH  —  Task Intelligence Dashboard")
        self._win.geometry("860x620")
        self._win.minsize(760, 500)
        self._win.configure(bg=COLORS["bg"])
        self._win.resizable(True, True)
        self._filter_var = tk.StringVar(value="all")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refresh_list())
        self._selected_task_id: str | None = None
        self._build()
        self._refresh_list()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Header
        hdr = tk.Frame(self._win, bg=COLORS["panel"], pady=12, padx=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚡ Task Intelligence Dashboard",
                 bg=COLORS["panel"], fg=COLORS["accent"],
                 font=("Segoe UI Semibold", 16)).pack(side="left")
        tk.Button(hdr, text="+ New Task", bg=COLORS["line"], fg=COLORS["text"],
                  font=("Segoe UI Semibold", 10), relief="flat", padx=10, pady=5,
                  command=self._open_create_dialog).pack(side="right", padx=(0, 8))
        tk.Button(hdr, text="↻ Refresh", bg=COLORS["line"], fg=COLORS["muted"],
                  font=("Segoe UI", 10), relief="flat", padx=8, pady=5,
                  command=self._refresh_list).pack(side="right", padx=(0, 6))

        # Filter bar
        filter_frame = tk.Frame(self._win, bg=COLORS["panel"], pady=6, padx=16)
        filter_frame.pack(fill="x")
        filters = [("All", "all"), ("Pending", "pending"), ("In Progress", "in_progress"),
                   ("Completed", "completed"), ("Overdue", "overdue"), ("High 🔴", "high")]
        for label, value in filters:
            btn = tk.Button(
                filter_frame, text=label,
                bg=COLORS["line"] if value != self._filter_var.get() else COLORS["accent"],
                fg=COLORS["text"],
                font=("Segoe UI", 9), relief="flat", padx=10, pady=4,
                command=lambda v=value: self._set_filter(v),
            )
            btn.pack(side="left", padx=(0, 4))
        # Search
        tk.Label(filter_frame, text="Search:", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 9)).pack(side="left", padx=(16, 4))
        tk.Entry(filter_frame, textvariable=self._search_var,
                 bg=COLORS["entry"], fg=COLORS["text"], insertbackground=COLORS["text"],
                 relief="flat", font=("Segoe UI", 10), width=22).pack(side="left")

        # Body
        body = tk.Frame(self._win, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=8)
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        # Left: task list
        left = tk.Frame(body, bg=COLORS["panel"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(left, text="TASKS", bg=COLORS["panel"], fg=COLORS["accent"],
                 font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=10, pady=(8, 4))

        list_frame = tk.Frame(left, bg=COLORS["surface"])
        list_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self._task_list = tk.Listbox(
            list_frame,
            bg=COLORS["surface"], fg=COLORS["text"],
            selectbackground=COLORS["line"], selectforeground=COLORS["accent"],
            font=("Consolas", 10), relief="flat", borderwidth=0,
            activestyle="none",
        )
        self._task_list.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self._task_list.yview)
        scrollbar.pack(side="right", fill="y")
        self._task_list.configure(yscrollcommand=scrollbar.set)
        self._task_list.bind("<<ListboxSelect>>", self._on_task_select)

        # Stats bar
        self._stats_var = tk.StringVar(value="")
        tk.Label(left, textvariable=self._stats_var,
                 bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(0, 6))

        # Right: detail panel
        right = tk.Frame(body, bg=COLORS["card"])
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        tk.Label(right, text="TASK DETAIL", bg=COLORS["card"], fg=COLORS["accent"],
                 font=("Segoe UI Semibold", 10)).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        self._detail_text = tk.Text(
            right, bg=COLORS["surface"], fg=COLORS["text"],
            font=("Segoe UI", 10), relief="flat", wrap="word",
            padx=12, pady=10, state="disabled",
        )
        self._detail_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 6))

        # Actions
        actions = tk.Frame(right, bg=COLORS["card"])
        actions.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 6))
        for label, cmd, color in [
            ("▶ Start", self._action_start, COLORS["accent"]),
            ("✅ Complete", self._action_complete, COLORS["success"]),
            ("🗒 Add Note", self._action_note, COLORS["warn"]),
            ("🗑 Delete", self._action_delete, COLORS["error"]),
        ]:
            tk.Button(actions, text=label, bg=color, fg=COLORS["bg"],
                      font=("Segoe UI Semibold", 9), relief="flat", padx=8, pady=5,
                      command=cmd).pack(side="left", padx=(0, 6))

        # Progress timeline at bottom
        summary_frame = tk.Frame(self._win, bg=COLORS["panel"], height=32)
        summary_frame.pack(fill="x", side="bottom")
        self._summary_var = tk.StringVar(value="")
        tk.Label(summary_frame, textvariable=self._summary_var,
                 bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(side="left", padx=12, pady=6)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _get_filtered_tasks(self) -> list["Task"]:
        f = self._filter_var.get()
        q = self._search_var.get().lower().strip()
        if f == "all":
            tasks = self._engine.all()
        elif f == "overdue":
            tasks = self._engine.overdue()
        elif f == "high":
            tasks = self._engine.by_priority("high")
        else:
            tasks = self._engine.by_status(f)  # type: ignore[arg-type]
        if q:
            tasks = [t for t in tasks if q in t.title.lower() or q in t.description.lower()]
        return tasks

    def _refresh_list(self) -> None:
        self._task_list.delete(0, "end")
        tasks = self._get_filtered_tasks()
        self._filtered_ids = [t.id for t in tasks]
        for t in tasks:
            pe = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(t.priority, "")
            se = {"pending": "⏳", "in_progress": "⚙️", "completed": "✅", "cancelled": "❌"}.get(t.status, "")
            overdue_marker = " ⚠️" if t.is_overdue() else ""
            self._task_list.insert("end", f"  {se}{pe} {t.title[:44]}{overdue_marker}")
        # Color completed items
        for i, t in enumerate(tasks):
            if t.status == "completed":
                self._task_list.itemconfig(i, fg=COLORS["success"])
            elif t.is_overdue():
                self._task_list.itemconfig(i, fg=COLORS["error"])

        pending   = self._engine.pending_count()
        completed = self._engine.completed_count()
        total     = len(self._engine.all())
        self._stats_var.set(f"  {total} total  |  {pending} pending  |  {completed} done")
        self._summary_var.set(f"Next: {self._engine.next_task().title if self._engine.next_task() else 'All clear!'}")

    def _on_task_select(self, event=None) -> None:
        sel = self._task_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._filtered_ids):
            return
        task_id = self._filtered_ids[idx]
        task    = self._engine.get(task_id)
        if not task:
            return
        self._selected_task_id = task_id
        self._show_detail(task)

    def _show_detail(self, task: "Task") -> None:
        self._detail_text.configure(state="normal")
        self._detail_text.delete("1.0", "end")
        pe = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(task.priority, "")
        se = {"pending": "⏳", "in_progress": "⚙️", "completed": "✅", "cancelled": "❌"}.get(task.status, "")
        lines = [
            f"ID:         {task.id}",
            f"Title:      {task.title}",
            f"Status:     {se} {task.status.replace('_',' ').title()}",
            f"Priority:   {pe} {task.priority.title()}",
            f"Created:    {task.created_at[:16]}",
        ]
        if task.due_date:
            overdue = " ⚠️ OVERDUE" if task.is_overdue() else ""
            lines.append(f"Due:        {task.due_date}{overdue}")
        if task.completed_at:
            lines.append(f"Completed:  {task.completed_at[:16]}")
        lines.append("")
        if task.description:
            lines += ["Description:", f"  {task.description}", ""]
        if task.context:
            lines += ["Context:", f"  {task.context}", ""]
        if task.notes:
            lines += ["Notes:", task.notes, ""]
        if task.tags:
            lines.append(f"Tags: {', '.join(task.tags)}")
        self._detail_text.insert("end", "\n".join(lines))
        self._detail_text.configure(state="disabled")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _action_start(self) -> None:
        if self._selected_task_id:
            t = self._engine.update_status(self._selected_task_id, "in_progress")
            if t:
                self._refresh_list()
                self._show_detail(t)

    def _action_complete(self) -> None:
        if self._selected_task_id:
            t = self._engine.update_status(self._selected_task_id, "completed")
            if t:
                self._refresh_list()
                self._show_detail(t)
                if self._on_speak:
                    self._on_speak(f"Task '{t.title}' marked complete.")

    def _action_delete(self) -> None:
        if self._selected_task_id:
            task = self._engine.get(self._selected_task_id)
            if task and messagebox.askyesno("Confirm Delete", f"Delete '{task.title}'?", parent=self._win):
                self._engine.delete(self._selected_task_id)
                self._selected_task_id = None
                self._detail_text.configure(state="normal")
                self._detail_text.delete("1.0", "end")
                self._detail_text.configure(state="disabled")
                self._refresh_list()

    def _action_note(self) -> None:
        if not self._selected_task_id:
            return
        task = self._engine.get(self._selected_task_id)
        if not task:
            return
        dialog = tk.Toplevel(self._win)
        dialog.title("Add Note")
        dialog.geometry("420x180")
        dialog.configure(bg=COLORS["bg"])
        dialog.grab_set()
        tk.Label(dialog, text=f"Add note to: {task.title[:50]}", bg=COLORS["bg"],
                 fg=COLORS["accent"], font=("Segoe UI", 10)).pack(anchor="w", padx=12, pady=(12, 0))
        note_var = tk.StringVar()
        tk.Entry(dialog, textvariable=note_var, bg=COLORS["entry"], fg=COLORS["text"],
                 font=("Segoe UI", 11), relief="flat", insertbackground=COLORS["text"]).pack(
            fill="x", padx=12, pady=10, ipady=8)
        def save():
            note = note_var.get().strip()
            if note:
                t = self._engine.add_note(self._selected_task_id, note)
                if t:
                    self._show_detail(t)
            dialog.destroy()
        tk.Button(dialog, text="Save Note", command=save, bg=COLORS["accent"], fg=COLORS["bg"],
                  font=("Segoe UI Semibold", 10), relief="flat", padx=14, pady=6).pack()

    def _set_filter(self, value: str) -> None:
        self._filter_var.set(value)
        self._refresh_list()

    def _open_create_dialog(self) -> None:
        dialog = tk.Toplevel(self._win)
        dialog.title("New Task")
        dialog.geometry("480x360")
        dialog.configure(bg=COLORS["bg"])
        dialog.grab_set()

        fields: dict[str, tk.Variable] = {
            "Title":       tk.StringVar(),
            "Description": tk.StringVar(),
            "Priority":    tk.StringVar(value="medium"),
            "Due Date":    tk.StringVar(value=""),
        }
        for label, var in fields.items():
            tk.Label(dialog, text=label, bg=COLORS["bg"], fg=COLORS["accent"],
                     font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=14, pady=(10, 0))
            if label == "Priority":
                frame = tk.Frame(dialog, bg=COLORS["bg"])
                frame.pack(anchor="w", padx=14)
                for val in ("high", "medium", "low"):
                    tk.Radiobutton(frame, text=val.title(), variable=var, value=val,
                                   bg=COLORS["bg"], fg=COLORS["text"],
                                   selectcolor=COLORS["card"], font=("Segoe UI", 10),
                                   activebackground=COLORS["bg"]).pack(side="left", padx=6)
            else:
                tk.Entry(dialog, textvariable=var, bg=COLORS["entry"], fg=COLORS["text"],
                         relief="flat", font=("Segoe UI", 10),
                         insertbackground=COLORS["text"]).pack(fill="x", padx=14, ipady=6)

        def create():
            title = fields["Title"].get().strip()
            if not title:
                return
            self._engine.create(
                title=title,
                description=fields["Description"].get().strip(),
                priority=fields["Priority"].get(),  # type: ignore[arg-type]
                due_date=fields["Due Date"].get().strip() or None,
            )
            self._refresh_list()
            dialog.destroy()

        tk.Button(dialog, text="Create Task", command=create, bg=COLORS["accent"], fg=COLORS["bg"],
                  font=("Segoe UI Semibold", 11), relief="flat", padx=16, pady=8).pack(pady=14)

    def bring_to_front(self) -> None:
        self._win.lift()
        self._win.focus_force()
        self._refresh_list()
