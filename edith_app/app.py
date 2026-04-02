from __future__ import annotations

from edith_app.assistant import EdithAssistant
from edith_app.config import AppConfig
from edith_app.services.bootstrap_service import BootstrapService
from edith_app.ui import EdithDesktopUI


def main() -> None:
    config = AppConfig()
    bootstrap = BootstrapService(config)
    bootstrap.start_async()
    assistant = EdithAssistant(config)
    ui = EdithDesktopUI(assistant)
    ui.run()
