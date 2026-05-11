"""
app_control_service.py — In-app action automation for EDITH.

Architecture (3 tiers):
  1. Deep links   — instant URL-scheme actions (no window focus needed)
  2. Hotkeys      — send keyboard shortcuts to the focused/target window
  3. Vision click — screenshot + pyautogui to click a named UI element

Add new apps by registering entries in _DEEP_LINKS and _HOTKEYS below.
"""
from __future__ import annotations

import re
import subprocess
import time
from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# App registry
# ─────────────────────────────────────────────────────────────────────────────

class _DeepLink(NamedTuple):
    url: str
    reply: str   # what EDITH says after triggering


class _Hotkey(NamedTuple):
    keys: str    # pyautogui hotkey string, e.g. "ctrl+n"
    window_hint: str   # partial window title to focus before sending keys
    reply: str


# Deep-link registry — zero dependency, instant, works even when app is closed
_DEEP_LINKS: dict[str, dict[str, _DeepLink]] = {
    "teams": {
        "new meeting":          _DeepLink("msteams://teams.microsoft.com/l/meeting/new", "Starting a new Teams meeting."),
        "start meeting":        _DeepLink("msteams://teams.microsoft.com/l/meeting/new", "Starting a new Teams meeting."),
        "calendar":             _DeepLink("msteams://teams.microsoft.com/l/entity/com.microsoft.teamspace.tab.planner/", "Opening Teams calendar."),
        "chat":                 _DeepLink("msteams://teams.microsoft.com/l/chat/0/0", "Opening Teams chat."),
        "activity":             _DeepLink("msteams://teams.microsoft.com/l/activity", "Opening Teams activity feed."),
    },
    "zoom": {
        "new meeting":          _DeepLink("zoommtg://zoom.us/start?confno=&zc=0", "Starting a new Zoom meeting."),
        "start meeting":        _DeepLink("zoommtg://zoom.us/start?confno=&zc=0", "Starting a new Zoom meeting."),
        "join meeting":         _DeepLink("zoommtg://zoom.us/join?action=join", "Opening Zoom join dialog."),
        "schedule meeting":     _DeepLink("zoommtg://zoom.us/schedule?action=schedule", "Opening Zoom scheduler."),
    },
    "slack": {
        "new message":          _DeepLink("slack://open?team=&channel=", "Opening a new Slack message."),
        "open":                 _DeepLink("slack://open", "Opening Slack."),
    },
    "vscode": {
        "new file":             _DeepLink("vscode://command/workbench.action.files.newUntitledFile", "Creating a new file in VS Code."),
        "new window":           _DeepLink("vscode://command/workbench.action.newWindow", "Opening a new VS Code window."),
        "open terminal":        _DeepLink("vscode://command/workbench.action.terminal.new", "Opening terminal in VS Code."),
        "settings":             _DeepLink("vscode://command/workbench.action.openSettings", "Opening VS Code settings."),
        "extensions":           _DeepLink("vscode://command/workbench.view.extensions", "Opening VS Code extensions."),
        "command palette":      _DeepLink("vscode://command/workbench.action.showCommands", "Opening VS Code command palette."),
        "open folder":          _DeepLink("vscode://command/workbench.action.openFolder", "Opening folder picker in VS Code."),
    },
    "spotify": {
        "play":                 _DeepLink("spotify:play", "Playing on Spotify."),
        "pause":                _DeepLink("spotify:pause", "Pausing Spotify."),
        "next":                 _DeepLink("spotify:next", "Skipping to next track."),
        "previous":             _DeepLink("spotify:previous", "Going to previous track."),
        "liked songs":          _DeepLink("spotify:user:spotify:collection", "Opening liked songs."),
    },
    "chrome": {
        "new tab":              _DeepLink("chrome://newtab", "Opening a new Chrome tab."),
        "new window":           _DeepLink("chrome://", "Opening Chrome."),
        "settings":             _DeepLink("chrome://settings", "Opening Chrome settings."),
        "extensions":           _DeepLink("chrome://extensions", "Opening Chrome extensions."),
        "history":              _DeepLink("chrome://history", "Opening Chrome history."),
        "downloads":            _DeepLink("chrome://downloads", "Opening Chrome downloads."),
        "bookmarks":            _DeepLink("chrome://bookmarks", "Opening Chrome bookmarks."),
        "incognito":            _DeepLink("", ""),   # handled via subprocess
    },
    "edge": {
        "new tab":              _DeepLink("microsoft-edge://newtab", "Opening a new Edge tab."),
        "settings":             _DeepLink("microsoft-edge://settings", "Opening Edge settings."),
        "history":              _DeepLink("microsoft-edge://history", "Opening Edge history."),
        "downloads":            _DeepLink("microsoft-edge://downloads", "Opening Edge downloads."),
    },
    "whatsapp": {
        "new message":          _DeepLink("whatsapp://send", "Opening WhatsApp new message."),
        "open":                 _DeepLink("whatsapp:", "Opening WhatsApp."),
    },
    "settings": {
        "display":              _DeepLink("ms-settings:display", "Opening display settings."),
        "sound":                _DeepLink("ms-settings:sound", "Opening sound settings."),
        "bluetooth":            _DeepLink("ms-settings:bluetooth", "Opening Bluetooth settings."),
        "wifi":                 _DeepLink("ms-settings:network-wifi", "Opening Wi-Fi settings."),
        "apps":                 _DeepLink("ms-settings:appsfeatures", "Opening Apps settings."),
        "privacy":              _DeepLink("ms-settings:privacy", "Opening Privacy settings."),
        "updates":              _DeepLink("ms-settings:windowsupdate", "Opening Windows Update."),
        "storage":              _DeepLink("ms-settings:storagesense", "Opening Storage settings."),
        "power":                _DeepLink("ms-settings:powersleep", "Opening Power & Sleep settings."),
        "accounts":             _DeepLink("ms-settings:accounts", "Opening Accounts settings."),
        "notifications":        _DeepLink("ms-settings:notifications", "Opening Notifications settings."),
        "taskbar":              _DeepLink("ms-settings:taskbar", "Opening Taskbar settings."),
    },
}

