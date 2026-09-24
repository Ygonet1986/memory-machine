"""Open (and cache) the Companion window for the desktop app.

Qt-free at import time: the window and backend are imported lazily so the CI
environment (no PySide6) can import this module.
"""

from __future__ import annotations

from typing import Any

_WINDOW: list[Any] = []


def open_companion() -> Any:
    """Return the single Companion window, creating it on first use."""
    if not _WINDOW:
        from .companion_backend import CompanionBackend
        from .ui.companion_window import CompanionWindow

        _WINDOW.append(CompanionWindow(CompanionBackend()))
    window = _WINDOW[0]
    window.showNormal()
    window.raise_()
    return window
