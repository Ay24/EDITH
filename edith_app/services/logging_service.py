from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_UI_CALLBACKS = []

class UICallbackHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            for cb in _UI_CALLBACKS:
                cb(record.levelname, msg)
        except Exception:
            self.handleError(record)

def register_ui_log_callback(callback):
    """Register a UI function to receive live log streams."""
    if callback not in _UI_CALLBACKS:
        _UI_CALLBACKS.append(callback)

_LOGGER_CACHE: dict[str, logging.Logger] = {}
_ui_handler = None

def get_logger(name: str, log_path: str) -> logging.Logger:
    global _ui_handler
    cached = _LOGGER_CACHE.get(name)
    if cached is not None:
        return cached

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = RotatingFileHandler(
            filename=str(path),
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        # Add Console output so terminal shows exactly what EDITH is doing
        import sys
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        if _ui_handler is None:
            _ui_handler = UICallbackHandler()
            _ui_handler.setFormatter(formatter)
            _ui_handler.setLevel(logging.INFO)
        logger.addHandler(_ui_handler)

    _LOGGER_CACHE[name] = logger
    return logger

class RunLogger:
    def __init__(self, runs_dir: str = "edith_runs"):
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        # Use a daily log file
        import datetime
        today = datetime.date.today().isoformat()
        self.log_file = self.runs_dir / f"run_{today}.md"
        
        # Write header if new
        if not self.log_file.exists():
            with open(self.log_file, "w", encoding="utf-8") as f:
                f.write(f"# EDITH Run Log - {today}\n\n")

    def log_interaction(self, user_input: str, assistant_reply: str, action: str = "none") -> None:
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        entry = (
            f"### [{timestamp}] Interaction\n"
            f"**USER:** {user_input}\n\n"
            f"**EDITH:** {assistant_reply}\n\n"
            f"*Action Taken:* `{action}`\n"
            f"---\n\n"
        )
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception:
            pass
