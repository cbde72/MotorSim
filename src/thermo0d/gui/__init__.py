from __future__ import annotations

"""GUI package for thermo0d editors.

This package intentionally keeps heavy PySide6 imports inside the concrete
editor modules so helper utilities like signal catalog generation can be used
without a Qt runtime.
"""

from .signal_catalog import (
    DEFAULT_SIGNAL_CATALOG_NAME,
    build_signal_catalog_for_project,
    generate_signal_catalog_file,
)

__all__ = [
    "DEFAULT_SIGNAL_CATALOG_NAME",
    "build_signal_catalog_for_project",
    "generate_signal_catalog_file",
]
