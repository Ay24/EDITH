from __future__ import annotations

import threading
import time
from typing import Callable, Any, TypeVar

T = TypeVar("T")

class AsyncWrapper:
    """Safely runs blocking operations in background threads with a non-blocking UI feel."""

    @staticmethod
    def run_in_background(func: Callable[..., T], *args, on_complete: Callable[[T | Exception], None] | None = None) -> threading.Thread:
        def _target():
            try:
                result = func(*args)
                if on_complete:
                    on_complete(result)
                return result
            except Exception as e:
                if on_complete:
                    on_complete(e)
                return e

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        return thread

    @staticmethod
    def run_with_timeout(func: Callable[..., T], timeout: float, *args) -> T | None:
        result = [None]
        exception = [None]
        
        def _target():
            try:
                result[0] = func(*args)
            except Exception as e:
                exception[0] = e

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout)
        
        if thread.is_alive():
            # The operation timed out
            return None
        if exception[0]:
            raise exception[0]
        return result[0]
