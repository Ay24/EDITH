"""Edith desktop assistant package."""

from __future__ import annotations

import warnings


warnings.filterwarnings(
    "ignore",
    message="CUDA path could not be detected.*",
    category=UserWarning,
    module=r"cupy\._environment",
)
warnings.filterwarnings(
    "ignore",
    message="CUDA initialization:.*",
    category=UserWarning,
    module=r"torch\.cuda\.__init__",
)
