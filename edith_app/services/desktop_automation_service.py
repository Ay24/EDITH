from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from edith_app.services.system_service import SystemService


@dataclass(slots=True)
class DesktopFileTask:
    app: str
    filename: str
    extension: str
    content: str
    target_dir: str
    use_gui: bool


class DesktopAutomationService:
    """
    Dynamic desktop task runner focused on low-latency file workflows.

    Design goals:
    - Keep behavior predictable and fast.
    - Avoid app-specific hardcoding beyond generic app open/focus primitives.
    - Fall back to direct filesystem writes when GUI automation is unavailable.
    """

    def __init__(self, system: SystemService) -> None:
        self._system = system
        self._home = Path.home()
        self._default_dir = self._home / "Desktop"

    def can_handle(self, command: str) -> bool:
        lowered = command.lower().strip()
        if not lowered:
            return False
        file_markers = (
            "create file",
            "new file",
            "create a file",
            "make a file",
            "text file",
            "save as",
            "with extension",
            "type in it",
            "write in it",
        )
        return any(marker in lowered for marker in file_markers)

    def execute(
        self,
        command: str,
        parse_with_model: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> str:
        task = self._parse_task(command, parse_with_model=parse_with_model)
        if task is None:
            return ""

        target_dir = self._resolve_target_dir(task.target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = self._build_filename(task.filename, task.extension)
        destination = target_dir / filename

        if task.use_gui:
            gui_reply = self._create_with_gui(task.app, destination, task.content)
            if gui_reply:
                return gui_reply

        return self._create_direct(destination, task.content, app=task.app)

    def _parse_task(
        self,
        command: str,
        parse_with_model: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> DesktopFileTask | None:
        rule_task = self._parse_task_rules(command)
        if rule_task is not None:
            return rule_task
        if parse_with_model is None:
            return None
        parsed = parse_with_model(command)
        if not parsed:
            return None

        confidence = parsed.get("confidence", 0.0)
        try:
            confidence_value = float(confidence)
        except Exception:
            confidence_value = 0.0
        if confidence_value < 0.45:
            return None

        filename = str(parsed.get("filename", "")).strip() or "new_file"
        extension = str(parsed.get("extension", "")).strip() or ".txt"
        content = str(parsed.get("content", "")).strip()
        app = str(parsed.get("app", "")).strip() or "notepad"
        target_dir = str(parsed.get("target_dir", "")).strip() or "desktop"
        use_gui = str(parsed.get("use_gui", "true")).lower() not in {"false", "0", "no"}
        return DesktopFileTask(
            app=app,
            filename=filename,
            extension=extension,
            content=content,
            target_dir=target_dir,
            use_gui=use_gui,
        )

    def _parse_task_rules(self, command: str) -> DesktopFileTask | None:
        lowered = command.lower()
        if not self.can_handle(command):
            return None

        app = "notepad"
        for name in ("wps", "notepad", "file explorer", "explorer", "vscode", "vs code"):
            if name in lowered:
                app = name
                break

        target_dir = "desktop"
        for folder in ("desktop", "downloads", "documents"):
            if folder in lowered:
                target_dir = folder
                break
        path_match = re.search(r"(?:in|inside|under)\s+([a-zA-Z]:\\[^,\n]+)", command, flags=re.IGNORECASE)
        if path_match:
            target_dir = path_match.group(1).strip()

        filename = "new_file"
        extension = ".txt"
        content = ""

        save_as_match = re.search(
            r"(?:save as|named|called)\s+['\"]?([a-zA-Z0-9 _\-.]+)['\"]?",
            command,
            flags=re.IGNORECASE,
        )
        if save_as_match:
            raw = save_as_match.group(1).strip().rstrip(".")
            stem, ext = os.path.splitext(raw)
            if stem:
                filename = stem
            elif raw:
                filename = raw
            if ext:
                extension = ext

        ext_match = re.search(
            r"(?:extension|ext)\s+['\"]?\.?([a-zA-Z0-9]{1,8})['\"]?",
            command,
            flags=re.IGNORECASE,
        )
        if ext_match:
            extension = f".{ext_match.group(1).lower()}"

        content_match = re.search(
            r"(?:type|write|with content|content)\s+['\"](.+?)['\"]",
            command,
            flags=re.IGNORECASE,
        )
        if content_match:
            content = content_match.group(1)

        use_gui = app not in {"file explorer", "explorer"}
        return DesktopFileTask(
            app=app,
            filename=filename,
            extension=extension,
            content=content,
            target_dir=target_dir,
            use_gui=use_gui,
        )

    def _resolve_target_dir(self, raw_dir: str) -> Path:
        lowered = raw_dir.lower().strip()
        if lowered in {"desktop"}:
            return self._home / "Desktop"
        if lowered in {"downloads", "download"}:
            return self._home / "Downloads"
        if lowered in {"documents", "document"}:
            return self._home / "Documents"
        expanded = Path(os.path.expandvars(raw_dir)).expanduser()
        if expanded.exists() and expanded.is_dir():
            return expanded
        return self._default_dir

    def _build_filename(self, stem: str, extension: str) -> str:
        clean_stem = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "", stem).strip(" .")
        if not clean_stem:
            clean_stem = "new_file"
        clean_ext = extension.strip()
        if not clean_ext:
            clean_ext = ".txt"
        if not clean_ext.startswith("."):
            clean_ext = f".{clean_ext}"
        clean_ext = re.sub(r"[^a-zA-Z0-9.]+", "", clean_ext)[:10] or ".txt"
        if clean_stem.lower().endswith(clean_ext.lower()):
            return clean_stem
        return f"{clean_stem}{clean_ext}"

    def _create_with_gui(self, app: str, destination: Path, content: str) -> str:
        try:
            import pyautogui
        except Exception:
            return ""

        open_target = "vscode" if app == "vs code" else app
        self._system.open_target(open_target)
        time.sleep(1.1)
        pyautogui.FAILSAFE = False
        try:
            pyautogui.hotkey("ctrl", "n")
            time.sleep(0.2)
            if content:
                pyautogui.write(content, interval=0.006)
            pyautogui.hotkey("ctrl", "s")
            time.sleep(0.4)
            pyautogui.write(str(destination), interval=0.008)
            pyautogui.press("enter")
            time.sleep(0.55)
            if destination.exists():
                return f"Created {destination.name} in {destination.parent} using {app}."
            return ""
        except Exception:
            return ""

    def _create_direct(self, destination: Path, content: str, app: str) -> str:
        try:
            destination.write_text(content, encoding="utf-8")
        except Exception as exc:
            return f"I could not create {destination.name}: {exc}"

        if app in {"notepad", "wps", "vscode", "vs code"}:
            try:
                self._system.open_file(str(destination))
            except Exception:
                pass
        return f"Created {destination.name} in {destination.parent}."

