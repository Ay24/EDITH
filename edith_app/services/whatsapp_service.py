from __future__ import annotations

import subprocess
import time

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    import pyperclip
except ImportError:
    pyperclip = None


class WhatsAppService:
    def __init__(self) -> None:
        if pyautogui is not None:
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.08
        self._startup_delay = 3.5
        self._search_delay = 1.1
        self._confirm_delay = 0.8

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
            time.sleep(0.2)
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
        time.sleep(2.5)

        try:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.4)
            copied = pyperclip.paste().strip()
            if not copied:
                return "I couldn't copy the visible WhatsApp chat text."
            return copied[-2000:]
        except Exception as exc:
            return f"I couldn't read the current WhatsApp chat: {exc}"

    def _open_chat(self, contact_name: str) -> bool:
        if not self.available:
            return False
        exact_name = contact_name.strip()
        if not exact_name:
            return False

        try:
            pyperclip.copy(exact_name)
            pyautogui.hotkey("ctrl", "n")
            time.sleep(0.9)
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
