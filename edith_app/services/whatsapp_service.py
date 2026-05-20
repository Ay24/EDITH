from __future__ import annotations

import subprocess
import time
from pathlib import Path

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    import pyperclip
except ImportError:
    pyperclip = None
try:
    from pywinauto import Desktop
except ImportError:
    Desktop = None


class WhatsAppService:
    def __init__(self, timing: object | None = None) -> None:
        t = timing
        if pyautogui is not None:
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = getattr(t, "pyautogui_pause", 0.08) if t else 0.08
        self._startup_delay = getattr(t, "whatsapp_startup_delay", 3.5) if t else 3.5
        self._search_delay = getattr(t, "whatsapp_search_delay", 1.1) if t else 1.1
        self._confirm_delay = getattr(t, "whatsapp_confirm_delay", 0.8) if t else 0.8
        self._read_chat_delay = getattr(t, "whatsapp_read_chat_delay", 2.5) if t else 2.5
        self._new_chat_delay = getattr(t, "whatsapp_new_chat_delay", 0.9) if t else 0.9
        self._clipboard_step = getattr(t, "whatsapp_clipboard_step", 0.2) if t else 0.2
        self._focus_delay = getattr(t, "whatsapp_focus_click_delay", 0.15) if t else 0.15
        self._esc_delay = getattr(t, "whatsapp_esc_delay", 0.1) if t else 0.1
        self._copy_step = getattr(t, "whatsapp_copy_step", 0.15) if t else 0.15
        self._copy_step_short = getattr(t, "whatsapp_copy_step_short", 0.12) if t else 0.12
        self._copy_settle = getattr(t, "whatsapp_copy_settle", 0.35) if t else 0.35
        self._ui_tick = getattr(t, "whatsapp_ui_tick", 0.35) if t else 0.35

    @property
    def available(self) -> bool:
        return pyautogui is not None and pyperclip is not None

    def open_app(self) -> str:
        try:
            subprocess.Popen('start "" "whatsapp:"', shell=True)
            return "Opening WhatsApp Desktop."
        except Exception as exc:
            return f"I couldn't open WhatsApp Desktop: {exc}"

    def send_message(self, contact_name: str, message: str) -> str:
        if not self.available:
            return "WhatsApp automation needs pyautogui and pyperclip installed."

        self.open_app()
        time.sleep(self._startup_delay)

        try:
            if not self._open_chat(contact_name):
                return (
                    f"I couldn't confidently open the WhatsApp chat for {contact_name}. "
                    "Please open that chat once and try again."
                )

            pyperclip.copy(message)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(self._clipboard_step)
            pyautogui.press("enter")
            return f"Sent your WhatsApp message to {contact_name}."
        except Exception as exc:
            return f"I couldn't send the WhatsApp message: {exc}"

    def voice_call(self, contact_name: str) -> str:
        if not self.available:
            return "WhatsApp calling needs pyautogui and pyperclip installed."

        self.open_app()
        time.sleep(self._startup_delay)

        try:
            if not self._open_chat(contact_name):
                return f"I couldn't open the WhatsApp chat for {contact_name}."
            pyautogui.hotkey("ctrl", "shift", "c")
            return f"Starting a WhatsApp voice call with {contact_name}."
        except Exception as exc:
            return f"I couldn't start the WhatsApp voice call: {exc}"

    def video_call(self, contact_name: str) -> str:
        if not self.available:
            return "WhatsApp calling needs pyautogui and pyperclip installed."

        self.open_app()
        time.sleep(self._startup_delay)

        try:
            if not self._open_chat(contact_name):
                return f"I couldn't open the WhatsApp chat for {contact_name}."
            pyautogui.hotkey("ctrl", "shift", "v")
            return f"Starting a WhatsApp video call with {contact_name}."
        except Exception as exc:
            return f"I couldn't start the WhatsApp video call: {exc}"

    def read_current_chat(self) -> str:
        if not self.available:
            return "WhatsApp reading needs pyautogui and pyperclip installed."

        self.open_app()
        time.sleep(self._read_chat_delay)

        try:
            baseline = pyperclip.paste()
            copied = self._copy_visible_chat_text(baseline)
            if copied:
                return copied[-4000:]
            return "I couldn't copy the visible WhatsApp chat text."
        except Exception as exc:
            return f"I couldn't read the current WhatsApp chat: {exc}"

    def read_current_chat_uia(self) -> str:
        if Desktop is None:
            return ""
        try:
            win = self._find_whatsapp_window()
            if win is None:
                return ""
            try:
                win.set_focus()
            except Exception:
                pass
            texts: list[str] = []
            descendants = win.descendants()
            for el in descendants:
                try:
                    text = (el.window_text() or "").strip()
                except Exception:
                    continue
                if not text:
                    continue
                if len(text) > 220:
                    text = text[:220]
                if self._likely_chat_line(text):
                    texts.append(text)
            if not texts:
                return ""
            deduped: list[str] = []
            seen: set[str] = set()
            for t in texts:
                key = t.lower()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(t)
            return "\n".join(deduped[-80:])
        except Exception:
            return ""

    def capture_chat_screenshot(self) -> str | None:
        if pyautogui is None:
            return None
        try:
            path = Path("data") / "whatsapp_chat_capture.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            shot = pyautogui.screenshot()
            width, height = shot.size
            # Approximate WhatsApp Desktop chat pane crop (right side, excluding left chat list).
            left = int(width * 0.30)
            top = int(height * 0.10)
            right = int(width * 0.99)
            bottom = int(height * 0.95)
            if right > left and bottom > top:
                shot = shot.crop((left, top, right, bottom))
            shot.save(path)
            return str(path)
        except Exception:
            return None

    def _open_chat(self, contact_name: str) -> bool:
        if not self.available:
            return False
        exact_name = contact_name.strip()
        if not exact_name:
            return False

        try:
            pyperclip.copy(exact_name)
            pyautogui.hotkey("ctrl", "n")
            time.sleep(self._new_chat_delay)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("backspace")
            pyautogui.hotkey("ctrl", "v")
            time.sleep(self._search_delay)
            pyautogui.press("enter")
            time.sleep(self._confirm_delay)
            pyautogui.press("enter")
            time.sleep(self._confirm_delay)
            return True
        except Exception:
            return False

    def _copy_visible_chat_text(self, baseline_clipboard: str) -> str:
        if not self.available:
            return ""

        # Focus chat pane to improve copy reliability.
        screen_w, screen_h = pyautogui.size()
        pyautogui.click(int(screen_w * 0.72), int(screen_h * 0.46))
        time.sleep(self._focus_delay)
        pyautogui.press("esc")
        time.sleep(self._esc_delay)

        attempts: list[tuple[str, callable]] = [
            (
                "ctrl_a_copy",
                lambda: (
                    pyautogui.hotkey("ctrl", "a"),
                    time.sleep(self._copy_step),
                    pyautogui.hotkey("ctrl", "c"),
                ),
            ),
            (
                "page_up_then_copy",
                lambda: (
                    pyautogui.press("pageup"),
                    time.sleep(self._copy_step),
                    pyautogui.hotkey("ctrl", "a"),
                    time.sleep(self._copy_step_short),
                    pyautogui.hotkey("ctrl", "c"),
                ),
            ),
        ]

        for _, run_attempt in attempts:
            try:
                run_attempt()
            except Exception:
                continue
            time.sleep(self._copy_settle)
            copied = pyperclip.paste().strip()
            if not copied:
                continue
            if copied == (baseline_clipboard or "").strip():
                continue
            if len(copied) < 10:
                continue
            return copied
        return ""

    def _find_whatsapp_window(self):
        if Desktop is None:
            return None
        desktop = Desktop(backend="uia")
        candidates = desktop.windows()
        for win in candidates:
            try:
                title = (win.window_text() or "").lower()
            except Exception:
                continue
            if "whatsapp" in title:
                return win
        return None

    def _likely_chat_line(self, text: str) -> bool:
        lowered = text.lower().strip()
        if len(lowered) < 2:
            return False
        blocked = (
            "whatsapp",
            "search",
            "new chat",
            "typing",
            "online",
            "yesterday",
            "today",
            "menu",
            "archive",
            "settings",
            "status",
            "channels",
            "communities",
        )
        if lowered in blocked:
            return False
        if lowered.startswith(("ctrl+", "alt+", "press ")):
            return False
        return True
