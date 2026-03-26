from __future__ import annotations

import os
import subprocess
import urllib.parse
import webbrowser

from edith_app.config import AppConfig

try:
    import pywhatkit
except ImportError:
    pywhatkit = None


class MediaService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._spotify_playlists = {
            "deep focus": "spotify:playlist:37i9dQZF1DWZeKCadgRdKQ",
            "cinematic": "spotify:playlist:37i9dQZF1DX1tz6EDao8it",
            "coding": "spotify:playlist:37i9dQZF1DX8NTLI2TtZa6",
            "lofi": "spotify:playlist:37i9dQZF1DWWQRwui0ExPn",
            "ambient": "spotify:playlist:37i9dQZF1DX4E3UdUs7fUx",
        }

    def open_youtube_home(self) -> str:
        webbrowser.open("https://www.youtube.com/")
        return "Opening YouTube."

    def search_youtube(self, query: str) -> str:
        if pywhatkit is not None:
            try:
                pywhatkit.playonyt(query)
                return f"Playing {query} on YouTube."
            except Exception:
                pass
        encoded = urllib.parse.quote_plus(query)
        webbrowser.open(f"https://www.youtube.com/results?search_query={encoded}")
        return f"Searching YouTube for {query}."

    def launch_youtube_mix(self, query: str) -> str:
        if pywhatkit is not None:
            try:
                pywhatkit.playonyt(f"{query} mix")
                return f"Playing a YouTube mix for {query}."
            except Exception:
                pass
        encoded = urllib.parse.quote_plus(query)
        webbrowser.open(f"https://www.youtube.com/results?search_query={encoded}&sp=EgIQAw%253D%253D")
        return f"Launching a YouTube mix for {query}."

    def open_spotify(self) -> str:
        app_path = self._config.spotify_app_path
        if app_path and os.path.exists(app_path):
            subprocess.Popen(app_path)
            return "Opening Spotify."
        webbrowser.open("https://open.spotify.com/")
        return "Opening Spotify Web."

    def search_spotify(self, query: str) -> str:
        deep_link = f"spotify:search:{query}"
        if self._open_spotify_uri(deep_link):
            return f"Opening Spotify search for {query}."
        encoded = urllib.parse.quote_plus(query)
        webbrowser.open(f"https://open.spotify.com/search/{encoded}")
        return f"Searching Spotify for {query}."

    def playlist_for_vibe(self, vibe: str) -> str:
        lowered = vibe.lower()
        for key, uri in self._spotify_playlists.items():
            if key in lowered:
                if self._open_spotify_uri(uri):
                    return f"Opening a Spotify {key} playlist."
        return self.search_spotify(f"{vibe} playlist")

    def open_site(self, url: str, label: str) -> str:
        webbrowser.open(url)
        return f"Opening {label}."

    def _open_spotify_uri(self, uri: str) -> bool:
        try:
            subprocess.Popen(f'start "" "{uri}"', shell=True)
            return True
        except Exception:
            return False