# Hotkey registry — for apps that don't have deep links for specific actions
_HOTKEYS: dict[str, dict[str, _Hotkey]] = {
    "teams": {
        "mute":             _Hotkey("ctrl+shift+m", "Microsoft Teams", "Muted in Teams."),
        "unmute":           _Hotkey("ctrl+shift+m", "Microsoft Teams", "Unmuted in Teams."),
        "camera on":        _Hotkey("ctrl+shift+o", "Microsoft Teams", "Camera toggled in Teams."),
        "camera off":       _Hotkey("ctrl+shift+o", "Microsoft Teams", "Camera toggled in Teams."),
        "toggle video":     _Hotkey("ctrl+shift+o", "Microsoft Teams", "Video toggled in Teams."),
        "raise hand":       _Hotkey("ctrl+shift+k", "Microsoft Teams", "Hand raised in Teams."),
        "end call":         _Hotkey("ctrl+shift+h", "Microsoft Teams", "Call ended in Teams."),
        "leave call":       _Hotkey("ctrl+shift+h", "Microsoft Teams", "Left the Teams call."),
        "chat":             _Hotkey("ctrl+shift+c", "Microsoft Teams", "Chat opened in Teams."),
        "participants":     _Hotkey("ctrl+shift+p", "Microsoft Teams", "Participants panel opened."),
        "fullscreen":       _Hotkey("ctrl+shift+f", "Microsoft Teams", "Fullscreen toggled in Teams."),
    },
    "zoom": {
        "mute":             _Hotkey("alt+a", "Zoom", "Muted in Zoom."),
        "unmute":           _Hotkey("alt+a", "Zoom", "Unmuted in Zoom."),
        "camera on":        _Hotkey("alt+v", "Zoom", "Camera toggled in Zoom."),
        "camera off":       _Hotkey("alt+v", "Zoom", "Camera toggled in Zoom."),
        "raise hand":       _Hotkey("alt+y", "Zoom", "Hand raised in Zoom."),
        "end call":         _Hotkey("alt+q", "Zoom", "Zoom meeting ended."),
        "share screen":     _Hotkey("alt+s", "Zoom", "Screen sharing toggled in Zoom."),
        "participants":     _Hotkey("alt+u", "Zoom", "Participants panel opened."),
        "chat":             _Hotkey("alt+h", "Zoom", "Chat panel opened."),
        "fullscreen":       _Hotkey("alt+f", "Zoom", "Fullscreen toggled in Zoom."),
        "record":           _Hotkey("alt+r", "Zoom", "Recording toggled in Zoom."),
    },
    "chrome": {
        "new tab":          _Hotkey("ctrl+t", "Google Chrome", "New tab opened in Chrome."),
        "close tab":        _Hotkey("ctrl+w", "Google Chrome", "Tab closed in Chrome."),
        "new window":       _Hotkey("ctrl+n", "Google Chrome", "New Chrome window opened."),
        "incognito":        _Hotkey("ctrl+shift+n", "Google Chrome", "Incognito window opened."),
        "refresh":          _Hotkey("f5", "Google Chrome", "Page refreshed in Chrome."),
        "address bar":      _Hotkey("ctrl+l", "Google Chrome", "Address bar focused."),
        "back":             _Hotkey("alt+left", "Google Chrome", "Went back in Chrome."),
        "forward":          _Hotkey("alt+right", "Google Chrome", "Went forward in Chrome."),
        "zoom in":          _Hotkey("ctrl+=", "Google Chrome", "Zoomed in Chrome."),
        "zoom out":         _Hotkey("ctrl+-", "Google Chrome", "Zoomed out in Chrome."),
        "find":             _Hotkey("ctrl+f", "Google Chrome", "Find opened in Chrome."),
        "downloads":        _Hotkey("ctrl+j", "Google Chrome", "Downloads opened in Chrome."),
        "history":          _Hotkey("ctrl+h", "Google Chrome", "History opened in Chrome."),
        "bookmarks":        _Hotkey("ctrl+shift+b", "Google Chrome", "Bookmarks bar toggled."),
        "developer tools":  _Hotkey("f12", "Google Chrome", "Developer tools opened."),
    },
    "edge": {
        "new tab":          _Hotkey("ctrl+t", "Microsoft Edge", "New tab opened in Edge."),
        "close tab":        _Hotkey("ctrl+w", "Microsoft Edge", "Tab closed in Edge."),
        "incognito":        _Hotkey("ctrl+shift+n", "Microsoft Edge", "InPrivate window opened."),
        "refresh":          _Hotkey("f5", "Microsoft Edge", "Page refreshed."),
        "address bar":      _Hotkey("ctrl+l", "Microsoft Edge", "Address bar focused."),
        "back":             _Hotkey("alt+left", "Microsoft Edge", "Went back."),
        "forward":          _Hotkey("alt+right", "Microsoft Edge", "Went forward."),
        "find":             _Hotkey("ctrl+f", "Microsoft Edge", "Find opened."),
        "reading view":     _Hotkey("f9", "Microsoft Edge", "Reading view toggled."),
        "developer tools":  _Hotkey("f12", "Microsoft Edge", "Developer tools opened."),
    },
    "vscode": {
        "save":             _Hotkey("ctrl+s", "Visual Studio Code", "File saved in VS Code."),
        "save all":         _Hotkey("ctrl+k ctrl+s", "Visual Studio Code", "All files saved."),
        "undo":             _Hotkey("ctrl+z", "Visual Studio Code", "Undo in VS Code."),
        "redo":             _Hotkey("ctrl+y", "Visual Studio Code", "Redo in VS Code."),
        "find":             _Hotkey("ctrl+f", "Visual Studio Code", "Find opened in VS Code."),
        "replace":          _Hotkey("ctrl+h", "Visual Studio Code", "Replace opened in VS Code."),
        "new file":         _Hotkey("ctrl+n", "Visual Studio Code", "New file created."),
        "open file":        _Hotkey("ctrl+o", "Visual Studio Code", "Open file dialog opened."),
        "close file":       _Hotkey("ctrl+w", "Visual Studio Code", "File closed."),
        "terminal":         _Hotkey("ctrl+`", "Visual Studio Code", "Terminal toggled."),
        "split editor":     _Hotkey("ctrl+\\", "Visual Studio Code", "Editor split."),
        "command palette":  _Hotkey("ctrl+shift+p", "Visual Studio Code", "Command palette opened."),
        "sidebar":          _Hotkey("ctrl+b", "Visual Studio Code", "Sidebar toggled."),
        "run":              _Hotkey("f5", "Visual Studio Code", "Running in VS Code."),
        "debug":            _Hotkey("f5", "Visual Studio Code", "Debug started."),
        "format":           _Hotkey("shift+alt+f", "Visual Studio Code", "File formatted."),
        "comment":          _Hotkey("ctrl+/", "Visual Studio Code", "Line(s) commented."),
        "zen mode":         _Hotkey("ctrl+k z", "Visual Studio Code", "Zen mode toggled."),
    },
    "notepad": {
        "save":             _Hotkey("ctrl+s", "Notepad", "Saved in Notepad."),
        "new":              _Hotkey("ctrl+n", "Notepad", "New file in Notepad."),
        "open":             _Hotkey("ctrl+o", "Notepad", "Open file in Notepad."),
        "find":             _Hotkey("ctrl+f", "Notepad", "Find opened in Notepad."),
        "replace":          _Hotkey("ctrl+h", "Notepad", "Replace opened in Notepad."),
    },
    "excel": {
        "save":             _Hotkey("ctrl+s", "Microsoft Excel", "Saved in Excel."),
        "new":              _Hotkey("ctrl+n", "Microsoft Excel", "New workbook created."),
        "open":             _Hotkey("ctrl+o", "Microsoft Excel", "Open dialog opened."),
        "find":             _Hotkey("ctrl+f", "Microsoft Excel", "Find opened."),
        "bold":             _Hotkey("ctrl+b", "Microsoft Excel", "Bold applied."),
        "sum":              _Hotkey("alt+=", "Microsoft Excel", "Sum formula inserted."),
    },
    "word": {
        "save":             _Hotkey("ctrl+s", "Microsoft Word", "Saved in Word."),
        "new":              _Hotkey("ctrl+n", "Microsoft Word", "New document created."),
        "bold":             _Hotkey("ctrl+b", "Microsoft Word", "Bold applied."),
        "italic":           _Hotkey("ctrl+i", "Microsoft Word", "Italic applied."),
        "underline":        _Hotkey("ctrl+u", "Microsoft Word", "Underline applied."),
        "find":             _Hotkey("ctrl+f", "Microsoft Word", "Find opened."),
        "replace":          _Hotkey("ctrl+h", "Microsoft Word", "Replace opened."),
        "print":            _Hotkey("ctrl+p", "Microsoft Word", "Print dialog opened."),
        "undo":             _Hotkey("ctrl+z", "Microsoft Word", "Undo in Word."),
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Intent parsing helpers
# ─────────────────────────────────────────────────────────────────────────────

# Normalise raw voice input: "in teams start a new meeting" → app=teams, action=start new meeting
_IN_APP_PATTERN = re.compile(
    r"""
    (?:
        (?:in|on|inside|using|within)\s+(?P<app1>[\w\s]+?)\s+(?P<action1>.+)
        |
        (?P<app2>[\w\s]+?)\s+(?:action|command|do|perform|execute)\s*[:\-]?\s*(?P<action2>.+)
        |
        (?P<action3>.+?)\s+(?:in|on|inside|using|within)\s+(?P<app3>[\w\s]+)
    )$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Common action alias expansions before matching
_ACTION_ALIASES: dict[str, str] = {
    "toggle mute":         "mute",
    "toggle camera":       "camera on",
    "toggle video":        "camera on",
    "end the call":        "end call",
    "leave the call":      "leave call",
    "new tab":             "new tab",
    "open new tab":        "new tab",
    "open incognito":      "incognito",
    "private window":      "incognito",
    "open dev tools":      "developer tools",
    "devtools":            "developer tools",
    "open command palette": "command palette",
    "show commands":       "command palette",
    "open terminal":       "terminal",
    "integrated terminal": "terminal",
    "run code":            "run",
    "format code":         "format",
    "format document":     "format",
    "comment out":         "comment",
    "toggle comment":      "comment",
    "start meeting":       "new meeting",
    "create meeting":      "new meeting",
}

# App name aliases
_APP_ALIASES: dict[str, str] = {
    "microsoft teams":  "teams",
    "ms teams":         "teams",
    "google chrome":    "chrome",
    "ms edge":          "edge",
    "microsoft edge":   "edge",
    "vs code":          "vscode",
    "visual studio code": "vscode",
    "word":             "word",
    "excel":            "excel",
    "microsoft word":   "word",
    "microsoft excel":  "excel",
    "notepad":          "notepad",
    "whatsapp":         "whatsapp",
    "zoom meetings":    "zoom",
}


def _normalize_app(raw: str) -> str:
    cleaned = raw.lower().strip().rstrip("s")  # teams → team etc
    for alias, canonical in _APP_ALIASES.items():
        if alias in cleaned:
            return canonical
    # Direct key match
    cleaned_full = raw.lower().strip()
    if cleaned_full in _DEEP_LINKS or cleaned_full in _HOTKEYS:
        return cleaned_full
    return cleaned_full


def _normalize_action(raw: str) -> str:
    cleaned = raw.lower().strip()
    for alias, canonical in _ACTION_ALIASES.items():
        if alias == cleaned or alias in cleaned:
            return canonical
    return cleaned


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class AppControlService:
    """
    Handle in-app actions via deep links and keyboard shortcuts.
    No vision or click automation required for registered apps.
    """

    def can_handle(self, command: str) -> bool:
        """Return True if this command looks like an in-app action request."""
        lowered = command.lower()
        trigger_phrases = (
            " in teams", " in zoom", " in chrome", " in edge", " in vscode",
            " in vs code", " in spotify", " in slack", " in whatsapp",
            " in word", " in excel", " in notepad", " in settings",
            "in teams ", "in zoom ", "in chrome ", "in edge ",
            "teams action", "chrome action", "zoom action",
            "start a new meeting", "start new meeting", "new meeting in",
            "mute in ", "unmute in ", "end call", "leave call",
            "open new tab", "new tab in", "incognito window",
        )
        return any(phrase in lowered for phrase in trigger_phrases)

    def execute(self, command: str) -> str:
        """Parse command and execute the best available automation tier."""
        app, action = self._parse(command)
        if not app or not action:
            return ""

        # Tier 1: Deep link
        app_links = _DEEP_LINKS.get(app, {})
        link = app_links.get(action)
        if link and link.url:
            return self._launch_url(link.url, link.reply)

        # Fuzzy deep link match (partial action match)
        for key, link in app_links.items():
            if key in action or action in key:
                if link.url:
                    return self._launch_url(link.url, link.reply)

        # Tier 2: Keyboard shortcut
        app_hotkeys = _HOTKEYS.get(app, {})
        hotkey = app_hotkeys.get(action)
        if hotkey:
            return self._send_hotkey(hotkey)

        # Fuzzy hotkey match
        for key, hotkey in app_hotkeys.items():
            if key in action or action in key:
                return self._send_hotkey(hotkey)

        return f"I know {app} but I don't have a shortcut for '{action}' yet."

    def _parse(self, command: str) -> tuple[str, str]:
        """Extract (app_name, action) from a natural language command."""
        lowered = command.lower().strip()

        # Direct pattern match
        m = _IN_APP_PATTERN.match(lowered)
        if m:
            app   = m.group("app1") or m.group("app2") or m.group("app3") or ""
            action = m.group("action1") or m.group("action2") or m.group("action3") or ""
            return _normalize_app(app.strip()), _normalize_action(action.strip())

        # Heuristic: "start a new meeting in teams"
        for app_key in list(_DEEP_LINKS.keys()) + list(_HOTKEYS.keys()):
            # Check "... in <app>" or "in <app> ..."
            patterns = [
                rf"\bin\s+{re.escape(app_key)}\b",
                rf"\b{re.escape(app_key)}\b.*\b(?:action|command|do)\b",
            ]
            for pat in patterns:
                if re.search(pat, lowered):
                    # Everything that isn't "in <app>" is the action
                    action_raw = re.sub(
                        rf"(in|on|inside|using|within)?\s*{re.escape(app_key)}\s*(and|then|to|please|now)?",
                        "", lowered
                    ).strip()
                    return app_key, _normalize_action(action_raw)

        # Check for common standalone phrases
        if "new meeting" in lowered:
            for app_key in ("teams", "zoom"):
                if app_key in lowered:
                    return app_key, "new meeting"
            return "teams", "new meeting"

        if "end call" in lowered or "leave call" in lowered:
            for app_key in ("teams", "zoom"):
                if app_key in lowered:
                    return app_key, "end call"

        if "mute" in lowered and ("teams" in lowered or "zoom" in lowered):
            app = "teams" if "teams" in lowered else "zoom"
            return app, "mute"

        return "", ""

    def _launch_url(self, url: str, reply: str) -> str:
        try:
            subprocess.Popen(f'start "" "{url}"', shell=True)
            return reply
        except Exception as exc:
            return f"I tried to trigger that action but ran into an issue: {exc}"

    def _send_hotkey(self, hotkey: _Hotkey) -> str:
        """Focus target window and send keyboard shortcut via pyautogui."""
        try:
            import pygetwindow as gw
            import pyautogui
        except ImportError:
            # Fallback: just send keys without window focus
            try:
                import pyautogui
                time.sleep(0.3)
                for key_combo in hotkey.keys.split():
                    keys = key_combo.split("+")
                    pyautogui.hotkey(*keys)
                return hotkey.reply
            except ImportError:
                return f"I need pyautogui installed to send shortcuts. Run: pip install pyautogui pygetwindow"

        try:
            # Find and focus the target window
            windows = gw.getWindowsWithTitle(hotkey.window_hint)
            if windows:
                win = windows[0]
                if win.isMinimized:
                    win.restore()
                win.activate()
                time.sleep(0.4)

            import pyautogui
            pyautogui.FAILSAFE = False
            for key_combo in hotkey.keys.split():
                keys = key_combo.split("+")
                pyautogui.hotkey(*keys)
            return hotkey.reply

        except Exception as exc:
            return f"I sent the shortcut but couldn't confirm: {exc}"

    def list_supported_actions(self, app: str | None = None) -> str:
        """Return a human-readable list of supported apps and actions."""
        if app:
            key = _normalize_app(app)
            links = list(_DEEP_LINKS.get(key, {}).keys())
            hotkeys = list(_HOTKEYS.get(key, {}).keys())
            actions = sorted(set(links + hotkeys))
            if not actions:
                return f"I don't have registered actions for {app} yet."
            return f"Actions I can do in {key}: " + ", ".join(actions) + "."
        apps = sorted(set(list(_DEEP_LINKS.keys()) + list(_HOTKEYS.keys())))
        return "I can control these apps: " + ", ".join(apps) + ". Ask me what I can do in any of them."
