from __future__ import annotations

import socket
import time


class ConnectivityService:
    def __init__(self) -> None:
        self._cache: tuple[float, bool] = (0.0, False)

    def is_online(self) -> bool:
        checked_at, cached = self._cache
        now = time.monotonic()
        if now - checked_at < 5.0:
            return cached
        online = self._probe()
        self._cache = (now, online)
        return online

    def _probe(self) -> bool:
        for host, port in (("1.1.1.1", 53), ("8.8.8.8", 53)):
            try:
                with socket.create_connection((host, port), timeout=1.2):
                    return True
            except OSError:
                continue
        return False
