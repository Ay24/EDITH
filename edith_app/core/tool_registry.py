from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import time


@dataclass(slots=True)
class ToolObservation:
    name: str
    detail: str


class ToolRegistry:
    def __init__(self, workspace_root: str) -> None:
        self._root = Path(workspace_root)
        self._ignored_parts = {".git", ".venv", "venv", "__pycache__", ".idea"}
        self._observation_cache: dict[tuple[str, str, int], tuple[float, ToolObservation]] = {}

    def project_summary(self) -> ToolObservation:
        cached = self._cache_get(("project_summary", "", 0), ttl=20.0)
        if cached is not None:
            return cached
        counts: dict[str, int] = {}
        for path in self._root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in self._ignored_parts for part in path.parts):
                continue
            ext = path.suffix.lower() or "<none>"
            counts[ext] = counts.get(ext, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:10]
        detail = "\n".join(f"{ext}: {count}" for ext, count in ranked) if ranked else "No files found."
        observation = ToolObservation("project_summary", detail)
        self._cache_set(("project_summary", "", 0), observation)
        return observation

    def workspace_snapshot(self, limit: int = 40) -> ToolObservation:
        cached = self._cache_get(("workspace_snapshot", "", limit), ttl=10.0)
        if cached is not None:
            return cached
        files: list[str] = []
        for path in self._root.rglob("*"):
            if path.is_dir():
                if path.name in self._ignored_parts:
                    continue
                continue
            rel = path.relative_to(self._root)
            if any(part in self._ignored_parts for part in rel.parts):
                continue
            files.append(str(rel))
            if len(files) >= limit:
                break
        detail = "\n".join(files) if files else "No visible files found."
        observation = ToolObservation("workspace_snapshot", detail)
        self._cache_set(("workspace_snapshot", "", limit), observation)
        return observation

    def search_text(self, needle: str, limit: int = 12) -> ToolObservation:
        matches: list[str] = []
        lowered = needle.lower().strip()
        if not lowered:
            return ToolObservation("search_text", "No search text provided.")
        cached = self._cache_get(("search_text", lowered, limit), ttl=12.0)
        if cached is not None:
            return cached
        for path in self._root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in self._ignored_parts for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if lowered in line.lower():
                    matches.append(f"{path.relative_to(self._root)}:{line_no}: {line.strip()[:180]}")
                    if len(matches) >= limit:
                        observation = ToolObservation("search_text", "\n".join(matches))
                        self._cache_set(("search_text", lowered, limit), observation)
                        return observation
        observation = ToolObservation("search_text", "\n".join(matches) if matches else f"No matches found for '{needle}'.")
        self._cache_set(("search_text", lowered, limit), observation)
        return observation

    def read_file(self, relative_path: str, max_lines: int = 120) -> ToolObservation:
        path = (self._root / relative_path).resolve()
        try:
            path.relative_to(self._root.resolve())
        except Exception:
            return ToolObservation("read_file", "Refused to read outside the workspace.")
        if not path.exists() or not path.is_file():
            return ToolObservation("read_file", f"File not found: {relative_path}")
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception as exc:
            return ToolObservation("read_file", f"Could not read {relative_path}: {exc}")
        snippet = "\n".join(f"{idx + 1}: {line}" for idx, line in enumerate(lines[:max_lines]))
        return ToolObservation("read_file", f"{relative_path}\n{snippet}")

    def run_compile_check(self) -> ToolObservation:
        cached = self._cache_get(("compile_check", "", 0), ttl=15.0)
        if cached is not None:
            return cached
        try:
            result = subprocess.run(
                ["python", "-m", "compileall", ".", "-q"],
                cwd=self._root,
                capture_output=True,
                text=True,
                timeout=120,
                shell=False,
            )
            output = (result.stdout + "\n" + result.stderr).strip()
            if result.returncode == 0:
                observation = ToolObservation("compile_check", "Compile check passed.")
                self._cache_set(("compile_check", "", 0), observation)
                return observation
            observation = ToolObservation("compile_check", output or "Compile check failed.")
            self._cache_set(("compile_check", "", 0), observation)
            return observation
        except Exception as exc:
            return ToolObservation("compile_check", f"Compile check could not run: {exc}")

    def open_browser_search(self, query: str) -> ToolObservation:
        return ToolObservation("browser_search", f"Suggested browser search: {query}")

    def search_filenames(self, needle: str, limit: int = 12) -> ToolObservation:
        lowered = needle.lower().strip()
        cached = self._cache_get(("search_filenames", lowered, limit), ttl=12.0)
        if cached is not None:
            return cached
        matches: list[str] = []
        for path in self._root.rglob("*"):
            if any(part in self._ignored_parts for part in path.parts):
                continue
            if lowered in path.name.lower():
                matches.append(str(path.relative_to(self._root)))
                if len(matches) >= limit:
                    break
        observation = ToolObservation("search_filenames", "\n".join(matches) if matches else f"No filenames found for '{needle}'.")
        self._cache_set(("search_filenames", lowered, limit), observation)
        return observation

    def suggest_edit_targets(self, goal: str, limit: int = 6) -> ToolObservation:
        lowered = goal.lower()
        candidates: list[str] = []
        keywords = [word for word in lowered.split() if len(word) >= 4][:6]
        for path in self._root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".py", ".md", ".toml", ".json", ".txt"}:
                continue
            if any(part in self._ignored_parts for part in path.parts):
                continue
            score = 0
            path_text = str(path.relative_to(self._root)).lower()
            for keyword in keywords:
                if keyword in path_text:
                    score += 2
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except Exception:
                text = ""
            for keyword in keywords:
                if keyword in text:
                    score += 1
            if score > 0:
                candidates.append((score, str(path.relative_to(self._root))))
        candidates.sort(key=lambda item: item[0], reverse=True)
        top = [path for _, path in candidates[:limit]]
        return ToolObservation("edit_targets", "\n".join(top) if top else "No strong edit targets found yet.")

    def _cache_get(self, key: tuple[str, str, int], ttl: float) -> ToolObservation | None:
        cached = self._observation_cache.get(key)
        if cached is None:
            return None
        cached_at, observation = cached
        if time.monotonic() - cached_at > ttl:
            self._observation_cache.pop(key, None)
            return None
        return observation

    def _cache_set(self, key: tuple[str, str, int], observation: ToolObservation) -> None:
        if len(self._observation_cache) > 64:
            self._observation_cache.pop(next(iter(self._observation_cache)), None)
        self._observation_cache[key] = (time.monotonic(), observation)
