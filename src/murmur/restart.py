"""Process-relaunch helper used by the hotkey-change confirmation modal.

Hotkey changes can't be safely hot-reloaded into the running pynput
listener — see ``main_window`` and #38 for the full story. The user
confirms the relaunch via a "Restart Murmur to apply?" modal; this
module provides the actual ``os.execv`` call. Kept separate so the main
window can swap it out in tests.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from ._logging import get_logger

_log = get_logger("restart")


def _default_relaunch() -> None:
    _log.info("relaunching: %s %s", sys.executable, sys.argv)
    app = QApplication.instance()
    if app is not None:
        app.quit()
    # ``os.execv`` replaces the current process image — works for both
    # ``python -m murmur`` (sys.executable is the venv python) and a
    # PyInstaller-built ``Murmur.app`` (sys.executable is the bundle's
    # binary, sys.argv[0] is the same).
    os.execv(sys.executable, [sys.executable, *sys.argv])
