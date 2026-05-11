import tkinter as tk
from tkinter import ttk
from collections import deque
from edith_app.services.logging_service import register_ui_log_callback

class TerminalWindow:
    def __init__(self, parent_root: tk.Tk):
        self.toplevel = tk.Toplevel(parent_root)
        self.toplevel.title("EDITH NEURAL TERMINAL")
        self.toplevel.geometry("800x400")
        
        # Style to match the glassmorphism HUD
        self.toplevel.configure(bg="#050B14")
        self.toplevel.attributes("-alpha", 0.96)
        
        # Header
        header = tk.Frame(self.toplevel, bg="#0A1526", height=30)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        tk.Label(header, text="SYSTEM COGNITION STREAM", bg="#0A1526", fg="#00FFCC", font=("Consolas", 10, "bold")).pack(side="left", padx=10)
        
        # Log Text Area
        self.text_area = tk.Text(
            self.toplevel, 
            bg="#03080F", 
            fg="#B0C4DE", 
            font=("Consolas", 9),
            insertbackground="white",
            relief="flat",
            padx=10, 
            pady=10,
            state="disabled"
        )
        self.text_area.pack(fill="both", expand=True)
        
        # Sub-Queue for thread-safe rendering
        self._log_queue = deque()
        
        # Color Tags for Log Levels
        self.text_area.tag_configure("INFO", foreground="#00FFCC")      # Cyan/Green
        self.text_area.tag_configure("WARNING", foreground="#FFD700")   # Yellow
        self.text_area.tag_configure("ERROR", foreground="#FF4444")     # Red
        self.text_area.tag_configure("DEBUG", foreground="#607B96")     # Grey
        
        # Register the Live Hook
        register_ui_log_callback(self._on_log)
        
        self._process_queue()
        
    def _on_log(self, level: str, message: str) -> None:
        self._log_queue.append((level, message))
        
    def _process_queue(self) -> None:
        if self._log_queue:
            self.text_area.configure(state="normal")
            while self._log_queue:
                level, msg = self._log_queue.popleft()
                self.text_area.insert("end", msg + "\n", level)
            self.text_area.see("end")
            self.text_area.configure(state="disabled")
            
        # Recursive UI Loop
        self.toplevel.after(100, self._process_queue)
        
    def show(self) -> None:
        self.toplevel.deiconify()
        self.toplevel.lift()
        self.toplevel.focus_force()

    def hide(self) -> None:
        self.toplevel.withdraw()
