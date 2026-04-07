from __future__ import annotations

import sys
import traceback

from edith_app.assistant import EdithAssistant
from edith_app.config import AppConfig
from edith_app.services.bootstrap_service import BootstrapService
from edith_app.services.logging_service import get_logger
from edith_app.ui import EdithDesktopUI


def main() -> None:
    config = AppConfig()
    logger = get_logger("edith.app", config.runtime_log_path)

    def _handle_uncaught(exc_type, exc_value, exc_tb) -> None:
        logger.error("Uncaught exception in main thread: %s", "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))

    sys.excepthook = _handle_uncaught
    logger.info("Starting Edith app runtime")

    bootstrap = BootstrapService(config)
    bootstrap.start_async()
    assistant = EdithAssistant(config)
    ui = EdithDesktopUI(assistant)
    ui.run()
