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
            (r"\bvolume\s+up\b", "adjust_volume", {"direction": "up"}),
            (r"\bvolume\s+down\b", "adjust_volume", {"direction": "down"}),
            (r"\bincrease\s+volume\b", "adjust_volume", {"direction": "up"}),
            (r"\bdecrease\s+volume\b", "adjust_volume", {"direction": "down"}),
            (r"\bmute\b", "mute"),
            (r"\bunmute\b", "unmute"),

            # Brightness
            (r"(?:set|change)\s+(?:the\s+)?brightness\s+(?:to\s+)?(\d+)", "set_brightness"),
            (r"brightness\s+(\d+)", "set_brightness"),

            # Time / Date
            (r"\bwhat(?:'s| is)\s+the\s+time\b|\btime\b|\bwhat time is it\b", "get_time"),
            (r"\bwhat(?:'s| is)\s+(?:today(?:'s)?\s+)?(?:the\s+)?date\b|\bdate\b|\bwhat day is it\b", "get_date"),

            # System status
            (r"\bsystem\s+status\b|\bstatus\b|\bhow is the system\b", "system_status"),

            # Apps
            (r"\bopen\s+(?:the\s+)?calculator\b", "open_app", {"name": "calculator"}),
            (r"\bopen\s+(?:the\s+)?notepad\b", "open_app", {"name": "notepad"}),
            (r"\bopen\s+(?:the\s+)?(?:browser|google|chrome)\b", "open_app", {"name": "chrome"}),
            (r"\bopen\s+(?:the\s+)?settings\b", "open_app", {"name": "settings"}),
            (r"\bopen\s+whatsapp\b", "open_app", {"name": "whatsapp"}),
            (r"\bopen\s+spotify\b", "open_app", {"name": "spotify"}),
            (r"\bopen\s+youtube\b", "open_youtube"),
            (r"\bopen\s+(?:vs\s*code|visual\s+studio\s+code)\b", "open_app", {"name": "vscode"}),
            (r"\bopen\s+(?:the\s+)?task\s+manager\b", "open_app", {"name": "taskmgr"}),
            (r"\bopen\s+paint\b", "open_app", {"name": "paint"}),
            (r"\bopen\s+(?:the\s+)?terminal\b", "open_app", {"name": "terminal"}),
            (r"\bopen\s+(?:file\s+)?explorer\b", "open_app", {"name": "explorer"}),
            (r"\bopen\s+camera\b", "open_app", {"name": "camera"}),
            (r"\bopen\s+teams\b", "open_app", {"name": "teams"}),
            (r"\bopen\s+discord\b", "open_app", {"name": "discord"}),
            (r"\bopen\s+(?:vs\s*)?code\b", "open_app", {"name": "vscode"}),

            # Folders
            (r"\bopen\s+(?:the\s+)?downloads(?:\s+folder)?\b", "open_app", {"name": "downloads"}),
            (r"\bopen\s+(?:the\s+)?desktop(?:\s+folder)?\b", "open_app", {"name": "desktop"}),
            (r"\bopen\s+(?:the\s+)?documents(?:\s+folder)?\b", "open_app", {"name": "documents"}),
            (r"\bopen\s+(?:the\s+)?pictures(?:\s+folder)?\b", "open_app", {"name": "pictures"}),

            # Connectivity
            (r"\bwifi\s+on\b|\benable\s+wifi\b|\bturn\s+(?:on\s+)?wifi\b", "wifi", {"enabled": True}),
            (r"\bwifi\s+off\b|\bdisable\s+wifi\b|\bturn\s+(?:off\s+)?wifi\b", "wifi", {"enabled": False}),

            # Tasks
            (r"\b(?:list|show)\s+(?:my\s+)?(?:pending\s+)?tasks\b|\bwhat are my tasks\b|\bmy tasks\b", "list_tasks"),
            (r"\bwhat(?:'s| is) (?:my )?next task\b|\bnext task\b", "list_tasks"),

            # Media
            (r"\bplay\s+(.+?)\s+on\s+youtube\b|\bplay\s+(.+?)\s+youtube\b", "play_youtube"),
            (r"\bplay\s+(.+?)\s+on\s+spotify\b|\bplay\s+(.+?)\s+spotify\b", "play_spotify"),

            # System actions
            (r"\block\s+(?:the\s+)?(?:pc|computer|screen)\b|\block\s+pc\b", "lock_pc"),
            (r"\bsystem\s+status\b|\bpreflight\b|\bstatus\b", "system_status"),
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
                        params["level"] = int(match.group(1))
                    elif action == "set_brightness":
                        params["level"] = int(match.group(1))
                    elif action == "play_youtube":
                        query = match.group(1) or match.group(2) or ""
                        params["query"] = query.strip()
                    elif action == "play_spotify":
                        query = match.group(1) or match.group(2) or ""
                        params["query"] = query.strip()
                return RoutedCommand(action, params)
        return None
