from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import time
import webbrowser


class SystemService:
    def __init__(self) -> None:
        self._home = Path.home()
        self._special_folders = {
            "downloads": self._home / "Downloads",
            "documents": self._home / "Documents",
            "desktop": self._home / "Desktop",
            "pictures": self._home / "Pictures",
            "music": self._home / "Music",
            "videos": self._home / "Videos",
        }
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
        self._known_sites = {
            "notebooklm": "https://notebooklm.google.com/",
            "chatgpt": "https://chatgpt.com/",
            "github": "https://github.com/",
            "gmail": "https://mail.google.com/",
            "google docs": "https://docs.google.com/",
            "google drive": "https://drive.google.com/",
            "google calendar": "https://calendar.google.com/",
            "google maps": "https://maps.google.com/",
            "wikipedia": "https://wikipedia.org/",
            "youtube": "https://www.youtube.com/",
            "spotify": "https://open.spotify.com/",
            "notion": "https://www.notion.so/",
            "stackoverflow": "https://stackoverflow.com/",
            "whatsapp web": "https://web.whatsapp.com/",
        }
        self._search_cache: dict[tuple[str, str, int], tuple[float, list[str]]] = {}

    def open_app(self, app_name: str) -> str:
        target = self._known_apps.get(app_name.lower().strip(), app_name.strip())
        return self._run_command(target, f"Opening {app_name}.")

    def open_target(self, target: str) -> str:
        normalized = target.lower().strip()

        if normalized in self._special_folders:
            return self.open_folder(str(self._special_folders[normalized]))

        if normalized in self._known_sites:
            webbrowser.open(self._known_sites[normalized])
            return f"Opening {target} in your browser."

        if normalized in self._known_apps:
            return self.open_app(normalized)

        candidate_path = Path(os.path.expandvars(target)).expanduser()
        if candidate_path.exists():
            if candidate_path.is_dir():
                return self.open_folder(str(candidate_path))
            return self.open_file(str(candidate_path))

        executable = shutil.which(target)
        if executable:
            return self.open_file(executable)

        local_matches = self.search_files(target, limit=1)
        if local_matches:
            first = Path(local_matches[0])
            if first.is_dir():
                return self.open_folder(str(first))
            return self.open_file(str(first))

        if normalized.startswith("http://") or normalized.startswith("https://"):
            webbrowser.open(target)
            return f"Opening {target}."

        if "." in normalized and " " not in normalized:
            webbrowser.open(f"https://{normalized}")
            return f"Opening {normalized}."

        guessed_site = normalized.replace(" ", "")
        if guessed_site:
            webbrowser.open(f"https://www.google.com/search?q={guessed_site}")
            return f"I couldn't match a local app, so I searched the web for {target}."

        return f"I couldn't figure out how to open {target}."

    def open_folder(self, path: str) -> str:
        expanded = Path(os.path.expandvars(path)).expanduser()
        if expanded.exists():
            subprocess.Popen(["explorer.exe", str(expanded)])
            return f"Opening folder {expanded}."
        return f"I couldn't find the folder {expanded}."

    def open_file(self, path: str) -> str:
        expanded = Path(os.path.expandvars(path)).expanduser()
        if not expanded.exists():
            return f"I couldn't find {expanded}."
        try:
            os.startfile(str(expanded))
            return f"Opening {expanded.name}."
        except Exception:
            try:
                subprocess.Popen(["explorer.exe", str(expanded)])
                return f"Opening {expanded.name}."
            except Exception as exc:
                return f"I couldn't open {expanded.name}: {exc}"

    def search_files(self, name: str, limit: int = 8) -> list[str]:
        needle = name.lower().strip()
        cached = self._cache_get(("global", needle, limit))
        if cached is not None:
            return cached
        quick_matches = self._fast_filename_search(needle, limit)
        if quick_matches:
            self._cache_set(("global", needle, limit), quick_matches)
            return quick_matches
        matches: list[str] = []
        for root in self._search_roots:
            if not root.exists():
                continue
            try:
                for path in root.rglob("*"):
                    if needle in path.name.lower():
                        matches.append(str(path))
                        if len(matches) >= limit:
                            self._cache_set(("global", needle, limit), matches)
                            return matches
            except OSError:
                continue
        self._cache_set(("global", needle, limit), matches)
        return matches

    def search_within_folder(self, name: str, folder: str, limit: int = 8) -> list[str]:
        root = self._resolve_folder(folder)
        if root is None or not root.exists():
            return []
        needle = name.lower().strip()
        cache_key = (str(root).lower(), needle, limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        matches: list[str] = []
        try:
            for path in root.rglob("*"):
                if needle in path.name.lower():
                    matches.append(str(path))
                    if len(matches) >= limit:
                        break
        except OSError:
            return []
        self._cache_set(cache_key, matches)
        return matches

    def open_item_in_folder(self, item_name: str, folder: str) -> str:
        matches = self.search_within_folder(item_name, folder, limit=1)
        if not matches:
            return f"I couldn't find {item_name} inside {folder}."
        match = Path(matches[0])
        if match.is_dir():
            return self.open_folder(str(match))
        return self.open_file(str(match))

    def search_web(self, query: str) -> str:
        webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
        return f"Searching the web for {query}."

    def _fast_filename_search(self, needle: str, limit: int) -> list[str]:
        matches: list[str] = []
        try:
            result = subprocess.run(
                f'where /r "{self._home}" *{needle}*',
                capture_output=True,
                text=True,
                timeout=8,
                shell=True,
            )
            lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            matches.extend(lines[:limit])
        except Exception:
            pass
        return matches[:limit]

    def set_brightness(self, percent: int) -> str:
        percent = max(10, min(100, percent))
        script = (
            "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
            f".WmiSetBrightness(1,{percent})"
        )
        return self._run_powershell(script, f"Brightness set to {percent}%.")

    def wifi(self, enabled: bool) -> str:
        state = "enabled" if enabled else "disabled"
        interfaces = self._wifi_interface_names()
        if not interfaces:
            return "I couldn't find a Wi-Fi adapter to control on this machine."
        for interface in interfaces:
            result = subprocess.run(
                f'netsh interface set interface name="{interface}" admin={state}',
                capture_output=True,
                text=True,
                shell=True,
                timeout=12,
            )
            if result.returncode == 0:
                return f"Wi-Fi {'enabled' if enabled else 'disabled'}."
        return "I couldn't change the Wi-Fi state automatically."

    def bluetooth_settings(self) -> str:
        return self._run_command("start ms-settings:bluetooth", "Opening Bluetooth settings.")

    def bluetooth(self, enabled: bool) -> str:
        action = "Enable" if enabled else "Disable"
        script = (
            "$devices = Get-PnpDevice -Class Bluetooth -Status OK -ErrorAction SilentlyContinue;"
            "if (-not $devices) { $devices = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue };"
            f"if ($devices) {{ $devices | ForEach-Object {{ {action}-PnpDevice -InstanceId $_.InstanceId -Confirm:$false -ErrorAction SilentlyContinue }}; exit 0 }} else {{ exit 1 }}"
        )
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            if result.returncode == 0:
                return f"Bluetooth {'enabled' if enabled else 'disabled'}."
        except Exception:
            pass
        fallback = self.bluetooth_settings()
        return (
            f"I couldn't {'enable' if enabled else 'disable'} Bluetooth directly, "
            f"so {fallback.lower()}"
        )

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

    def _wifi_interface_names(self) -> list[str]:
        names: list[str] = []
        commands = [
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "Get-NetAdapter -Physical | Where-Object { $_.Name -match 'Wi-Fi|WiFi|WLAN|Wireless' -or $_.InterfaceDescription -match 'Wi-Fi|WiFi|WLAN|Wireless' } | Select-Object -ExpandProperty Name",
            ],
            ["netsh", "wlan", "show", "interfaces"],
        ]
        try:
            result = subprocess.run(commands[0], capture_output=True, text=True, timeout=10, shell=False)
            names.extend([line.strip() for line in result.stdout.splitlines() if line.strip()])
        except Exception:
            pass
        if names:
            return list(dict.fromkeys(names))
        try:
            result = subprocess.run(commands[1], capture_output=True, text=True, timeout=10, shell=False)
            for line in result.stdout.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                if key.strip().lower() == "name":
                    names.append(value.strip())
        except Exception:
            pass
        return list(dict.fromkeys(names))

    def _resolve_folder(self, folder: str) -> Path | None:
        normalized = folder.lower().strip()
        if normalized in self._special_folders:
            return self._special_folders[normalized]
        expanded = Path(os.path.expandvars(folder)).expanduser()
        if expanded.exists():
            return expanded
        quick = self.search_files(folder, limit=1)
        if quick:
            candidate = Path(quick[0])
            if candidate.is_dir():
                return candidate
            if candidate.parent.exists():
                return candidate.parent
        return None

    def _cache_get(self, key: tuple[str, str, int]) -> list[str] | None:
        cached = self._search_cache.get(key)
        if cached is None:
            return None
        cached_at, value = cached
        if time.monotonic() - cached_at > 20.0:
            self._search_cache.pop(key, None)
            return None
        return list(value)

    def _cache_set(self, key: tuple[str, str, int], value: list[str]) -> None:
        if len(self._search_cache) > 128:
            oldest_key = next(iter(self._search_cache))
            self._search_cache.pop(oldest_key, None)
        self._search_cache[key] = (time.monotonic(), list(value))
