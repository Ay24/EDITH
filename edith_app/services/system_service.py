from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import webbrowser

try:
    from PIL import Image, ImageFilter
except ImportError:
    Image = None
    ImageFilter = None

try:
    from docx import Document
except ImportError:
    Document = None

from edith_app.services.vision_service import VisionService


@dataclass(slots=True)
class PlannedMove:
    source: str
    destination: str
    reason: str


class SystemService:
    def __init__(self, vision: VisionService | None = None, organization_manifest_path: str | None = None) -> None:
        self._home = Path.home()
        self._vision = vision
        self._manifest_path = Path(organization_manifest_path) if organization_manifest_path else Path("data") / "edith_last_organization.json"
        self._special_folders = {
            "downloads": self._known_folder("Downloads", self._home / "Downloads"),
            "documents": self._known_folder("MyDocuments", self._home / "Documents"),
            "desktop": self._known_folder("Desktop", self._home / "Desktop"),
            "pictures": self._known_folder("MyPictures", self._home / "Pictures"),
            "music": self._known_folder("MyMusic", self._home / "Music"),
            "videos": self._known_folder("MyVideos", self._home / "Videos"),
        }
        self._search_roots = [
            self._special_folders["desktop"],
            self._special_folders["documents"],
            self._special_folders["downloads"],
            self._special_folders["pictures"],
            self._home,
        ]
        self._known_apps = {
            "calculator": "calc.exe", "calc": "calc.exe", "notepad": "notepad.exe", "paint": "mspaint.exe",
            "cmd": "cmd.exe", "powershell": "powershell.exe", "explorer": "explorer.exe", "file explorer": "explorer.exe",
            "settings": "start ms-settings:", "task manager": "taskmgr.exe", "control panel": "control.exe", "whatsapp": "start whatsapp:",
        }
        self._known_sites = {
            "notebooklm": "https://notebooklm.google.com/", "chatgpt": "https://chatgpt.com/", "github": "https://github.com/",
            "gmail": "https://mail.google.com/", "google docs": "https://docs.google.com/", "google drive": "https://drive.google.com/",
            "google calendar": "https://calendar.google.com/", "google maps": "https://maps.google.com/", "wikipedia": "https://wikipedia.org/",
            "youtube": "https://www.youtube.com/", "spotify": "https://open.spotify.com/", "notion": "https://www.notion.so/",
            "stackoverflow": "https://stackoverflow.com/", "whatsapp web": "https://web.whatsapp.com/",
        }
        self._search_cache: dict[tuple[str, str, int], tuple[float, list[str]]] = {}
        self._folder_analysis_cache: dict[tuple[str, str], tuple[float, str]] = {}
        self._plan_cache: dict[tuple[str, str, tuple[str, ...]], tuple[float, list[PlannedMove]]] = {}
        self._text_cache: dict[tuple[str, float], str] = {}
        self._image_meta_cache: dict[tuple[str, float], tuple[str, float | None]] = {}
        self._organize_buckets = {
            "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".ppt", ".pptx", ".xls", ".xlsx", ".csv"},
            "Images": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".heic"},
            "Video": {".mp4", ".mkv", ".avi", ".mov", ".webm"},
            "Audio": {".mp3", ".wav", ".flac", ".aac", ".m4a"},
            "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
            "Installers": {".exe", ".msi", ".apk"},
            "Code": {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".md", ".toml", ".yaml", ".yml"},
            "Shortcuts": {".lnk", ".url"},
        }
        self._context_keywords = {
            "Screenshots": {"screenshot", "screen shot", "snip", "capture"},
            "Receipts": {"receipt", "invoice", "bill", "payment", "order"},
            "Designs": {"mockup", "poster", "banner", "logo", "design", "ui", "wireframe"},
            "Personal Photos": {"family", "birthday", "trip", "vacation", "selfie", "wedding"},
            "Study": {"assignment", "lecture", "syllabus", "notes", "exam", "question", "course"},
            "Work": {"meeting", "proposal", "client", "project", "brief", "presentation", "report"},
            "Finance": {"bank", "salary", "tax", "expense", "budget", "statement"},
            "Code Projects": {"src", "component", "config", "package", "module", "script", "app"},
            "Reference": {"guide", "manual", "reference", "tutorial", "readme", "documentation"},
            "Wallpapers": {"wallpaper", "background", "cover"},
            "Downloads Review": {"setup", "installer", "download", "patch", "update"},
        }

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
            return self.open_folder(str(candidate_path)) if candidate_path.is_dir() else self.open_file(str(candidate_path))
        executable = shutil.which(target)
        if executable:
            return self.open_file(executable)
        local_matches = self.search_files(target, limit=1)
        if local_matches:
            first = Path(local_matches[0])
            return self.open_folder(str(first)) if first.is_dir() else self.open_file(str(first))
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
            ranked_quick = self._rank_matches(quick_matches, needle)[:limit]
            self._cache_set(("global", needle, limit), ranked_quick)
            return ranked_quick
        matches: list[str] = []
        for root in self._search_roots:
            if not root.exists():
                continue
            try:
                for path in root.rglob("*"):
                    if needle in path.name.lower():
                        matches.append(str(path))
                        if len(matches) >= limit:
                            ranked = self._rank_matches(matches, needle)[:limit]
                            self._cache_set(("global", needle, limit), ranked)
                            return ranked
            except OSError:
                continue
        ranked = self._rank_matches(matches, needle)[:limit]
        self._cache_set(("global", needle, limit), ranked)
        return ranked

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
                    if len(matches) >= max(limit * 4, limit):
                        break
        except OSError:
            return []
        ranked = self._rank_matches(matches, needle)[:limit]
        self._cache_set(cache_key, ranked)
        return ranked

    def open_item_in_folder(self, item_name: str, folder: str) -> str:
        matches = self.search_within_folder(item_name, folder, limit=1)
        if not matches:
            return f"I couldn't find {item_name} inside {folder}."
        match = Path(matches[0])
        return self.open_folder(str(match)) if match.is_dir() else self.open_file(str(match))

    def analyze_folder(self, folder: str) -> str:
        root = self._resolve_folder(folder)
        if root is None or not root.exists():
            return f"I couldn't find the folder {folder}."
        files = [path for path in root.iterdir() if path.is_file()]
        dirs = [path for path in root.iterdir() if path.is_dir()]
        if not files and not dirs:
            return f"{root.name} looks clean. I didn't find any visible files or folders."
        bucket_counts: dict[str, int] = {}
        for path in files:
            bucket = self._bucket_for(path)
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        top_buckets = ", ".join(f"{name}: {count}" for name, count in sorted(bucket_counts.items(), key=lambda item: item[1], reverse=True)[:6])
        return f"{root.name} has {len(files)} files and {len(dirs)} folders at the top level. " + (f"Main file groups: {top_buckets}." if top_buckets else "No top-level files to group.")

    def analyze_folder_context(self, folder: str) -> str:
        root = self._resolve_folder(folder)
        if root is None or not root.exists():
            return f"I couldn't find the folder {folder}."
        files = [path for path in root.iterdir() if path.is_file()]
        if not files:
            return f"{root.name} has no top-level files to analyze."
        cache_key = self._folder_cache_key(root, "context-analysis")
        cached = self._folder_analysis_cache_get(cache_key)
        if cached is not None:
            return cached
        context_counts: dict[str, int] = {}
        sample_lines: list[str] = []
        duplicates = self._find_duplicate_images(files)
        blurry = self._find_blurry_images(files)
        for path in files[:80]:
            category = self._context_bucket_for(path, root, duplicates, blurry)
            context_counts[category] = context_counts.get(category, 0) + 1
        for path in files[:6]:
            sample_lines.append(f"{path.name} -> {self._context_bucket_for(path, root, duplicates, blurry)}")
        ranked = ", ".join(f"{name}: {count}" for name, count in sorted(context_counts.items(), key=lambda item: item[1], reverse=True)[:8])
        lines = [f"Context analysis for {root.name}: {ranked or 'No strong context groups yet.'}", "Sample classification:", *sample_lines]
        if duplicates:
            lines.append(f"Potential duplicate photos: {len(duplicates)}")
        if blurry:
            lines.append(f"Potential blurry images: {len(blurry)}")
        result = "\n".join(lines)
        self._folder_analysis_cache_set(cache_key, result)
        return result

    def organize_folder(self, folder: str) -> str:
        plan = self._build_plan(folder, mode="extension")
        return self._apply_plan(plan, folder, label="organized")

    def organize_folder_by_context(self, folder: str) -> str:
        plan = self._build_plan(folder, mode="context")
        return self._apply_plan(plan, folder, label="context-organized")

    def preview_organization(self, folder: str, by_context: bool = False) -> str:
        mode = "context" if by_context else "extension"
        plan = self._build_plan(folder, mode=mode)
        return self._summarize_plan(plan, folder, mode)

    def undo_last_organization(self) -> str:
        manifest = self._load_manifest()
        if not manifest:
            return "There is no organization run to undo yet."
        undone = 0
        for move in reversed(manifest.get("moves", [])):
            source = Path(move.get("source", ""))
            destination = Path(move.get("destination", ""))
            if not destination.exists():
                continue
            source.parent.mkdir(parents=True, exist_ok=True)
            target = self._dedupe_destination(source) if source.exists() else source
            try:
                shutil.move(str(destination), str(target))
                undone += 1
            except Exception:
                continue
        try:
            self._manifest_path.unlink(missing_ok=True)
        except Exception:
            pass
        return f"Undid the last organization run and restored {undone} item{'s' if undone != 1 else ''}."

    def move_item(self, item_name: str, destination_folder: str) -> str:
        matches = self.search_files(item_name, limit=1)
        if not matches:
            return f"I couldn't find {item_name}."
        source = Path(matches[0])
        destination_root = self._resolve_folder(destination_folder)
        if destination_root is None:
            destination_root = Path(os.path.expandvars(destination_folder)).expanduser()
            destination_root.mkdir(parents=True, exist_ok=True)
        destination = self._dedupe_destination(destination_root / source.name)
        try:
            shutil.move(str(source), str(destination))
            return f"Moved {source.name} to {destination_root}."
        except Exception as exc:
            return f"I couldn't move {source.name}: {exc}"

    def folder_clutter_report(self, folder: str) -> str:
        root = self._resolve_folder(folder)
        if root is None or not root.exists():
            return f"I couldn't find the folder {folder}."
        files = [path for path in root.iterdir() if path.is_file()]
        large = sorted(files, key=lambda path: path.stat().st_size if path.exists() else 0, reverse=True)[:5]
        duplicate_names: dict[str, int] = {}
        for path in files:
            duplicate_names[path.stem.lower()] = duplicate_names.get(path.stem.lower(), 0) + 1
        repeated = [name for name, count in duplicate_names.items() if count > 1][:5]
        lines = [self.analyze_folder(folder), self.analyze_folder_context(folder)]
        if large:
            lines.append("Largest top-level files: " + ", ".join(f"{path.name}" for path in large))
        if repeated:
            lines.append("Repeated base names: " + ", ".join(repeated))
        return "\n".join(lines)

    def search_web(self, query: str) -> str:
        webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
        return f"Searching the web for {query}."

    def set_brightness(self, percent: int) -> str:
        percent = max(10, min(100, percent))
        script = "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)" f".WmiSetBrightness(1,{percent})"
        return self._run_powershell(script, f"Brightness set to {percent}%.")

    def wifi(self, enabled: bool) -> str:
        state = "enabled" if enabled else "disabled"
        interfaces = self._wifi_interface_names()
        if not interfaces:
            return "I couldn't find a Wi-Fi adapter to control on this machine."
        for interface in interfaces:
            result = subprocess.run(f'netsh interface set interface name="{interface}" admin={state}', capture_output=True, text=True, shell=True, timeout=12)
            if result.returncode == 0:
                return f"Wi-Fi {'enabled' if enabled else 'disabled'}."
        return "I couldn't change the Wi-Fi state automatically."

    def bluetooth_settings(self) -> str:
        return self._run_command("start ms-settings:bluetooth", "Opening Bluetooth settings.")

    def bluetooth(self, enabled: bool) -> str:
        action = "Enable" if enabled else "Disable"
        script = "$devices = Get-PnpDevice -Class Bluetooth -Status OK -ErrorAction SilentlyContinue;if (-not $devices) { $devices = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue };"
        script += f"if ($devices) {{ $devices | ForEach-Object {{ {action}-PnpDevice -InstanceId $_.InstanceId -Confirm:$false -ErrorAction SilentlyContinue }}; exit 0 }} else {{ exit 1 }}"
        try:
            result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], capture_output=True, text=True, timeout=20, shell=False)
            if result.returncode == 0:
                return f"Bluetooth {'enabled' if enabled else 'disabled'}."
        except Exception:
            pass
        fallback = self.bluetooth_settings()
        return f"I couldn't {'enable' if enabled else 'disable'} Bluetooth directly, so {fallback.lower()}"

    def check_updates(self) -> str:
        try:
            result = subprocess.run(["winget", "upgrade", "--include-unknown"], capture_output=True, text=True, timeout=45, shell=False)
            output = (result.stdout or result.stderr or "").strip()
            if not output:
                return "No update information was returned by winget."
            return output[:1800]
        except Exception as exc:
            return f"I couldn't check updates automatically: {exc}"

    def upgrade_apps(self) -> str:
        return self._run_command("winget upgrade --all --include-unknown --silent", "Attempting to upgrade available applications.")

    def lock_pc(self) -> str:
        return self._run_command("rundll32.exe user32.dll,LockWorkStation", "Locking the PC.")

    def sleep_pc(self) -> str:
        return self._run_command("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", "Putting the PC to sleep.")

    def open_website(self, url: str, label: str) -> str:
        webbrowser.open(url)
        return f"Opening {label}."

    def _build_plan(self, folder: str, mode: str) -> list[PlannedMove]:
        root = self._resolve_folder(folder)
        if root is None or not root.exists():
            return []
        files = [path for path in root.iterdir() if path.is_file()]
        plan_cache_key = self._folder_plan_cache_key(root, mode, files)
        cached_plan = self._plan_cache_get(plan_cache_key)
        if cached_plan is not None:
            return cached_plan
        duplicates = self._find_duplicate_images(files)
        blurry = self._find_blurry_images(files)
        plan: list[PlannedMove] = []
        for path in files:
            if str(path) in duplicates:
                bucket, reason = "Duplicates", "duplicate-image-detection"
            elif str(path) in blurry:
                bucket, reason = "Blurry", "blur-detection"
            elif mode == "context":
                bucket, reason = self._context_bucket_for(path, root, duplicates, blurry), "context-analysis"
            else:
                bucket, reason = self._bucket_for(path), "file-type"
            destination = root / self._sanitize_folder_name(bucket) / path.name
            if destination.resolve() == path.resolve():
                continue
            plan.append(PlannedMove(source=str(path), destination=str(destination), reason=reason))
        self._plan_cache_set(plan_cache_key, plan)
        return plan

    def _apply_plan(self, plan: list[PlannedMove], folder: str, label: str) -> str:
        root = self._resolve_folder(folder)
        if root is None or not root.exists():
            return f"I couldn't find the folder {folder}."
        if not plan:
            return f"{root.name} is already fairly organized. I didn't move any top-level files."
        created: set[str] = set()
        applied: list[PlannedMove] = []
        for move in plan:
            source = Path(move.source)
            if not source.exists():
                continue
            destination = self._dedupe_destination(Path(move.destination))
            destination.parent.mkdir(parents=True, exist_ok=True)
            created.add(destination.parent.name)
            try:
                shutil.move(str(source), str(destination))
                applied.append(PlannedMove(source=move.source, destination=str(destination), reason=move.reason))
            except Exception:
                continue
        if not applied:
            return f"{root.name} is already fairly organized. I didn't move any top-level files."
        self._save_manifest(str(root), applied)
        created_text = ", ".join(sorted(created))
        return f"{label.capitalize()} {len(applied)} file{'s' if len(applied) != 1 else ''} in {root.name}. Created or used: {created_text}."

    def _summarize_plan(self, plan: list[PlannedMove], folder: str, mode: str) -> str:
        root = self._resolve_folder(folder)
        if root is None or not root.exists():
            return f"I couldn't find the folder {folder}."
        if not plan:
            return f"{root.name} already looks organized. I don't have any top-level moves to suggest."
        grouped: dict[str, list[PlannedMove]] = {}
        for move in plan:
            grouped.setdefault(Path(move.destination).parent.name, []).append(move)
        lines = [f"Preview for {root.name} using {'context' if mode == 'context' else 'file-type'} organization:"]
        for bucket, moves in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)[:8]:
            sample = ", ".join(Path(move.source).name for move in moves[:3])
            lines.append(f"- {bucket}: {len(moves)} file(s) -> {sample}")
        if any(Path(move.destination).parent.name == "Duplicates" for move in plan):
            lines.append("- Duplicates bucket includes images that look visually identical or near-identical.")
        if any(Path(move.destination).parent.name == "Blurry" for move in plan):
            lines.append("- Blurry bucket includes images with very low sharpness scores.")
        lines.append("Say the matching organize command when you want me to apply it.")
        return "\n".join(lines)

    def _find_duplicate_images(self, files: list[Path]) -> set[str]:
        if Image is None:
            return set()
        hashes: dict[str, list[Path]] = {}
        for path in files:
            if self._bucket_for(path) != "Images":
                continue
            image_hash = self._image_hash(path)
            if image_hash:
                hashes.setdefault(image_hash, []).append(path)
        duplicates: set[str] = set()
        for paths in hashes.values():
            if len(paths) > 1:
                for path in paths[1:]:
                    duplicates.add(str(path))
        return duplicates

    def _find_blurry_images(self, files: list[Path]) -> set[str]:
        if Image is None or ImageFilter is None:
            return set()
        blurry: set[str] = set()
        for path in files:
            if self._bucket_for(path) != "Images":
                continue
            score = self._sharpness_score(path)
            if score is not None and score < 4.0:
                blurry.add(str(path))
        return blurry

    def _image_hash(self, path: Path) -> str:
        cache_key = self._path_cache_key(path)
        cached = self._image_meta_cache.get(cache_key)
        if cached is not None and cached[0]:
            return cached[0]
        try:
            with Image.open(path) as image:
                pixels = list(image.convert("L").resize((8, 8)).getdata())
            avg = sum(pixels) / len(pixels)
            bits = "".join("1" if pixel >= avg else "0" for pixel in pixels)
            image_hash = hashlib.sha1(bits.encode("ascii")).hexdigest()
            sharpness = cached[1] if cached is not None else None
            self._image_meta_cache[cache_key] = (image_hash, sharpness)
            return image_hash
        except Exception:
            return ""

    def _sharpness_score(self, path: Path) -> float | None:
        cache_key = self._path_cache_key(path)
        cached = self._image_meta_cache.get(cache_key)
        if cached is not None and cached[1] is not None:
            return cached[1]
        try:
            with Image.open(path) as image:
                values = list(image.convert("L").resize((128, 128)).filter(ImageFilter.FIND_EDGES).getdata())
            score = (sum(values) / len(values)) if values else None
            image_hash = cached[0] if cached is not None else ""
            self._image_meta_cache[cache_key] = (image_hash, score)
            return score
        except Exception:
            return None

    def _fast_filename_search(self, needle: str, limit: int) -> list[str]:
        matches: list[str] = []
        try:
            result = subprocess.run(f'where /r "{self._home}" *{needle}*', capture_output=True, text=True, timeout=8, shell=True)
            matches.extend([line.strip() for line in result.stdout.splitlines() if line.strip()][:limit])
        except Exception:
            pass
        return matches[:limit]

    def _run_powershell(self, script: str, success_message: str) -> str:
        return self._run_command(f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{script}"', success_message)

    def _run_command(self, command: str, success_message: str) -> str:
        try:
            subprocess.Popen(command, shell=True)
            return success_message
        except Exception as exc:
            return f"I couldn't complete that system action: {exc}"

    def _wifi_interface_names(self) -> list[str]:
        names: list[str] = []
        commands = [
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "Get-NetAdapter -Physical | Where-Object { $_.Name -match 'Wi-Fi|WiFi|WLAN|Wireless' -or $_.InterfaceDescription -match 'Wi-Fi|WiFi|WLAN|Wireless' } | Select-Object -ExpandProperty Name"],
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
                if ":" in line and line.split(":", 1)[0].strip().lower() == "name":
                    names.append(line.split(":", 1)[1].strip())
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

    def _known_folder(self, name: str, fallback: Path) -> Path:
        try:
            path = Path(os.path.expandvars(os.path.expanduser(os.getenv(name, ""))))
            if str(path) and str(path) != "." and path.exists():
                return path
        except Exception:
            pass
        try:
            command = (
                "[Environment]::GetFolderPath("
                f"[Environment+SpecialFolder]::{name}"
                ")"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
            resolved = Path(result.stdout.strip())
            if result.returncode == 0 and result.stdout.strip() and resolved.exists():
                return resolved
        except Exception:
            pass
        return fallback

    def _bucket_for(self, path: Path) -> str:
        suffix = path.suffix.lower()
        for bucket, suffixes in self._organize_buckets.items():
            if suffix in suffixes:
                return bucket
        return "Other"

    def _context_bucket_for(self, path: Path, root: Path, duplicates: set[str], blurry: set[str]) -> str:
        if str(path) in duplicates:
            return "Duplicates"
        if str(path) in blurry:
            return "Blurry"
        ext_bucket = self._bucket_for(path)
        basename = path.stem.lower().replace("_", " ").replace("-", " ")
        full_text = f"{basename} {root.name.lower()} {self._extract_text_sample(path)}".lower()
        if ext_bucket == "Images":
            return self._context_bucket_for_image(path, full_text)
        if ext_bucket == "Documents":
            return self._context_bucket_for_document(full_text)
        if ext_bucket == "Code":
            return "Code Projects"
        if ext_bucket == "Installers":
            return "Downloads Review"
        if ext_bucket in {"Audio", "Video", "Archives", "Shortcuts"}:
            return ext_bucket
        for label, keywords in self._context_keywords.items():
            if any(keyword in full_text for keyword in keywords):
                return label
        return ext_bucket

    def _context_bucket_for_document(self, text: str) -> str:
        for label in ("Finance", "Study", "Work", "Reference", "Receipts"):
            if any(keyword in text for keyword in self._context_keywords[label]):
                return label
        return "Documents"

    def _context_bucket_for_image(self, path: Path, text: str) -> str:
        if any(keyword in text for keyword in self._context_keywords["Screenshots"]):
            return "Screenshots"
        if any(keyword in text for keyword in self._context_keywords["Receipts"]):
            return "Receipts"
        if any(keyword in text for keyword in self._context_keywords["Designs"]):
            return "Designs"
        if any(keyword in text for keyword in self._context_keywords["Wallpapers"]):
            return "Wallpapers"
        if any(keyword in text for keyword in self._context_keywords["Personal Photos"]):
            return "Personal Photos"
        if any(token in text for token in {"document", "paper", "notes", "worksheet", "form"}):
            return "Reference"
        if any(token in text for token in {"chart", "graph", "diagram"}):
            return "Work"
        if Image is not None:
            try:
                with Image.open(path) as image:
                    width, height = image.size
                if width >= 1800 and height >= 900:
                    return "Wallpapers"
                if width >= 1000 and height >= 700 and "img" in path.stem.lower():
                    return "Personal Photos"
            except Exception:
                pass
        if self._vision is not None and self._looks_ambiguous_image(text, path):
            vision_hint = self._vision.describe_image(path)
            if vision_hint:
                enriched = f"{text} {vision_hint.lower()}"
                if any(keyword in enriched for keyword in self._context_keywords["Screenshots"]):
                    return "Screenshots"
                if any(keyword in enriched for keyword in self._context_keywords["Receipts"]):
                    return "Receipts"
                if any(keyword in enriched for keyword in self._context_keywords["Designs"]):
                    return "Designs"
                if any(keyword in enriched for keyword in self._context_keywords["Wallpapers"]):
                    return "Wallpapers"
                if any(keyword in enriched for keyword in self._context_keywords["Personal Photos"]):
                    return "Personal Photos"
                if any(token in enriched for token in {"document", "paper", "notes", "worksheet", "form"}):
                    return "Reference"
                if any(token in enriched for token in {"chart", "graph", "diagram"}):
                    return "Work"
        return "Images"

    def _extract_text_sample(self, path: Path, max_chars: int = 1200) -> str:
        cache_key = self._path_cache_key(path)
        cached = self._text_cache.get(cache_key)
        if cached is not None:
            return cached
        suffix = path.suffix.lower()
        try:
            if suffix in {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css", ".yaml", ".yml", ".toml"}:
                text = path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
                self._text_cache[cache_key] = text
                return text
            if suffix == ".docx" and Document is not None:
                doc = Document(str(path))
                text = "\n".join(paragraph.text for paragraph in doc.paragraphs[:40])[:max_chars]
                self._text_cache[cache_key] = text
                return text
        except Exception:
            return ""
        return ""

    def _sanitize_folder_name(self, name: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*]+', "", name).strip()
        return cleaned or "Other"

    def _dedupe_destination(self, destination: Path) -> Path:
        if not destination.exists():
            return destination
        stem, suffix, parent, counter = destination.stem, destination.suffix, destination.parent, 1
        while True:
            candidate = parent / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _save_manifest(self, folder: str, moves: list[PlannedMove]) -> None:
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"folder": folder, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "moves": [asdict(move) for move in moves]}
        self._manifest_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _load_manifest(self) -> dict[str, object] | None:
        if not self._manifest_path.exists():
            return None
        try:
            return json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except Exception:
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
            self._search_cache.pop(next(iter(self._search_cache)), None)
        self._search_cache[key] = (time.monotonic(), list(value))

    def _rank_matches(self, matches: list[str], needle: str) -> list[str]:
        def score(path_text: str) -> tuple[int, int, int, str]:
            path = Path(path_text)
            name = path.name.lower()
            stem = path.stem.lower()
            lowered_path = path_text.lower()
            exact_name = 1 if name == needle else 0
            exact_stem = 1 if stem == needle else 0
            starts = 1 if name.startswith(needle) or stem.startswith(needle) else 0
            path_contains = 1 if needle in lowered_path else 0
            shorter = -len(path.parts)
            return (
                exact_name,
                exact_stem,
                starts + path_contains,
                shorter,
                lowered_path,
            )

        unique = list(dict.fromkeys(matches))
        unique.sort(key=score, reverse=True)
        return unique

    def _path_cache_key(self, path: Path) -> tuple[str, float]:
        try:
            return (str(path.resolve()), path.stat().st_mtime)
        except OSError:
            return (str(path), 0.0)

    def _folder_cache_key(self, root: Path, mode: str) -> tuple[str, str]:
        try:
            stamp = max((child.stat().st_mtime for child in root.iterdir()), default=root.stat().st_mtime)
        except OSError:
            stamp = time.time()
        return (f"{root.resolve()}::{stamp}", mode)

    def _folder_plan_cache_key(self, root: Path, mode: str, files: list[Path]) -> tuple[str, str, tuple[str, ...]]:
        fingerprint = tuple(
            f"{path.name}:{int(path.stat().st_mtime)}:{path.stat().st_size}"
            for path in sorted(files, key=lambda item: item.name.lower())[:200]
        )
        return (str(root.resolve()), mode, fingerprint)

    def _folder_analysis_cache_get(self, key: tuple[str, str]) -> str | None:
        cached = self._folder_analysis_cache.get(key)
        if cached is None:
            return None
        cached_at, value = cached
        if time.monotonic() - cached_at > 20.0:
            self._folder_analysis_cache.pop(key, None)
            return None
        return value

    def _folder_analysis_cache_set(self, key: tuple[str, str], value: str) -> None:
        if len(self._folder_analysis_cache) > 32:
            self._folder_analysis_cache.pop(next(iter(self._folder_analysis_cache)), None)
        self._folder_analysis_cache[key] = (time.monotonic(), value)

    def _plan_cache_get(self, key: tuple[str, str, tuple[str, ...]]) -> list[PlannedMove] | None:
        cached = self._plan_cache.get(key)
        if cached is None:
            return None
        cached_at, plan = cached
        if time.monotonic() - cached_at > 20.0:
            self._plan_cache.pop(key, None)
            return None
        return [PlannedMove(move.source, move.destination, move.reason) for move in plan]

    def _plan_cache_set(self, key: tuple[str, str, tuple[str, ...]], plan: list[PlannedMove]) -> None:
        if len(self._plan_cache) > 24:
            self._plan_cache.pop(next(iter(self._plan_cache)), None)
        self._plan_cache[key] = (
            time.monotonic(),
            [PlannedMove(move.source, move.destination, move.reason) for move in plan],
        )

    def _looks_ambiguous_image(self, text: str, path: Path) -> bool:
        hint_tokens = {
            "screenshot",
            "screen shot",
            "receipt",
            "invoice",
            "bill",
            "poster",
            "banner",
            "logo",
            "design",
            "wallpaper",
            "family",
            "trip",
            "selfie",
            "document",
            "notes",
            "chart",
            "graph",
            "diagram",
        }
        lowered_name = path.stem.lower().replace("_", " ").replace("-", " ")
        if any(token in text or token in lowered_name for token in hint_tokens):
            return False
        return True
