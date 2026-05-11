import tkinter as tk
from tkinter import ttk
from edith_app.core.task_queue import TaskQueue

class TaskDashboardUI:
    def __init__(self, root: tk.Tk, task_queue: TaskQueue) -> None:
        self.root = root
        self.task_queue = task_queue
        self.window = tk.Toplevel(self.root)
        self.window.title("EDITH Task Dashboard")
        
        # Center window and set size
        w, h = 450, 600
        sw, sh = self.window.winfo_screenwidth(), self.window.winfo_screenheight()
        # Offset slightly from the main HUD
        self.window.geometry(f"{w}x{h}+{(sw-w)//2 + 650}+{(sh-h)//2 - 100}")
        
        self._colors = {
            "bg": "#050b12",
            "panel": "#0a1826",
            "card": "#0d2338",
            "entry": "#102a40",
            "text": "#dcf9ff",
            "muted": "#7ba8b2",
            "accent": "#00e5ff",
            "success": "#00ffa3",
        }
        self.window.configure(bg=self._colors["bg"])
        self.window.attributes("-alpha", 0.95)
        
        # Header
        header_frame = tk.Frame(self.window, bg=self._colors["panel"], height=60)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)
        tk.Label(
            header_frame, text="NEURAL TASK QUEUE",
            fg=self._colors["accent"], bg=self._colors["panel"],
            font=("Consolas Bold", 14)
        ).pack(side="left", padx=20, pady=15)
        
        tk.Button(
            header_frame, text="CLEAR DONE", command=self._clear_done,
            bg=self._colors["card"], fg=self._colors["muted"],
            activebackground=self._colors["entry"], activeforeground=self._colors["text"],
            bd=0, font=("Consolas", 10), cursor="hand2"
        ).pack(side="right", padx=20, pady=15)
        
        # Task List Canvas
        self.canvas = tk.Canvas(self.window, bg=self._colors["bg"], highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.window, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg=self._colors["bg"])
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw", width=430)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="top", fill="both", expand=True, padx=10, pady=10)
        self.scrollbar.pack(side="right", fill="y")
        
        # Add Task Bar
        add_frame = tk.Frame(self.window, bg=self._colors["panel"], height=60)
        add_frame.pack(side="bottom", fill="x")
        add_frame.pack_propagate(False)
        
        self.add_entry = tk.Entry(
            add_frame, bg=self._colors["entry"], fg=self._colors["text"],
            insertbackground=self._colors["accent"], font=("Consolas", 12),
            bd=0, highlightthickness=1, highlightbackground=self._colors["card"], highlightcolor=self._colors["accent"]
        )
        self.add_entry.pack(side="left", fill="both", expand=True, padx=(20, 10), pady=15)
        self.add_entry.bind("<Return>", lambda e: self._add_task())
        
        tk.Button(
            add_frame, text="ADD", command=self._add_task,
            bg=self._colors["accent"], fg="#000000",
            activebackground=self._colors["success"], activeforeground="#000000",
            bd=0, font=("Consolas Bold", 11), cursor="hand2"
        ).pack(side="right", padx=(0, 20), pady=15)
        
        self.refresh()

    def refresh(self) -> None:
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
            
        tasks = self.task_queue.list()
        if not tasks:
            tk.Label(
                self.scrollable_frame, text="No tasks currently in queue.",
                fg=self._colors["muted"], bg=self._colors["bg"], font=("Consolas", 11)
            ).pack(pady=30)
            return
            
        for task in reversed(tasks):
            self._build_task_row(task)
            
    def _build_task_row(self, task) -> None:
        frame = tk.Frame(self.scrollable_frame, bg=self._colors["card"])
        frame.pack(fill="x", pady=5)
        
        is_done = task.status == "done"
        color = self._colors["muted"] if is_done else self._colors["text"]
        
        chk_var = tk.BooleanVar(value=is_done)
        chk = tk.Checkbutton(
            frame, variable=chk_var, bg=self._colors["card"], activebackground=self._colors["card"],
            selectcolor=self._colors["entry"], cursor="hand2",
            command=lambda t=task.title, v=chk_var: self._toggle_task(t, v)
        )
        chk.pack(side="left", padx=10, pady=10)
        
        lbl = tk.Label(
            frame, text=task.title, fg=color, bg=self._colors["card"], font=("Consolas", 11)
        )
        lbl.pack(side="left", pady=10, fill="x", expand=True, anchor="w")
        
        if is_done:
            lbl.configure(font=("Consolas", 11, "overstrike"))
            
    def _toggle_task(self, title: str, var: tk.BooleanVar) -> None:
        if var.get():
            self.task_queue.complete(title)
        else:
            # Reopen task
            for t in self.task_queue._tasks:
                if t.title == title:
                    t.status = "pending"
            self.task_queue._save()
        self.refresh()
        
    def _clear_done(self) -> None:
        self.task_queue.clear_done()
        self.refresh()
        
    def _add_task(self) -> None:
        title = self.add_entry.get().strip()
        if title:
            self.task_queue.add(title)
            self.add_entry.delete(0, tk.END)
            self.refresh()

    def is_open(self) -> bool:
        return self.window.winfo_exists()
