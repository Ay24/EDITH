from __future__ import annotations

from pathlib import Path
import os
import subprocess
import webbrowser


class SystemService:
    def __init__(self) -> None:
        self._home = Path.home()
        self._search_roots = [
            self._home / "Desktop",
            self._home / "Documents",
            self._home / "Downloads",
            self._home / "Pictures",
            self._home,
        ]
        self._known_apps = {
            "calculator": "calc.exe",
            "calc": "calc.exe",
            "notepad": "notepad.exe",
            "paint": "mspaint.exe",
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
            "explorer": "explorer.exe",
            "file explorer": "explorer.exe",
            "settings": "start ms-settings:",
            "task manager": "taskmgr.exe",
            "control panel": "control.exe",
            "whatsapp": "start whatsapp:",
        }

    def open_app(self, app_name: str) -> str:
        target = self._known_apps.get(app_name.lower().strip(), app_name.strip())
        return self._run_command(target, f"Opening {app_name}.")

    def open_folder(self, path: str) -> str:
        expanded = Path(os.path.expandvars(path)).expanduser()
        if expanded.exists():
            subprocess.Popen(["explorer.exe", str(expanded)])
            return f"Opening folder {expanded}."
        return f"I couldn't find the folder {expanded}."

    def search_files(self, name: str, limit: int = 8) -> list[str]:
        needle = name.lower().strip()
        matches: list[str] = []
        for root in self._search_roots:
            if not root.exists():
                continue
            try:
                for path in root.rglob("*"):
                    if needle in path.name.lower():
                        matches.append(str(path))
                        if len(matches) >= limit:
                            return matches
            except OSError:
                continue
        return matches

    def set_brightness(self, percent: int) -> str:
        percent = max(10, min(100, percent))
        script = (
            "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
            f".WmiSetBrightness(1,{percent})"
        )
        return self._run_powershell(script, f"Brightness set to {percent}%.")

    def wifi(self, enabled: bool) -> str:
        state = "enabled" if enabled else "disabled"
        command = f'netsh interface set interface name="Wi-Fi" admin={state}'
        message = "Wi-Fi enabled." if enabled else "Wi-Fi disabled."
        return self._run_command(command, message)

    def bluetooth_settings(self) -> str:
        return self._run_command("start ms-settings:bluetooth", "Opening Bluetooth settings.")

    def check_updates(self) -> str:
        try:
            result = subprocess.run(
                ["winget", "upgrade", "--include-unknown"],
                capture_output=True,
                text=True,
                timeout=45,
                shell=False,
            )
            output = (result.stdout or result.stderr or "").strip()
            if not output:
                return "No update information was returned by winget."
            return output[:1800]
        except Exception as exc:
            return f"I couldn't check updates automatically: {exc}"

    def upgrade_apps(self) -> str:
        command = "winget upgrade --all --include-unknown --silent"
        return self._run_command(command, "Attempting to upgrade available applications.")

    def lock_pc(self) -> str:
        return self._run_command("rundll32.exe user32.dll,LockWorkStation", "Locking the PC.")

    def sleep_pc(self) -> str:
        script = "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"
        return self._run_command(script, "Putting the PC to sleep.")

    def open_website(self, url: str, label: str) -> str:
        webbrowser.open(url)
        return f"Opening {label}."

    def _run_powershell(self, script: str, success_message: str) -> str:
        return self._run_command(
            f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{script}"',
            success_message,
        )

    def _run_command(self, command: str, success_message: str) -> str:
        try:
            subprocess.Popen(command, shell=True)
            return success_message
        except Exception as exc:
            return f"I couldn't complete that system action: {exc}"
