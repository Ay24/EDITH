import re
from typing import NamedTuple

class RoutedCommand(NamedTuple):
    action: str
    params: dict

class PatternRouter:
    def __init__(self):
        self.patterns = [
            # Volume
            (r"(?:set|change|turn|put)\s+(?:the\s+)?volume\s+(?:to\s+)?(\d+)", "set_volume"),
            (r"volume\s+(\d+)", "set_volume"),
            (r"\b(?:volume\s+)?up\b", "volume_up"),
            (r"\b(?:volume\s+)?down\b", "volume_down"),
            (r"\bmute\b", "mute"),
            (r"\bunmute\b", "unmute"),
            
            # Time/Date
            (r"\btime\b|what\s+is\s+the\s+time|what\s+time\s+is\s+it", "get_time"),
            (r"\bdate\b|what\s+is\s+today's\s+date|what's\s+the\s+date", "get_date"),
            
            # Apps (Common ones)
            (r"open\s+(?:the\s+)?calculator", "open_app", {"app": "calculator"}),
            (r"open\s+(?:the\s+)?notepad", "open_app", {"app": "notepad"}),
            (r"open\s+(?:the\s+)?browser|open\s+google", "open_app", {"app": "browser"}),
            (r"open\s+(?:the\s+)?settings", "open_app", {"app": "settings"}),
            (r"open\s+whatsapp", "open_app", {"app": "whatsapp"}),
            (r"open\s+spotify", "open_app", {"app": "spotify"}),
            (r"open\s+youtube", "open_app", {"app": "youtube"}),
            
            # Folders
            (r"open\s+(?:the\s+)?downloads(?:\s+folder)?", "open_folder", {"folder": "downloads"}),
            (r"open\s+(?:the\s+)?desktop(?:\s+folder)?", "open_folder", {"folder": "desktop"}),
            (r"open\s+(?:the\s+)?documents(?:\s+folder)?", "open_folder", {"folder": "documents"}),
            
            # Basic Controls
            (r"lock\s+(?:my\s+)?(?:pc|computer|system)", "lock_pc"),
            (r"sleep\s+(?:my\s+)?(?:pc|computer|system)", "sleep_pc"),
            (r"wifi\s+on|enable\s+wifi", "wifi_on"),
            (r"wifi\s+off|disable\s+wifi", "wifi_off"),
            
            # Modes
            (r"start\s+focus\s+mode|focus\s+mode", "mode", {"mode": "focus"}),
            (r"start\s+coding\s+mode|coding\s+mode", "mode", {"mode": "coding"}),
            (r"start\s+research\s+mode|research\s+mode", "mode", {"mode": "research"}),
            (r"start\s+cinematic\s+mode|cinematic\s+mode", "mode", {"mode": "cinematic"}),
        ]

    def route(self, command: str) -> RoutedCommand | None:
        lowered = command.lower().strip()
        for pattern, action, *extra in self.patterns:
            match = re.search(pattern, lowered)
            if match:
                params = dict(extra[0]) if extra else {}
                # Capture groups as params
                if match.groups():
                    if action == "set_volume":
                        params["value"] = int(match.group(1))
                return RoutedCommand(action, params)
        return None
