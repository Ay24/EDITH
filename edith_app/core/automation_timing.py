"""Centralized automation delays — tunable via environment / AppConfig."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _f(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


@dataclass(slots=True)
class AutomationTiming:
    whatsapp_startup_delay: float = 3.5
    whatsapp_search_delay: float = 1.1
    whatsapp_confirm_delay: float = 0.8
    whatsapp_read_chat_delay: float = 2.5
    whatsapp_new_chat_delay: float = 0.9
    whatsapp_clipboard_step: float = 0.2
    whatsapp_focus_click_delay: float = 0.15
    whatsapp_esc_delay: float = 0.1
    whatsapp_copy_step: float = 0.15
    whatsapp_copy_step_short: float = 0.12
    whatsapp_copy_settle: float = 0.35
    whatsapp_ui_tick: float = 0.35
    desktop_open_delay: float = 1.1
    desktop_focus_delay: float = 0.2
    desktop_type_delay: float = 0.4
    desktop_save_delay: float = 0.55
    media_open_delay: float = 2.2
    app_control_step: float = 0.3
    app_control_confirm: float = 0.4
    browser_step: float = 0.2
    vision_settle_delay: float = 1.5
    pyautogui_pause: float = 0.08

    @classmethod
    def from_env(cls) -> AutomationTiming:
        return cls(
            whatsapp_startup_delay=_f("EDITH_WA_STARTUP_DELAY", 3.5),
            whatsapp_search_delay=_f("EDITH_WA_SEARCH_DELAY", 1.1),
            whatsapp_confirm_delay=_f("EDITH_WA_CONFIRM_DELAY", 0.8),
            whatsapp_read_chat_delay=_f("EDITH_WA_READ_CHAT_DELAY", 2.5),
            whatsapp_new_chat_delay=_f("EDITH_WA_NEW_CHAT_DELAY", 0.9),
            whatsapp_clipboard_step=_f("EDITH_WA_CLIPBOARD_STEP", 0.2),
            whatsapp_focus_click_delay=_f("EDITH_WA_FOCUS_DELAY", 0.15),
            whatsapp_esc_delay=_f("EDITH_WA_ESC_DELAY", 0.1),
            whatsapp_copy_step=_f("EDITH_WA_COPY_STEP", 0.15),
            whatsapp_copy_step_short=_f("EDITH_WA_COPY_STEP_SHORT", 0.12),
            whatsapp_copy_settle=_f("EDITH_WA_COPY_SETTLE", 0.35),
            whatsapp_ui_tick=_f("EDITH_WA_UI_TICK", 0.35),
            desktop_open_delay=_f("EDITH_DESKTOP_OPEN_DELAY", 1.1),
            desktop_focus_delay=_f("EDITH_DESKTOP_FOCUS_DELAY", 0.2),
            desktop_type_delay=_f("EDITH_DESKTOP_TYPE_DELAY", 0.4),
            desktop_save_delay=_f("EDITH_DESKTOP_SAVE_DELAY", 0.55),
            media_open_delay=_f("EDITH_MEDIA_OPEN_DELAY", 2.2),
            app_control_step=_f("EDITH_APP_CONTROL_STEP", 0.3),
            app_control_confirm=_f("EDITH_APP_CONTROL_CONFIRM", 0.4),
            browser_step=_f("EDITH_BROWSER_STEP", 0.2),
            vision_settle_delay=_f("EDITH_VISION_SETTLE_DELAY", 1.5),
            pyautogui_pause=_f("EDITH_PYAUTOGUI_PAUSE", 0.08),
        )
